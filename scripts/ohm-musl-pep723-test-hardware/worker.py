"""One independent, externally admitted PC or CP hardware worker for Ruff's changed test."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support as q


def file_id(path):
    p = Path(path)
    s = p.stat()
    return {
        "path": str(p),
        "device": s.st_dev,
        "inode": s.st_ino,
        "bytes": s.st_size,
        "sha256": q.file_sha(p),
    }


def strong_native(s, ev, dest, role, phase, oracle):
    """Require the opened driver and terminal musl ld in the unclocked edit and first-repeat mirrors."""
    dest.mkdir()
    tr = dest / "proc"
    tr.mkdir()
    args = [
        "strace",
        "-ff",
        "-q",
        "-ttt",
        "-yy",
        "-s",
        "131072",
        "-e",
        "trace=clone,clone3,fork,vfork,execve,execveat,openat,openat2",
        "-o",
        tr / "pid",
        *q.REG["ordinary_argv"],
    ]
    v = subprocess.run(args, cwd=s.source, env=s.env, capture_output=True, timeout=1200)
    (dest / "stdout.raw").write_bytes(v.stdout)
    (dest / "stderr.raw").write_bytes(v.stderr)
    per_pid = sorted(tr.glob("pid.*"))
    # Archive first. A failed parser/identity check still leaves every genuine syscall available.
    with tarfile.open(dest / "processes.tar.gz", "x:gz", compresslevel=2) as ar:
        for p in per_pid:
            ar.add(p, arcname=p.name, recursive=False)
    q.require(v.returncode == 0, "native mirror failed")
    sig, exe = q.typed(v.stdout)
    q.require(sig == oracle, "native and measured typed graph differ")
    identities = {}
    for path in per_pid:
        raw = path.read_text()
        for line in raw.splitlines():
            if " ???(" in line:
                q.require(
                    line.endswith(" ???( <unfinished ...>"),
                    "unidentified syscall/detach in strong native mirror",
                )
    # This fixed source also requires any terminal unnamed row to belong to a real inherited
    # CLONE_THREAD group in the enrolled compiler and to exit cleanly in these successful visits.
    rec = ev.observe(tr, s.source, s.sdk, [s.work / "target", s.work / "shared"], set())
    q.write(dest / "kernel.json", rec)
    q.require(
        rec["status"] == 0 and not rec["scripts"] and not rec["failed_app_thread_exits"],
        "unexpected build script or failed worker",
    )
    rows = rec["compilers"]
    full = sorted(r["crate"] for r in rows if r["kind"] == "full")
    cached = sorted(r["crate"] for r in rows if r["kind"] == "link-only")
    expected = (
        (["compact_str", "ruff_python_ast", "zmij"], [])
        if role == "P"
        else ((["ruff_python_ast"], []) if phase == "edit" else ([], ["ruff_python_ast"]))
    )
    q.require(
        (full, cached) == expected
        and all(
            "--target" in r["argv"]
            and r["argv"][r["argv"].index("--target") + 1] == "x86_64-unknown-linux-musl"
            for r in rows
        ),
        "unexpected real compiler work",
    )
    q.require(
        all(
            any(
                pid == r["pid"] and Path(path).samefile(s.driver) for pid, path, _ in rec["driver_open"]
            )
            for r in rows
        ),
        "driver not opened by physical emitting compiler",
    )
    [ld] = rec["linkers"]
    q.require(
        Path(ld["image"]).samefile("/usr/bin/ld")
        and ld["exit"] == 0
        and Path(ld["output"]).name == exe.name,
        "real musl test linker",
    )
    all_ld = [
        r for r in rec["all_exec"] if ev.LD.fullmatch(Path(r["image"]).name) and "-o" in r["argv"]
    ]
    q.require(len(all_ld) == 1 and all_ld[0]["pid"] == ld["pid"], "unexpected second native linker")
    for rec0 in rec["all_exec"]:
        p = Path(rec0["image"])
        if p.name in ("cc", "collect2", "ld") and p.is_file():
            identities[p.name] = file_id(p)
    q.require(
        set(identities) == {"cc", "collect2", "ld"} and identities["ld"]["sha256"] == q.MUSL_LD_SHA256,
        "same actual musl native chain",
    )
    return {
        "full": full,
        "cached": cached,
        "target_ld": 1,
        "target_ld_pid": ld["pid"],
        "tools": identities,
        "physical_subject": {
            n: file_id(p)
            for n, p in [
                ("driver", s.driver),
                ("rustc", s.sdk / "bin/rustc"),
                ("cargo", s.sdk / "bin/cargo"),
            ]
        },
        "unknown_terminal_compiler_threads": rec["opaque_rustc_thread_exits"],
        "kernel_sha256": q.file_sha(dest / "kernel.json"),
        "process_tar": q.file_sha(dest / "processes.tar.gz"),
        "elf": q.file_sha(exe),
        "typed": sig,
    }


def admit_native_result(n, fixture):
    original = n["old"]["program"]
    edited = n["edit"]["program"]
    wrong = n["wrong"]["program"]
    q.require(
        len({original["sha256"], edited["sha256"], wrong["sha256"]}) == 3,
        "unchanged wrong/original/edited binary",
    )
    for nm in ["repair", "unchanged", "settled", "empty-new"]:
        q.require(
            n[nm]["program"]["sha256"] == edited["sha256"], "ordinary edited ELF vs independently clean"
        )
    q.require(
        n["empty-old"]["program"]["sha256"] == original["sha256"]
        and n["empty-wrong"]["program"]["sha256"] == wrong["sha256"],
        "old and wrong empty controls",
    )
    q.require(
        n["invalid"]["diagnostic"] == n["empty-invalid"]["diagnostic"]
        and n["invalid"]["exit"] == n["empty-invalid"]["exit"] == 101,
        "warm/empty invalid source",
    )
    for k, rec in [("old", original), ("edit", edited), ("wrong", wrong)]:
        q.require(
            rec["inventory"]["stdout"] == q.REG["source_ordinary_tests"][k], ("historical inventory", k)
        )
        q.require(rec["all"]["exit"] == (101 if k == "wrong" else 0), "native full suite")
    q.require(wrong["individual"][fixture.PLAN["wrong_test"]]["failed"] == 1, "wrong exact assertion")
    return {k: n[k]["program"]["sha256"] for k in ("old", "edit", "wrong")} | {
        "E0308": n["invalid"]["diagnostic"]
    }


def registry(path):
    return {p.name: q.file_sha(p) for p in (path / "registry/cache").glob("*/*.crate")}


def collect(a):
    permit = q.gate(a.clearance)
    q.require(
        not os.environ.get("GH_TOKEN") and not os.environ.get("GITHUB_TOKEN"),
        "measurement process carries GitHub credentials",
    )
    q.require(
        os.environ["GITHUB_REPOSITORY"] == "astral-experiments/ohm"
        and os.environ["GITHUB_REF_NAME"] == q.REG["ref"]
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
        and a.position in [1, 2],
        "unregistered workflow",
    )
    root = a.root.resolve()
    q.require(
        not root.exists() and shutil.disk_usage(root.parent).free >= q.REG["entry"]["space_bytes"],
        "fresh 12-GiB entry",
    )
    root.mkdir(mode=0o700)
    out = root / "counts"
    out.mkdir()
    case, meter, measure, products, ev = q.modules(a.structural, a.hardware, a.qual)
    order = q.REG["screen"]["position_" + str(a.position)]
    prior = q.archive_oracle(a.original)
    host = measure.host()
    q.require(
        host["boot_id"] not in q.REG["screen"]["excluded_boot_ids"]
        and host["boot_id"] not in permit.get("other_used_boots", []),
        "reused boot",
    )
    q.write(out / "host.json", host)
    shutil.copyfile(a.clearance, out / "clearance.json")
    q.require(q.file_sha(out / "clearance.json") == q.AUTHORIZED_CLEARANCE_SHA256, "clearance custody")
    products.storage_calibration(out, root)
    # This is the original, unmodified 28-control path. Its child does not run any Ruff commands.
    subprocess.run(
        [
            sys.executable,
            "-IB",
            a.hardware / "scripts/ohm-musl-ast-hardware/measure.py",
            "calibrate",
            out,
        ],
        check=True,
    )
    o = SimpleNamespace(
        work=root / "work",
        out=root / "flanks",
        qa=a.qual,
        receipts=a.receipts,
        ruff=None,
        archive_cache=None,
    )

    class Study(case.Study):
        def visit(self, role, name, state, empty):
            super().visit(role, name, state, empty)
            if name == "empty-new":
                self.empty_ledger = products.ledger(self.work, self.out / role / name)

    s = Study(o)
    seed = s.cargo_home.rename(s.work / "fresh-registry-seed")
    registry_expected = registry(seed)
    q.require(registry_expected == s.registry, "authenticated fresh seed")
    for p in seed.rglob("*"):
        if p.is_symlink():
            q.require(
                p.resolve(strict=True).is_relative_to(seed), "registry alias escaped immutable seed"
            )
    results = {}
    storage = {}
    role_native = {}
    for role in order:
        q.require(
            not s.cargo_home.exists() and not any((s.work / k).exists() for k in ["target", "shared"]),
            "cross-arm target or registry",
        )
        shutil.copytree(seed, s.cargo_home, symlinks=True)
        q.require(registry(s.cargo_home) == registry_expected, "different incoming registry")
        s.select("old")
        s.activate(role)
        s.result["roles"][role] = {}
        arm = out / role
        arm.mkdir()
        s.visit(role, "clock-training-old", "old", True)
        old = s.result["roles"][role]["clock-training-old"]["program"]
        s.select("new")
        s.space()
        values = meter.consecutive(out / "tools/watch", arm, s.env, s.source)
        typed = {phase: q.typed(values[phase]["stdout"]) for phase in ["edit", "repeat"]}
        for phase, (row, _) in typed.items():
            q.require(row == prior[role][phase], ("scored typed graph", role, phase))
        q.require(typed["edit"][1] == typed["repeat"][1], "test path changed between adjacent clocks")
        final = arm / "measured-final"
        final.mkdir()
        last = s.test_program(typed["repeat"][1], "new", final)
        warm_storage = products.ledger(s.work, final)
        s.park("measured")
        # Reuse the already proven 11-visit history in a completely empty second target.
        s.run_role(role)
        n = s.result["roles"][role]
        body = admit_native_result(n, case)
        q.require(
            old["sha256"] == body["old"] and last["sha256"] == body["edit"],
            "clocked final and training vs clean native",
        )
        q.require(
            all(all(d.values()) for d in s.result["within_role"][role].values()),
            "within-role native gate",
        )
        storage[role] = {"storage": {"warm": warm_storage, "empty": s.empty_ledger}}
        # That parked view was the independently empty old build. Rename both same-filesystem
        # roots together while no children are live. No file/inode is copied or synthesized.
        s.select("old")
        donor = s.closed / (role + "-before-empty-wrong")
        for key in ("target", "shared"):
            q.require(
                not (s.work / key).exists()
                and (donor / key).is_dir()
                and not (donor / key).is_symlink(),
                "wrong frozen empty-old state",
            )
            (donor / key).rename(s.work / key)
        s.select("new")
        mirrors = {}
        for phase in ("edit", "repeat"):
            mirrors[phase] = strong_native(
                s, ev, arm / ("kernel-" + phase), role, phase, prior[role][phase]
            )
            q.require(
                mirrors[phase]["elf"] == body["edit"],
                "strong native mirror vs complete own-mode empty body",
            )
        s.park("strong-mirror")
        q.require(registry(s.cargo_home) == registry_expected, "mutable source archives")
        s.cargo_home.rename(s.closed / (role + "-cargo-home"))
        role_native[role] = body
        terminal = {
            "role": role,
            "body": body,
            "measured_final": last["sha256"],
            "native": mirrors,
            "typed": {p: row for p, (row, _) in typed.items()},
            "unknown_in_legacy_flanks": "Full original -qq records are retained. Strong edit/repeat mirrors require physical clone, exec, driver and ld evidence.",
            "structural_partial": q.file_sha(s.out / "partial.json"),
            "storage": storage[role]["storage"],
        }
        q.write(arm / "terminal.json", terminal)
        results[role] = q.file_sha(arm / "terminal.json")
    s.activate("P")
    q.require(role_native["P"] == role_native["C"], "cross-arm whole ELF or E0308 differs")
    q.require(
        s.result["role_identity"]["P"]["182_common_inode_map_sha"]
        == s.result["role_identity"]["C"]["182_common_inode_map_sha"],
        "common physical inputs",
    )
    storage_summary = measure.storage_gate(storage)
    q.write(
        out / "pair.json",
        {
            "position": a.position,
            "order": order,
            "registration": q.REG_SHA,
            "boot_id": host["boot_id"],
            "workflow": os.environ["GITHUB_RUN_ID"],
            "head": os.environ["GITHUB_SHA"],
            "argv": q.REG["ordinary_argv"],
            "clearance": q.file_sha(a.clearance),
            "native_terminal": results,
            "storage": storage_summary,
            "scope": "test-only screen",
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for n in ["structural", "hardware", "qual", "receipts", "original", "clearance", "root"]:
        p.add_argument("--" + n, type=Path, required=True)
    p.add_argument("--position", type=int, choices=(1, 2), required=True)
    collect(p.parse_args())
