"""Measure actual signed and paired compiler/linker executions for Ruff's ty_server edit."""

import argparse
import gzip
import json
from pathlib import Path
import zipfile

from dyld import check as check_dyld
from macho_paths import compare
from measure import fresh, retire, select
from native_inputs import run_archive_check
from study import check_host, digest, env_for, load, need, save, sdk_id, sha
from ty_links import A, B, CensusTrace, NEW, checkout, collect, run_focus

SIGNED_DIGEST = "086a5224bf973b7fbfa3f2e5567ff048a1ca8867287eb4a75b6e3a4907e34567"
WORKSPACE_PHASES = [
    ("cold", "old"),
    ("edit", "new"),
    ("repeat-1", "new"),
    ("repeat-2", "new"),
]


def enroll_signed(archive):
    need(sha(archive) == SIGNED_DIGEST, "wrong signed focused artifact")
    with zipfile.ZipFile(archive) as z:

        def record(name):
            return json.loads(z.read(name))

        result = record("ty-focus/result.json")
        need(
            result["source"] == [A, B]
            and all(all(c.values()) for c in result["comparisons"].values()),
            "signed clean mismatch",
        )
        old, new = (result["clean"][s] for s in ("old", "new"))
        need(
            set(new["inventory"]) - set(old["inventory"]) == {NEW}
            and set(old["inventory"]) < set(new["inventory"])
            and old["raw"] != new["raw"],
            "wrong signed e2e transition",
        )
        for phase in ("edit", "repeat-1", "repeat-2", "invalid", "repair"):
            prefix = "ty-focus/visit/" + phase + "/"
            row = record(prefix + "verified.json")
            data = {
                field: gzip.decompress(z.read(prefix + file + ".gz"))
                for field, file in (
                    ("native_events", "exec.json"),
                    ("stdout", "stdout"),
                    ("stderr", "stderr"),
                )
            }
            need(
                {k: digest(v) for k, v in data.items()} == row["streams"],
                "signed stream changed",
            )
            events = json.loads(data["native_events"])
            crates = []
            outputs = []
            for event in events:
                args = event["argv"]
                if (
                    event["path"].endswith("/signed/bin/rustc")
                    and "--crate-name" in args
                ):
                    crates.append(args[args.index("--crate-name") + 1])
                if event["path"].endswith("/XcodeDefault.xctoolchain/usr/bin/ld"):
                    (out,) = [v for k, v in zip(args, args[1:]) if k == "-o"]
                    outputs.append(out)
            expected_crates = ["e2e", "ty_server", "zmij"]
            if phase.startswith("repeat"):
                expected_crates = ["e2e", "zmij"]
            elif phase == "invalid":
                expected_crates = ["ty_server", "zmij"]
            need(
                sorted(crates) == expected_crates,
                "different signed physical rustc invocations",
            )
            rows = list(map(json.loads, data["stdout"].splitlines()))
            valid = phase != "invalid"
            need(
                rows[-1] == {"reason": "build-finished", "success": valid}
                and row["exit"] == (0 if valid else 101),
                "signed Cargo verdict",
            )
            if valid:
                (exe,) = (
                    r["executable"]
                    for r in rows
                    if r.get("executable")
                    and r["target"]["name"] == "e2e"
                    and r["profile"]["test"]
                )
                need(
                    outputs == [exe] and row["binary_roster"][exe]["sha"] == new["raw"],
                    "signed linker output changed",
                )
                case = NEW.rsplit("::", 1)[1]
                verdict = gzip.decompress(z.read(prefix + case + "-stdout.gz"))
                need(
                    record(prefix + case + "-exit.json") == 0
                    and ("test " + NEW + " ... ok").encode() in verdict,
                    "signed selected test failed",
                )
            else:
                need(
                    not outputs
                    and any(
                        (r.get("message", {}).get("code") or {}).get("code") == "E0425"
                        for r in rows
                    ),
                    "signed invalid edit did not fail",
                )
    return {
        "source": [A, B],
        "artifact_sha256": SIGNED_DIGEST,
        "signed_repeat_e2e_links": [1, 1],
    }


def run_pair_focus(root, trace):
    top = root / "receipts/ty-comparison"
    refs = {}
    for role in ("P", "C"):
        check_dyld(root, role, select(root, role), top / role / "dyld")
        refs[role] = run_focus(root, trace, role)
        run_archive_check(root, role, trace)

    for state in ("old", "new"):
        inputs = {}
        for role in ("P", "C"):
            row = load(
                top / role / "focus" / ("empty-" + state) / "clean/verified.json"
            )
            (path,) = row["binary_roster"]
            (args,) = [
                link["argv"]
                for link in row["native"]["linkers"]
                if [v for k, v in zip(link["argv"], link["argv"][1:]) if k == "-o"]
                == [path]
            ]
            ref = refs[role][state]
            data = gzip.decompress(
                (
                    root / "receipts/clean-ty-executables" / (ref["raw"] + ".macho.gz")
                ).read_bytes()
            )
            need(digest(data) == ref["raw"], "wrong clean test executable")
            inputs[role] = data, path, args
        need(
            all(
                refs["P"][state][k] == refs["C"][state][k]
                for k in ("text", "inventory")
            ),
            "changed code or test names between compilers",
        )
        save(top / ("clean-equivalence-" + state + ".json"), compare(inputs))
    counts = {}
    for role in ("P", "C"):
        counts[role] = {}
        for phase in ("cold", "edit", "repeat-1", "repeat-2", "invalid", "repair"):
            row = load(top / role / "focus/visit" / phase / "verified.json")
            counts[role][phase] = {
                "full": row["native"]["full"],
                "links": len(row["native"]["linkers"]),
                "e2e_links": row["e2e_links"],
            }
    save(top / "focused-physical.json", counts)


def roster(row):
    by_unit = {
        (pkg, name, tuple(kind)): (path, data)
        for path, data in row["binary_roster"].items()
        for pkg, name, kind in [data["unit"]]
    }
    need(len(by_unit) == len(row["binary_roster"]), "ambiguous logical executable")
    return by_unit


def run_pair_workspace(root, trace):
    # All arms use one spelling for their work directory. Start empty before each
    # sequence and again before the clean B build, including Cargo's shared files.
    top = root / "receipts/ty-comparison/workspace"
    work = root / "ty-compared-workspace"
    work.mkdir()
    summary = {}
    shapes = {}
    for role in ("P", "C"):
        sdk = select(root, role)
        env = env_for(work, sdk)
        identity = None
        snapshots = {}
        for sequence, phases in (
            ("visit", WORKSPACE_PHASES),
            ("empty-new", [("clean", "new")]),
        ):
            check_host(root, 65)
            fresh(work, root / "seed")
            current = sdk_id(sdk, env)
            if identity is None:
                identity = current
            need(current == identity, "changed workspace compiler")
            before = None
            for label, state in phases:
                if before != state:
                    checkout(root / "ruff", state)
                before = state
                dest = top / role / sequence / label
                collect(root, "workspace", work, sdk, env, trace, dest, state, label)
                snapshots[label] = load(dest / "verified.json")
            retire(work)
        need(identity == sdk_id(sdk, env), "workspace SDK drift")
        clean = roster(snapshots["clean"])
        summary[role] = {}
        shapes[role] = set(clean)
        for phase, row in snapshots.items():
            binaries = roster(row)
            need(set(binaries) == shapes[role], "different logical test outputs")
            mismatches = []
            if phase != "cold":
                mismatches = [
                    list(key)
                    for key, (_, cur) in binaries.items()
                    if (cur["sha"], cur["bytes"])
                    != (clean[key][1]["sha"], clean[key][1]["bytes"])
                ]
                need(
                    row["e2e"] == snapshots["clean"]["e2e"],
                    "workspace e2e differs from clean",
                )
            summary[role][phase] = {
                "physical_rustcs": row["native"]["full"],
                "link_only": row["native"]["link_only"],
                "all_linkers": len(row["native"]["linkers"]),
                "e2e_links": row["e2e_links"],
                "test_count": len(binaries),
                "linked_tests": [
                    list(key)
                    for key, (_, info) in sorted(binaries.items())
                    if info["links"]
                ],
                "mismatches_to_clean_B": mismatches,
            }
            save(top / role / ("counts-" + phase + ".json"), summary[role][phase])
    need(shapes["P"] == shapes["C"], "different test outputs between compilers")
    save(top / "paired-physical.json", summary)
    need(
        all(
            not obs["mismatches_to_clean_B"]
            for arm in summary.values()
            for obs in arm.values()
        ),
        "one or more workspace binaries differ from independent clean B",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("enroll", "focus", "workspace"))
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if args.mode == "enroll":
        save(root / "receipts/enrolled-ty.json", enroll_signed(root / "signed-ty.zip"))
    else:
        need(
            load(root / "receipts/enrolled-ty.json")["artifact_sha256"] == SIGNED_DIGEST
            and (root / "receipts/observer.json").is_file(),
            "missing signed enrollment or kernel observer",
        )
        trace = CensusTrace()
        try:
            trace.ready()
            (run_pair_focus if args.mode == "focus" else run_pair_workspace)(
                root, trace
            )
        finally:
            trace.close()
