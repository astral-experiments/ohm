"""Attribute the actual GNU renderer library edit on two independently calibrated hosts."""

import argparse
import gzip
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import signal
import subprocess
import sys
import traceback
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
COMMON = HERE.parent / "gnu-example-ceiling"
sys.path[:0] = [str(HERE), str(COMMON)]
import artifacts
import kit
import pmu
import readback
import workload as w

CLI = [
    "cargo",
    "+ohm",
    "build",
    "-p",
    "ruff_annotate_snippets",
    "--lib",
    "--locked",
    "--offline",
    "-j4",
    "--message-format=json",
]
ORDERS = {"01": ["tree", "plain"], "02": ["plain", "tree"]}
UNITS = {"anstyle", "annotate_snippets", "memchr", "unicode_width"}


def run(folder, cmd, cwd, env=None, timeout=900):
    """Keep the command, exit and both raw streams, including rejected visits."""
    folder.mkdir(parents=True)
    args = list(map(str, cmd))
    kit.save(folder / "started.json", {"argv": args, "cwd": str(cwd)})
    with (folder / "stdout.partial").open("xb") as stdout, (folder / "stderr.partial").open(
        "xb"
    ) as stderr:
        p = subprocess.Popen(
            args, cwd=cwd, env=env, stdout=stdout, stderr=stderr, start_new_session=True
        )
        try:
            p.wait(timeout=timeout)
        except BaseException:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait()
            raise
    streams = []
    for name in ("stdout", "stderr"):
        original = folder / (name + ".partial")
        data = original.read_bytes()
        pmu.gz(folder / (name + ".gz"), data)
        original.unlink()
        streams.append(data)
    kit.save(folder / "invocation.json", {"argv": args, "status": p.returncode})
    return subprocess.CompletedProcess(args, p.returncode, *streams)


def calibration(root, out, bins):
    """Re-use the 36 process calibrations while retaining even a failed command's streams."""
    raw = out / "calibration-commands"
    raw.mkdir()

    def retained(cmd, cwd, env, timeout=900):
        return run(raw / str(len(list(raw.iterdir()))), cmd, cwd, env, timeout)

    with patch.object(pmu, "spawn", retained):
        pmu.calibration(bins, out)
    assert len(list(raw.iterdir())) == 36
    scripted = out / "worker-calibration"
    scripted.mkdir()
    for i, count in enumerate((0, 4_000_000, 0, 12_000_000)):
        trace = scripted / str(i)
        trace.mkdir()
        args = [
            bins / "workers",
            trace,
            "hardware",
            bins / "calibrator",
            "calibration",
            bins / "calibrator",
            "--crate-name",
            "calibration",
            "--out-dir",
            root,
            count,
            "fixture",
        ]
        r = run(scripted / ("invocation-" + str(i)), args, root)
        assert r.returncode == 0 and not r.stdout and not r.stderr, (i, r.returncode, r.stderr[-400:])
    kit.save(out / "worker-calibration.json", readback.worker_calibration(scripted))


def registry(home, seed, locked):
    """Give Cargo a private index and archives. Its cold visit extracts its own sources."""
    assert not home.exists() and not (seed / "git").exists()
    home.mkdir()
    dest = home / "registry"
    dest.mkdir()
    for name in ("cache", "index"):
        shutil.copytree(seed / "registry" / name, dest / name)
    assert not (dest / "src").exists()
    got = {}
    for f in dest.glob("cache/*/*.crate"):
        assert not f.is_symlink() and not f.samefile(seed / "registry" / f.relative_to(dest))
        assert f.name not in got
        got[f.name] = kit.sha(f)
    assert got == locked and len(got) == 498
    return {"archive_count": len(got), "root": kit.stable(dest)[:2], "logical": str(dest)}


def verify_artifact_inventory(data, phase):
    rows = [json.loads(line) for line in data.splitlines()]
    assert rows[-1] == {"reason": "build-finished", "success": True}
    assert not [m for m in rows if m.get("message", {}).get("level") == "error"]
    units = [m for m in rows if m["reason"] == "compiler-artifact"]
    assert len(units) == len(UNITS) and {m["target"]["name"] for m in units} == UNITS
    assert all(m["target"]["kind"] == ["lib"] and m["executable"] is None for m in units)
    dirty = {m["target"]["name"] for m in units if not m["fresh"]}
    assert (
        dirty == {"old": UNITS, "edit": {"annotate_snippets"}, "repeat": set(), "empty": UNITS}[phase]
    ), (phase, dirty)


def keep(pool, path):
    digest = kit.sha(path)
    dest = pool / digest
    if not dest.exists():
        shutil.copyfile(path, dest)
    assert kit.sha(dest) == digest
    return digest


def behavior(dest, src, env, label, state, pool):
    folder = dest / (label + "-oracle")
    record = w.oracle(folder, src, env, state)
    msgs = [
        json.loads(line)
        for line in gzip.decompress((folder / "no-run/stdout.gz").read_bytes()).splitlines()
    ]
    (exe,) = [
        Path(m["executable"])
        for m in msgs
        if m.get("executable") and m.get("target", {}).get("kind") == ["test"]
    ]
    assert keep(pool, exe) == record["program"]
    kit.save(dest / (label + "-behavior.json"), record)


def arm(root, out, bins, mode, src, env, pool):
    dest = out / mode
    dest.mkdir()
    tools, _ = w.paths(root, dest, env)
    kit.save(dest / "stable-rustc.json", kit.stable(tools["rustc"]))
    assert all(not Path(env[k]).exists() for k in ("CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR"))
    snapshot = {}

    def visit(phase, cmd):
        result = run(dest / phase, cmd, src, env)
        assert result.returncode == 0, (mode, phase, result.returncode, result.stderr[-600:])
        verify_artifact_inventory(result.stdout, phase)
        current = artifacts.snapshot(result.stdout, env, pool)
        assert keep(pool, Path(current["library"])) == current["archive"]
        current["work_products"] = keep(pool, Path(current["session"]))
        kit.save(dest / (phase + "-artifacts.json"), current)
        snapshot[phase] = current

    w.git(src, "apply", "--reverse", str(COMMON / "renderer.patch"))
    kit.save(dest / "old-source.json", w.sources(src, "old"))
    visit("old", CLI)
    behavior(dest, src, env, "old", "old", pool)
    w.park(root, root / (mode + "-old-oracle"), ("oracle-target", "oracle-shared"))
    w.git(src, "apply", str(COMMON / "renderer.patch"))
    kit.save(dest / "edited-source.json", w.sources(src, "corrected"))
    if mode == "tree":
        trace = dest / "edit-counter"
        trace.mkdir()
        measured = [bins / "workers", trace, "hardware", tools["rustc"], "annotate_snippets"]
    else:
        measured = [bins / "plain", dest / "edit-perf.json"]
    visit("edit", [*measured, *CLI])
    visit("repeat", [bins / "plain", dest / "repeat-perf.json", *CLI])
    w.park(root, root / (mode + "-finished-history"), ("target", "shared"))
    assert all(not Path(env[k]).exists() for k in ("CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR"))
    visit("empty", CLI)
    behavior(dest, src, env, "edited", "corrected", pool)
    w.sources(src, "corrected")
    artifacts.compare(snapshot, lambda h: (pool / h).read_bytes())


def main(position, pinned):
    root = Path(os.environ["RUNNER_TEMP"]) / "gnu-renderer-library-workers"
    root.mkdir()
    out = root / "receipt"
    out.mkdir()
    try:
        head = os.environ["GITHUB_SHA"]
        attempt = os.environ["GITHUB_RUN_ATTEMPT"]
        assert re.fullmatch("[a-f0-9]{40}", head) and attempt == "1"
        assert root.is_absolute() and not root.is_symlink() and shutil.disk_usage(root).free > 12 * 2**30
        assert (
            subprocess.check_output(["git", "-C", HERE, "rev-parse", "HEAD"], text=True).strip() == head
        )
        assert (
            kit.sha(COMMON / "SHA256SUMS")
            == "c5699f1e7821adef2d2339803e455d44f652239cdfe083b4ab9a3de14e803699"
        )
        host = runpy.run_path(str(COMMON / "study.py"))["host"]()
        kit.save(out / "host.json", host)
        kit.save(
            out / "enrollment.json",
            {
                "position": position,
                "order": ORDERS[position],
                "cli": CLI,
                "attempt": attempt,
                "run": os.environ["GITHUB_RUN_ID"],
                "head": head,
                "plan": kit.sha(HERE / "PLAN.md"),
                "source": kit.sha(HERE / "SHA256SUMS"),
                "inherited_source": kit.sha(COMMON / "SHA256SUMS"),
            },
        )
        bins = pmu.compilers(root)
        for name, file, flags in [
            ("workers", "workers.c", ["-I", str(COMMON)]),
            ("calibrator", "calibrator.c", ["-pthread"]),
        ]:
            cmd = [
                "cc",
                "-std=gnu11",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                *flags,
                HERE / file,
                "-o",
                bins / name,
            ]
            assert run(out / ("build-" + name), cmd, root).returncode == 0
        store = out / "observers"
        store.mkdir()
        for name in ("plain", "loop", "tree", "nested", "workers", "calibrator"):
            shutil.copy2(bins / name, store / name)
        kit.save(
            out / "compiler.json",
            {
                "cc": subprocess.check_output(["cc", "--version"], text=True),
                "observers": {p.name: kit.sha(p) for p in store.iterdir()},
            },
        )
        calibration(root, out, bins)
        received = out / "custody"
        received.mkdir()
        donor = kit.acquire(root, received, pinned)
        del os.environ["GH_TOKEN"]
        cargo = root / "cargo-301"
        (received / "cargo-301").rename(cargo)
        src = w.source(root)
        kit.activate(root, donor, cargo)
        env = w.env_for(root)
        seed = w.prepare_registry(root, src, env, out)
        locked = readback.load(out / "registry-locks.json")
        (root / "sdk").rename(root / "ingress-sdk")
        (root / "slot").rename(root / "ingress-slot")
        pool = out / "native-objects"
        pool.mkdir()
        installed, registries = [], []
        for mode in ORDERS[position]:
            assert shutil.disk_usage(root).free > 4 * 2**30
            install = kit.activate(root, donor, cargo)
            installed.append(install)
            kit.save(out / (mode + "-activation.json"), install)
            env = w.env_for(root)
            assert set(env).isdisjoint(
                {
                    "RUSTFLAGS",
                    "RUSTC_WRAPPER",
                    "RUSTC_WORKSPACE_WRAPPER",
                    "CARGO_INCREMENTAL",
                    "CARGO_LOG",
                    "CI",
                    "GH_TOKEN",
                    "GITHUB_TOKEN",
                }
            )
            private = registry(Path(env["CARGO_HOME"]), seed, locked)
            registries.append(private)
            kit.save(out / (mode + "-registry.json"), private)
            arm(root, out, bins, mode, src, env, pool)
            (root / "sdk").rename(root / (mode + "-sdk"))
            (root / "slot").rename(root / (mode + "-slot"))
        assert installed[0]["SDK_inode"] != installed[1]["SDK_inode"]
        assert installed[0]["operational_tools"] == installed[1]["operational_tools"]
        assert registries[0]["root"] != registries[1]["root"]
        reopen(out)
        kit.save(
            out / "worker-complete.json",
            {
                "position": position,
                "run": os.environ["GITHUB_RUN_ID"],
                "scope": "one qualified position; joint decision requires both independent hosts",
            },
        )
    except BaseException:
        (out / "refused.txt").write_text(traceback.format_exc())
        raise


def reopen(out):
    pmu.calibration(out / "observers", out, replay=True)
    enroll = readback.load(out / "enrollment.json")
    assert enroll["source"] == kit.sha(HERE / "SHA256SUMS") and enroll["plan"] == kit.sha(
        HERE / "PLAN.md"
    )
    locked = readback.load(out / "registry-locks.json")
    assert len(locked) == 498
    signed = readback.load(out / "custody/signed.json")
    assert (
        signed["release"]["assets"][0]["sha256"]
        == readback.load(COMMON / "signed-members.json")["sha256"]
    )
    assert (
        len(signed["members"]) == 3768
        and signed["provenance"]["sources"]["rust"]["revision"] == kit.RUST
    )
    cargo = readback.load(out / "custody/cargo.json")
    assert cargo["source"] == kit.TOOLCARGO and cargo["archive_features"] == "ohm-defaults,all-static"
    rows = {}
    for mode in ORDERS[enroll["position"]]:
        d = out / mode
        sysroot = readback.load(out / (mode + "-activation.json"))
        registry_proof = readback.load(out / (mode + "-registry.json"))
        assert registry_proof["archive_count"] == len(locked)
        for n, expected_sha in [
            ("bin/rustc", kit.RUST_ELF),
            ("bin/cargo", kit.CARGO),
            (kit.WILD_PATH, kit.WILD),
        ]:
            assert sysroot["operational_tools"][n][1] == expected_sha
        ids = readback.load(d / "identities.json")
        assert kit.RUST in ids["versions"]["rustc"] and kit.TOOLCARGO in ids["versions"]["cargo"]
        for phase in ("old", "edit", "repeat", "empty"):
            assert readback.load(d / phase / "invocation.json")["status"] == 0
            verify_artifact_inventory(gzip.decompress((d / phase / "stdout.gz").read_bytes()), phase)
            snap = readback.load(d / (phase + "-artifacts.json"))
            blob = (out / "native-objects" / snap["archive"]).read_bytes()
            index = (out / "native-objects" / snap["work_products"]).read_bytes()
            assert kit.H(blob) == snap["archive"] and kit.H(index) == snap["work_products"]
            members = artifacts.archive(blob)
            assert kit.H(members["lib.rmeta"]) == snap["metadata"]
            objects = {
                k.split(".")[-4] + ".o": kit.H(v) for k, v in members.items() if k.endswith(".rcgu.o")
            }
            assert objects == {k: v[0] for k, v in snap["cgu"].items()}
            assert all(k.encode() in index for k in objects)
        images = {}
        for label, state in [("old", "old"), ("edited", "corrected")]:
            proof = readback.load(d / (label + "-behavior.json"))
            assert readback.load(d / (label + "-source.json")) == kit.ROLES["source_inputs"][state]
            case = d / (label + "-oracle") / "case"
            raw = readback.load(case / "invocation.json")
            assert raw["status"] == 0 and raw["argv"][1:] == [
                "--exact",
                "multiple_insertions",
                "--nocapture",
                "--test-threads=1",
            ]
            stdout, stderr = [
                gzip.decompress((case / (n + ".gz")).read_bytes()) for n in ("stdout", "stderr")
            ]
            assert [kit.H(stdout), kit.H(stderr)] == [proof["stdout"], proof["stderr"]]
            assert b"running 1 test" in stdout and b"1 passed; 0 failed" in stdout
            assert (b"panicked" in stderr) == (state == "old") and (
                state != "old" or b"index out of bounds" in stderr
            )
            assert kit.sha(out / "native-objects" / proof["program"]) == proof["program"]
            images[label] = proof["program"]
        rows[mode] = (sysroot, registry_proof, images)
    tree, plain = rows["tree"], rows["plain"]
    assert (
        tree[0]["SDK_inode"] != plain[0]["SDK_inode"]
        and tree[0]["operational_tools"] == plain[0]["operational_tools"]
    )
    assert tree[1]["root"] != plain[1]["root"] and tree[2] == plain[2]
    selectors = readback.load(out / "tree/selected.json")
    trace = out / "tree/edit-counter"
    execs = [
        line.split("\t")
        for line in (trace / "events.tsv").read_text().splitlines()
        if line.startswith("exec\t")
    ]
    physical = {role: tuple(row[:2]) for role, row in selectors.items()}
    rustcs = [r for r in execs if tuple(map(int, r[2:4])) == physical["rustc"]]
    assert len(rustcs) == 1 and rustcs[0][4] == "1"
    assert not any(
        tuple(map(int, r[2:4])) in {physical[k] for k in ("cc", "collect2", "wild")} for r in execs
    )
    argv = (trace / "selected.argv").read_bytes().split(b"\0")
    assert argv.count(b"--crate-type") == 1 and argv[argv.index(b"--crate-type") + 1] == b"lib"
    assert b"--emit=dep-info,metadata,link" in argv and any(b"incremental=" in a for a in argv)
    return readback.report(out)


def pair(roots):
    enrollments = [readback.load(r / "enrollment.json") for r in roots]
    assert {e["position"] for e in enrollments} == set(ORDERS)
    assert all(
        len({e[key] for e in enrollments}) == 1
        for key in ("run", "head", "plan", "source", "inherited_source")
    )
    assert all(
        (r / "worker-complete.json").is_file() and not (r / "refused.txt").exists() for r in roots
    )
    results = [reopen(r) for r in roots]
    assert len({r["boot"] for r in results}) == 2
    decision = {}
    for name in ("all_six", "two_debug_only"):
        values = [2 * v["possibly_removable"] - v["whole"] for host in results for v in host[name]]
        if all(x < 0 for x in values):
            decision[name] = "even removing all these worker instructions cannot halve the edit"
        elif all(x > 0 for x in values):
            decision[name] = (
                "both hosts have theoretical headroom; a safe implementation and its cost remain unmeasured"
            )
        else:
            decision[name] = "the two-host bounds leave the 2x question unresolved"
    return {
        "hosts": results,
        "decision": decision,
        "scope": "two independently calibrated edit instruction ceilings",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    collect = subs.add_parser("worker")
    collect.add_argument("position", choices=ORDERS)
    collect.add_argument("signed_helpers", type=Path)
    verify = subs.add_parser("pair")
    verify.add_argument("receipt", type=Path, nargs=2)
    opts = parser.parse_args()
    if opts.command == "worker":
        main(opts.position, opts.signed_helpers.resolve())
    else:
        print(json.dumps(pair(opts.receipt), indent=2, sort_keys=True))
