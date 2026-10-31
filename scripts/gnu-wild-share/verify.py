"""Detached replay of nested FDs, whole controls, Cargo ownership, native behavior, and the ceiling."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import re

HERE = Path(__file__).resolve().parent
sys.path[:0] = [
    str(HERE),
    str(HERE.parent / "ruff-integration-structure"),
    str(HERE.parent / "branch-return-pmu"),
]
import calibration, selection, suite
from kernel import (
    COMMAND,
    SELECTORS,
    arguments,
    classify,
    digest,
    load,
    require,
    snapshot,
)


def pair_results(pairs):
    result = []
    for j, v in enumerate(pairs, 1):
        tree, plain = v["tree"], v["plain"]["whole"]
        whole = tree["whole"]
        outputs = tree["outputs"]
        require(
            set(outputs) == {"ruff", "integration_test"}
            and min(*outputs.values(), plain, whole) > 0
            and sum(outputs.values()) < whole,
            "invalid positive totals",
        )
        difference = abs(whole - plain)
        require(
            100 * difference <= 3 * min(whole, plain),
            ("three-percent matched whole counter gate", j, whole, plain),
        )
        total = sum(outputs.values())
        # Plain is a separate ordinary execution. Comparing against it is a sensitivity check.
        den = [min(whole, plain), max(whole, plain)]
        require(total < den[0], "nonpositive sensitivity remainder")
        result.append(
            {
                "pair": j,
                "whole_traced": whole,
                "whole_plain": plain,
                "wild_by_output": outputs,
                "wild_combined": total,
                "other_traced": whole - total,
                "observed_share": {k: n / whole for k, n in outputs.items()},
                "combined_observed_share": total / whole,
                "combined_share_using_other_denominator": total / plain,
                "traced_zero_cost_ceiling": whole / (whole - total),
                "sensitivity_zero_cost_range": [d / (d - total) for d in reversed(den)],
                "above_half_on_both_denominators": 2 * total > den[1],
                "below_half_on_both_denominators": 2 * total < den[0],
            }
        )
    require(len(result) == 4, "need all four prespecified pairs")
    decision = (
        "ideal elimination of these two complete Wild subtrees is below 2x on all four observations"
        if all(x["below_half_on_both_denominators"] for x in result)
        else "these two complete Wild subtrees exceed half of both measured wholes in every pair"
        if all(x["above_half_on_both_denominators"] for x in result)
        else "the 2x ceiling is unresolved on this host"
    )
    return {"pairs": result, "within_host_descriptive_decision": decision}


def get(d, n):
    return gzip.decompress((d / n).read_bytes())


def artifact_map(d, src, cold, roster_digest):
    rows = [json.loads(x) for x in get(d, "stdout.gz").splitlines()]
    require(rows[-1] == {"reason": "build-finished", "success": True}, "Cargo status")
    roster, dirty = selection.roster(rows, src)
    body = json.dumps(roster, sort_keys=True, separators=(",", ":")).encode()
    require(
        len(roster) == 390 and hashlib.sha256(body).hexdigest() == roster_digest,
        "original typed graph",
    )
    require(
        len(dirty) == 390
        if cold
        else sorted(x["name"] for x in dirty) == ["integration_test", "ruff"],
        "unexpected fresh/dirty graph",
    )
    found = {}
    for r in rows:
        if r.get("reason") != "compiler-artifact" or not r["executable"]:
            continue
        t = r["target"]
        name = t["name"]
        specs = {
            "ruff": ("bin", "src/main.rs"),
            "integration_test": ("test", "tests/integration_test.rs"),
        }
        require(
            name in specs
            and name not in found
            and t["kind"] == [specs[name][0]]
            and Path(t["src_path"]) == src / "crates/ruff" / specs[name][1],
            "wrong Cargo artifact owner",
        )
        found[name] = r["executable"]
    require(set(found) == {"ruff", "integration_test"}, "missing native product")
    return found


def read_body(path):
    """Reopen every byte and query DT_NEEDED from this same held native ELF."""
    hasher = hashlib.sha256()
    size = 0
    with tempfile.TemporaryFile() as held:
        with subprocess.Popen(
            ["zstd", "-q", "-dc", path], stdout=subprocess.PIPE
        ) as proc:
            while chunk := proc.stdout.read(1 << 20):
                size += len(chunk)
                require(size < 512 << 20, "oversized native body")
                hasher.update(chunk)
                held.write(chunk)
            require(proc.wait() == 0, "bad native zstd frame")
        require(size > 1 << 20, "short native body")
        held.flush()
        fd = held.fileno()
        dynamic = subprocess.check_output(
            ["readelf", "-dW", f"/proc/self/fd/{fd}"], pass_fds=[fd], text=True
        )
        names = re.findall(r"\(NEEDED\)[^\n]*?\[([^\]]+)\]", dynamic)
        require(names, "missing native dependency table")
        return {"size": size, "sha256": hasher.hexdigest()}, names


def native_controls(d, src, expected, images):
    # For the native filenames use the path as Cargo actually exposed it. Any hardlinked internal alias
    # has its own physical -o/checksum record in the kernel arm.
    verdict = load(d / "libtest.json")
    names = suite.inventory(get(d, "libtest-list.stdout.gz"))
    suite.verdict(get(d, "libtest-full.stdout.gz"), names)
    require(
        (verdict["total"], verdict["passed"], verdict["inventory"])
        == (96, 96, suite.LIST_SHA),
        "wrong suite",
    )
    require(
        load(d / "images.json") == images and len(images) == 2,
        "wrong live complete native outputs",
    )
    for fn in ("libtest-list", "libtest-full"):
        j = load(d / (fn + ".json"))
        require(
            j["exit"] == 0
            and j["argv"][0] == expected["integration_test"]
            and j["cargo_bin"] == expected["ruff"]
            and j["cwd"] == str(src / "crates/ruff")
            and j["insta_root"] == str(src),
            "wrong binary or src",
        )
        for s in ("stdout", "stderr"):
            require(
                hashlib.sha256(get(d, f"{fn}.{s}.gz")).hexdigest() == j[s],
                "raw oracle output",
            )
    # Replay both forked native CLI cases. This parser needs no original absolute filesystem.
    import processes

    for name in suite.EXACT:
        suite.verdict(get(d, name + ".stdout.gz"), [name], 95)
        trace = processes.execs(get(d, name + ".exec.gz").decode().splitlines())
        require(len(trace) == 2, "unexpected child")
        (hpid, h, ha), (cpid, c, ca) = trace
        require(
            hpid != cpid
            and h == expected["integration_test"]
            and c == expected["ruff"]
            and ha[1:] == ["--exact", name, "--test-threads=1", "--color", "never"]
            and ca[1] == "check"
            and "--isolated" in ca
            and "--no-cache" in ca
            and (
                "@!.txt" in ca
                if name == suite.EXACT[1]
                else any(
                    v.startswith("@/") and v.endswith("/file_paths.txt") for v in ca
                )
            ),
            "wrong CLI case",
        )
    require(
        b"ruf950" in get(d, "dev-rule.stdout.gz").lower(), "missing development feature"
    )


def verdict(out, donor):
    os.environ.setdefault(
        "RUNNER_TEMP", "/tmp"
    )  # The inherited exec parser imports a default scratch path.
    from study import ABSENT, B, CARGO, NATIVE, ORDERS, RUST, TREE

    require(
        not (out / "refused.txt").exists()
        and load(out / "run.json")["plan"] == digest(HERE / "PLAN.md"),
        "refused/changed plan",
    )
    calibration.controls(donor, out, replay=True)
    q = load(out / "inputs.json")
    ids = q["ids"]
    src = Path(q["source"])
    require(
        q["rust"] == RUST
        and q["cargo"] == CARGO
        and q["ruff"] == B
        and q["tree"] == TREE
        and len(q["archives"]) == 505
        and q["driver"]["sha256"] == NATIVE["driver"]
        and all(ids[k]["sha256"] == NATIVE[k] for k in ("cargo", "rustc", "wild")),
        "foreign compiler/native inputs",
    )
    receipt = q["sdk_source"]
    require(
        receipt["source_head"] == "7bc72b798b019a9ec0de6eeea3bc22b783917b27"
        and receipt["run"] == 41212542603
        and receipt["artifact"]["sha256"]
        == "32a14901e46302ebeebdc3badc5be40284dbfc5c36f8ee176071b3ddd623d6c1",
        "foreign official source capsule",
    )
    expected_hash = load(HERE / "structural.json")["roster_sha256"]
    clean, system = {}, {}
    for role in ("cli", "harness"):
        clean[role], system[role] = read_body(out / (role + "-clean.zst"))
        require(system[role].count("libgcc_s.so.1") == 1, "missing original runtime")
    for n in ("reference-empty", "study-empty"):
        d = out / n
        paths = artifact_map(d, src, True, expected_hash)
        require(
            load(d / "call.json") == {"argv": COMMAND, "code": 0, "cwd": str(src)},
            "different empty Cargo",
        )
        native_controls(d / "native", src, paths, clean)
    groups = []
    link_out = None
    previous_end = 0
    for i, order in enumerate(ORDERS, 1):
        group = {}
        for mode in order:
            d = out / f"pair-{i}-{mode}"
            paths = artifact_map(d, src, False, expected_hash)
            c = load(d / "call.json")
            require(
                previous_end < c["begin_ns"] < c["end_ns"],
                "overlapping or reordered registered visits",
            )
            previous_end = c["end_ns"]
            argv = c["argv"]
            require(
                c["code"] == 0
                and c["cwd"] == str(src)
                and argv[2:] == [mode, *[ids[n]["path"] for n in SELECTORS], *COMMAND]
                and Path(argv[0]).name == "observe"
                and Path(argv[1]).parts[-2:] == (d.name, "trace"),
                "unregistered measured command",
            )
            expected = load(d / "expected.json")
            raw = snapshot(d / "trace", mode, ids)
            if mode == "tree":
                owners = load(d / "owners.json")
                for name, v in owners.items():
                    key = "cli" if name == "ruff" else "harness"
                    require(
                        v["link_output"]["path"] == expected[name]
                        and v["cargo_output"]["path"] == paths[name]
                        and v["link_output"]["sha256"]
                        == v["cargo_output"]["sha256"]
                        == clean[key]["sha256"],
                        "wrong -o to checked ELF",
                    )
                require(
                    set(owners) == set(expected) == set(paths),
                    "missing independent output",
                )
                require(
                    link_out is None or link_out == expected, "physical output changed"
                )
                link_out = expected
            else:
                require(expected == {}, "sham contains unobserved linker identities")
            native_controls(d / "native", src, paths, clean)
            group[mode] = classify(raw, expected, "ruff")
        groups.append(group)
    d = out / "native-challenge"
    passed = load(d / "result.json")
    prior = None
    for label in ("appeared", "same-stat", "malformed", "repaired", "removed"):
        sub = d / label
        status = 101 if label == "malformed" else 0
        rec = load(sub / "call.json")
        require(
            rec["code"] == status and rec["argv"][-len(COMMAND) :] == COMMAND,
            "wrong native-control command",
        )
        import processes

        raw = processes.execs(get(sub, "exec.gz").decode().splitlines())
        # GNU gcc emits an absolute signed Wild path in this kit.
        wild = Path(ids["wild"]["path"])
        spellings = {
            str(wild),
            str(
                Path(q["environment"]["RUSTUP_HOME"])
                / "toolchains/ohm"
                / wild.relative_to(Path(ids["rustc"]["path"]).parent.parent)
            ),
        }
        rawlinks = [
            (p, e, a)
            for p, e, a in raw
            if Path(e).name
            in {"ld", "ld.bfd", "ld.gold", "rust-lld", "ld.lld", "mold", "wild"}
            and "-o" in a
        ]
        require(
            all(e in spellings for _, e, _ in rawlinks),
            "nonstock linker in source check",
        )
        require(
            [[p, e, a] for p, e, a in rawlinks] == load(sub / "links.json")
            and len(rawlinks) == 2
            and {arguments(a, "-o") for _, _, a in rawlinks} == set(link_out.values()),
            "native challenge selection",
        )
        if status:
            data = get(sub, "stdout.gz").decode() + get(sub, "stderr.gz").decode()
            require(
                ABSENT in data and passed[label]["code"] == 101,
                "missing true provider failure",
            )
        else:
            paths = artifact_map(sub, src, False, expected_hash)
            native_controls(sub / "native", src, paths, passed[label]["images"])
            if label in ("appeared", "same-stat"):
                for role in ("cli", "harness"):
                    image, dynamic = read_body(sub / (role + ".zst"))
                    wanted = [
                        passed[label]["expected"] if n == "libgcc_s.so.1" else n
                        for n in system[role]
                    ]
                    require(
                        image == passed[label]["images"][role]
                        and dynamic == wanted == passed[label]["needed"][role],
                        "complete changed native body or dynamic dependency",
                    )
            if label != "removed":
                require(
                    all(
                        names.count(passed[label]["expected"]) == 1
                        and "libgcc_s.so.1" not in names
                        for names in passed[label]["needed"].values()
                    ),
                    "stale DT_NEEDED",
                )
        if label != "removed":
            coord = passed[label]["tuple"]
            require(prior is None or coord == prior, "provider stat changed")
            prior = coord
    require(
        len({passed[n]["provider"] for n in ("appeared", "same-stat", "malformed")})
        == 3
        and passed["repaired"]["provider"] == passed["same-stat"]["provider"]
        and passed["repaired"]["images"] == passed["same-stat"]["images"]
        and passed["removed"]["images"] == clean,
        "raw provider control results",
    )
    return {
        "source": RUST,
        "cargo": CARGO,
        "boot": load(out / "run.json")["boot"],
        "clean": clean,
        "ordinary": pair_results(groups),
        "provider": {k: v.get("code", 0) for k, v in passed.items()},
        "enrolled_normal_cache": "none",
        "host_scope": "one x86-64 GNU host",
    }


if __name__ == "__main__":
    out, donor = (Path(n).resolve() for n in sys.argv[1:])
    v = verdict(out, donor)
    require(v == load(out / "qualified.json"), "changed terminal recalculation")
    print(json.dumps(v, sort_keys=True, indent=2))
