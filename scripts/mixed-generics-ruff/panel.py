"""Run identical untouched Ruff commands in independent untraced-PMU and kernel-exec histories."""

import argparse
import collections
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kits import CARGO, ENROLL, HERE, HOST, WILD, need, sha, write
import observe
import chunks
import state as s

E2E = [
    "cargo",
    "+ohm",
    "test",
    "--no-run",
    "-p",
    "ty_server",
    "--test",
    "e2e",
    "--locked",
    "--offline",
    "-j8",
    "--message-format=json",
]
CHECK = [
    "cargo",
    "+ohm",
    "check",
    "-p",
    "ty_project",
    "--tests",
    "--locked",
    "--offline",
    "-j8",
    "--message-format=json",
]
ROLES = {
    "e2e-parent": ("e2e", "parent", "parent"),
    "e2e-candidate": ("e2e", "candidate", "candidate"),
    "stage-to-candidate": ("migration", "parent", "candidate"),
    "stage-to-sham": ("migration", "parent", "parent"),
    "signed-to-candidate": ("migration", "signed", "candidate"),
}


def visit(root, role, stream, name, mode, stamp):
    kind = ROLES[role][0]
    cli = E2E if kind == "e2e" else CHECK
    want = 101 if mode == "invalid" else 0
    label = f"{stream}/{name}"
    loc = root / "receipts" / label
    loc.mkdir(parents=True)
    sdk = root / "installed/current"
    e = s.env(root)
    s.state(root, kind, mode)
    paths = set(ENROLL[kind]["original"]) | ({s.BAD_PATH} if kind == "migration" else set())
    touched = {
        n: (
            [sha(root / "ruff" / n), (root / "ruff" / n).stat().st_mtime_ns]
            if (root / "ruff" / n).exists()
            else None
        )
        for n in sorted(paths)
    }
    write(loc / "source.json", touched)
    loose = []

    def verify(ok, msg):
        if not ok:
            loose.append(msg)

    with tempfile.TemporaryDirectory(dir=root / "slot/tmp") as tmp:
        t = Path(tmp)
        if stream == "pmu":
            args = [root / "observers/watch", loc / "whole.json", *cli]
        elif stream == "trace":
            args = [root / "observers/observe", t, root / "observers/never-selected", "cal", *cli]
        else:
            args = cli
        p = subprocess.run(args, cwd=root / "ruff", env=e, capture_output=True, timeout=3900)
        s.payload(loc / "stdout.jsonl.gz", p.stdout)
        s.payload(loc / "stderr.gz", p.stderr)
        print(role, label, mode, "exit", p.returncode, flush=True)
        write(
            loc / "command.json",
            {"environment": e, "argv": cli, "working_directory": str(root / "ruff"), "status": p.returncode},
        )
        lines = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
        terminal = lines[-1] if lines else None
        verify(p.returncode == want, f"unexpected Cargo exit (expected {want}, observed {p.returncode})")
        verify(
            terminal == {"reason": "build-finished", "success": not bool(want)},
            "incorrect Cargo terminal result",
        )
        panic = (p.stdout + p.stderr).lower()
        verify(
            all(
                v not in panic
                for v in (
                    b"internal compiler error",
                    b"the compiler unexpectedly panicked",
                    b"the compiler panicked",
                )
            ),
            "compiler panic",
        )
        messages = [r["message"] for r in lines if r.get("reason") == "compiler-message"]
        errs = [m for m in messages if m.get("level") == "error"]
        codes = [(m.get("code") or {}).get("code") for m in errs if m.get("code")]
        normalized = []
        for m in errs:
            if not m.get("code"):
                continue
            anchors = [
                {
                    "file": x["file_name"],
                    "line": x["line_start"],
                    "column": x["column_start"],
                    "text": [t["text"] for t in x["text"]],
                }
                for x in m.get("spans", [])
                if x["is_primary"]
            ]
            normalized.append({"code": m["code"]["code"], "message": m["message"], "primary": anchors})
        if want:
            verify(
                set(codes) == {"E0308"}
                and any(
                    z["code"] == "E0308"
                    and any(
                        a["file"].endswith(s.BAD_PATH)
                        and any("OHM_ACTUAL_COMPILER_MIGRATION_E0308" in t for t in a["text"])
                        for a in z["primary"]
                    )
                    for z in normalized
                ),
                "missing or unrelated malformed-input diagnostic",
            )
        else:
            verify(not errs, "unexpected diagnostics on valid inputs")
        arts = [r for r in lines if r.get("reason") == "compiler-artifact"]
        inventory = sorted(
            {
                json.dumps(
                    [
                        a["package_id"],
                        a["target"]["name"],
                        a["target"]["kind"],
                        a["features"],
                        a["profile"]["test"],
                    ],
                    separators=(",", ":"),
                )
                for a in arts
            }
        )
        write(loc / "logical-units.json", inventory)
        refs, generators, metadata_paths = observe.workspace_product(root, lines, loc)
        nonempty = {k: v for k, v in refs.items() if v["stamp"]}
        stale = {k: v["stamp"] for k, v in nonempty.items() if v["stamp"] != stamp}
        retained = (
            observe.confirm_stale(root, label, refs, stale, metadata_paths)
            if kind == "migration" and stale and not want and p.returncode == 0
            else {}
        )
        for proof in retained.values():
            verify(
                proof["status"] == 1 and "E0514" in proof["diagnostics"] and not proof["written"],
                "active direct reader did not independently reject retained wrong-epoch user metadata as expected",
            )
        if kind == "migration" and not want and p.returncode == 0:
            verify(
                bool(nonempty) and any("crates/ty_project/" in k for k in refs),
                "valid check returned no usable workspace metadata",
            )
            verify(not stale, "Cargo returned nonempty workspace metadata from a different compiler stamp")
            verify(set(generators) == set(s.GEN), "incomplete generated Rust sources")
        actual = None
        exe = None
        if kind == "e2e" and p.returncode == 0:
            returned = [
                Path(a["executable"])
                for a in arts
                if a.get("executable")
                and a["target"]["name"] == "e2e"
                and a["target"]["kind"] == ["test"]
                and a["target"]["src_path"] == str(root / "ruff/crates/ty_server/tests/e2e/main.rs")
            ]
            verify(len(returned) == 1, "Cargo returned wrong test binary")
            if len(returned) == 1:
                exe = returned[0]
                need(
                    exe.is_file() and exe.is_relative_to(root / "slot"), "program outside owned target/build"
                )
                actual = observe.native_reader(root, label, exe, mode)
                verify(actual["valid_inventory"], "actual e2e inventory failed or lost its stable control")
                expected_original = mode == "original"
                verify(
                    len(actual["new_cases"]) == int(expected_original),
                    "actual notebook test inventory differs from edit",
                )
                verify(
                    all(t == {"code": 0, "one_named": True} for t in actual["runtime"].values()),
                    "real test/snapshot verdict failed",
                )
        physical = None
        counts = None
        if stream == "trace":
            events, physical = observe.physical(t, sdk, cli, exe)
            s.payload(loc / "execs.json.gz", json.dumps(events, separators=(",", ":")).encode())
            write(loc / "physical.json", physical)
            verify(physical["counters"]["root"][1] == p.returncode, "observed foreground status differs")
            if kind == "e2e" and name in ("edited", "restored"):
                verify(
                    any(v["same_returned_e2e"] for v in physical["wild"]),
                    "changed/returned e2e was not physically linked by signed Wild",
                )
            verify(
                not any(v["same_returned_e2e"] for v in physical["other_links"]),
                "foreign linker produced the returned e2e",
            )
        elif stream == "pmu":
            counts = json.loads((loc / "whole.json").read_text())
            need(
                observe.calibrated(counts) and counts["code"] == p.returncode,
                "invalid whole-command PMU sample",
            )
    state = s.storage(root, loc)
    out = {
        "state": mode,
        "source": touched,
        "active_stamp": stamp,
        "status": p.returncode,
        "terminal": terminal,
        "diagnostics": normalized,
        "logical_units": s.digest(json.dumps(inventory).encode()),
        "allocated": state,
        "generated": generators,
        "workspace_metadata": refs,
        "stale_metadata": stale,
        "retained_reader": retained,
        "physical": physical,
        "pmu": counts,
        "test": actual,
        "issues": loose,
    }
    write(loc / "visit.json", out)
    return out


def stage(root, kits, title, role, kind, sham=False):
    s.state(root, kind, "original")
    meta = s.copy_sdk(root, kits, role, title, sham)
    stamp = observe.issuer(root, title)
    epoch = "1" if role in ("signed", "parent") else "2"
    need(
        stamp == meta["rustc_vv"].splitlines()[0] + " (Ohm metadata " + epoch + ")",
        "active compiler did not issue its own enrolled epoch",
    )
    return {**meta, "stamp": stamp}


def run(root, workspace, kits, role):
    kind, old, new = ROLES[role]
    s.unit_dir(root)
    s.source(root)
    observe.tools(root, workspace)
    head = s.output(["git", "-C", HERE, "rev-parse", "HEAD"]).decode().strip()
    need(head == os.environ["GITHUB_SHA"], "unexpected QA head")
    intake = json.loads((kits / "admission.json").read_text())
    need(
        intake["run"] == ENROLL["native_run"] and intake["head"] == ENROLL["native_qa"], "wrong native input"
    )
    write(
        root / "receipts/registration.json",
        {
            "run": int(os.environ["GITHUB_RUN_ID"]),
            "attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
            "head": head,
            "role": role,
            "subject": ENROLL,
            "sdk_admission": intake,
            "argv": E2E if kind == "e2e" else CHECK,
        },
    )
    s.copy_sdk(root, kits, "parent", "registry-sdk")
    s.seed_registry(root)
    records = {}
    installs = {}
    issues = []
    for stream in ["pmu", "trace"]:
        s.fresh(root, registry=True)
        a = installs[stream + "-old"] = stage(root, kits, "installs/" + stream + "-old", old, kind)

        def v(phase, mode, issuer):
            data = visit(root, role, stream, phase, mode, issuer["stamp"])
            records[stream + "/" + phase] = data
            issues.extend(stream + "/" + phase + ": " + i for i in data["issues"])
            write(root / "receipts/partial.json", {"role": role, "visited": list(records), "issues": issues})

        v("cold", "original", a)
        v("prior-repeat", "original", a)
        if stream == "trace" and kind == "migration":
            chunks.capture(root, "pre-install")
        b = a
        if kind == "migration":
            before = root / "receipts" / ("installs/" + stream + "-before")
            before.mkdir(parents=True)
            pre = s.storage(root, before)
            b = installs[stream + "-new"] = stage(
                root, kits, "installs/" + stream + "-new", new, kind, old == new
            )
            after = root / "receipts" / ("installs/" + stream + "-after")
            after.mkdir(parents=True)
            post = s.storage(root, after)
            need(
                pre["ledger_sha256"] == post["ledger_sha256"],
                "install or private identity probe touched populated target/shared state",
            )
            need(
                (a["rustc_vv"] == b["rustc_vv"]) == (old != "signed") and a["cargo_vv"] == b["cargo_vv"],
                "unexpected natural SDK identity",
            )
            # No intermediate Cargo/rustc operation under either build root between install and this first normal visit.
            v("upgrade-first", "original", b)
            if stream == "trace":
                chunks.capture(root, "post-first")
            v("upgrade-second", "original", b)
        v("edited", "reversed", b)
        v("edit-repeat", "reversed", b)
        if kind == "migration":
            v("invalid", "invalid", b)
            v("repaired", "reversed", b)
            if stream == "trace":
                chunks.capture(root, "post-repair")
        v("restored", "original", b)
        v("restore-repeat", "original", b)
    for name, mode in [("original", "original"), ("reversed", "reversed")] + (
        [("invalid", "invalid"), ("repaired", "reversed")] if kind == "migration" else []
    ):
        s.fresh(root, registry=True)
        v0 = visit(root, role, "clean", name, mode, b["stamp"])
        records["clean/" + name] = v0
        issues.extend("clean/" + name + ": " + i for i in v0["issues"])
    if kind == "e2e":
        compare_e2e(root, records, issues)
    else:
        compare_migration(records, issues)
    for stream in ("pmu", "trace"):
        for prev, current in [
            ("cold", "prior-repeat"),
            ("edited", "edit-repeat"),
            ("restored", "restore-repeat"),
        ] + (
            [("prior-repeat", "upgrade-first"), ("upgrade-first", "upgrade-second")]
            if kind == "migration"
            else []
        ):
            need(
                records[stream + "/" + prev]["source"] == records[stream + "/" + current]["source"],
                "registered unchanged Ruff source was touched",
            )
    summary = {
        "role": role,
        "kind": kind,
        "installs": installs,
        "issues": issues,
        "success": not issues,
        "visits": {
            k: {
                "status": v["status"],
                "instructions": v["pmu"]["instructions"] if v["pmu"] else None,
                "allocated": v["allocated"]["bytes"],
                "stale_rmeta": len(v["stale_metadata"]),
                "full": sum(x[2] == "full" for x in v["physical"]["compilers"]) if v["physical"] else None,
                "link_only": (
                    sum(x[2] == "link-only" for x in v["physical"]["compilers"]) if v["physical"] else None
                ),
                "wild": len(v["physical"]["wild"]) if v["physical"] else None,
                "returned_e2e_wild": (
                    sum(x["same_returned_e2e"] for x in v["physical"]["wild"]) if v["physical"] else None
                ),
            }
            for k, v in records.items()
        },
    }
    if kind == "migration":
        phases = summary["visits"]
        summary["upgrade_cost"] = {
            n: {
                "instructions": phases["pmu/" + n]["instructions"],
                "target_shared_bytes": phases["pmu/" + n]["allocated"],
                "allocated_change_from_preinstall": phases["pmu/" + n]["allocated"]
                - phases["pmu/prior-repeat"]["allocated"],
                "full_compiles": phases["trace/" + n]["full"],
                "link_only_compiles": phases["trace/" + n]["link_only"],
                "wild_links": phases["trace/" + n]["wild"],
                "exit": phases["pmu/" + n]["status"],
            }
            for n in (
                "prior-repeat",
                "upgrade-first",
                "upgrade-second",
                "edited",
                "repaired",
                "restore-repeat",
            )
        }
    if kind == "migration":
        summary["semantic_content_survey"] = chunks.summarize(root / "receipts/semantic-chunks")
    write(root / "receipts/summary.json", summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    return not issues


def compare_e2e(root, records, issues):
    orig = records["clean/original"]["test"]
    rev = records["clean/reversed"]["test"]
    if not (orig and rev):
        issues.append("empty e2e oracle missing")
        return
    if (
        set(orig["names"]) - set(rev["names"]) != set(orig["new_cases"])
        or len(orig["new_cases"]) != 1
        or set(rev["names"]) - set(orig["names"])
    ):
        issues.append("independent edit does not remove exactly the actually enrolled notebook case")
    if orig["elf"]["sha256"] == rev["elf"]["sha256"]:
        issues.append("independent edit did not change the ELF")
    bad = set()
    for n, row in records.items():
        want = orig if row["state"] == "original" else rev
        got = row["test"]
        if not got:
            continue
        if (got["names"], got["list_sha"], got["runtime"]) != (
            want["names"],
            want["list_sha"],
            want["runtime"],
        ):
            issues.append(n + ": actual program/list differs from its independent empty build")
        if got["elf"]["sha256"] != want["elf"]["sha256"]:
            issues.append(n + ": complete e2e ELF differs from its own clean build")
            bad.update((got["elf"]["sha256"], want["elf"]["sha256"]))
    if bad:
        dest = root / "receipts/elf-divergences"
        dest.mkdir()
        for h in sorted(bad):
            subprocess.run(
                ["zstd", "-q", "-T3", "-3", "-o", dest / (h + ".zst"), root / "image-vault" / h], check=True
            )


def compare_migration(records, issues):
    for n, row in records.items():
        if n.startswith("clean/") or n.endswith(("/cold", "/prior-repeat")):
            continue
        reference = records["clean/" + ("repaired" if n.endswith("/repaired") else row["state"])]
        if row["status"] != reference["status"] or row["terminal"] != reference["terminal"]:
            issues.append(n + ": verdict differs from empty")
        if row["state"] == "invalid":
            if {json.dumps(v, sort_keys=True) for v in row["diagnostics"]} != {
                json.dumps(v, sort_keys=True) for v in reference["diagnostics"]
            }:
                issues.append(n + ": failing diagnostics differ from independently empty input")
            continue
        if row["generated"] != reference["generated"] or row["logical_units"] != reference["logical_units"]:
            issues.append(n + ": returned source bytes/unit inventory differ from empty")
        if row["workspace_metadata"] != reference["workspace_metadata"]:
            issues.append(n + ": workspace metadata bytes differ from empty")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("workspace", type=Path)
    p.add_argument("kits", type=Path)
    p.add_argument("role", choices=ROLES)
    a = p.parse_args()
    sys.exit(0 if run(a.root.resolve(), a.workspace.resolve(), a.kits.resolve(), a.role) else 1)
