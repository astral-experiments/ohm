#!/usr/bin/env python3
"""Exercise flat dependency-graph generations across fresh rustc subprocesses."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

FLAG = "RUSTC_OHM_FLAT_DEP_GRAPH"
TRACE = "RUSTC_OHM_FLAT_DEP_GRAPH_TRACE"
PREFIX = "ohm-flat-dep-graph\t"
SNAPSHOT = "ohm-flat-dep-graph.bin"
HELPERS = 384
CHECKSUM = sum(range(HELPERS))


def source(marker, *, structural=False, broken=False):
    if broken:
        declaration = "fn marker() -> usize { missing_function() }"
    elif structural:
        declaration = (
            "trait Marker { fn get() -> usize; }\n"
            "struct Revision;\n"
            f"impl Marker for Revision {{ fn get() -> usize {{ {marker} }} }}\n"
            "fn marker() -> usize { Revision::get() }"
        )
    else:
        declaration = f"fn marker() -> usize {{ {marker} }}"
    helpers = "\n".join(
        f"#[inline(never)] fn helper_{index}() -> usize {{ {index} }}"
        for index in range(HELPERS)
    )
    calls = " + ".join(f"helper_{index}()" for index in range(HELPERS))
    return (
        f'#![recursion_limit = "1024"]\n{declaration}\n{helpers}\nfn warm() -> usize {{ {calls} }}\n'
        'fn main() { println!("{}", marker() + warm()); }\n'
    )


def snapshot_path(incremental):
    sessions = [
        path
        for crate in incremental.iterdir()
        if crate.is_dir()
        for path in crate.iterdir()
        if path.is_dir()
        and path.name.startswith("s-")
        and not path.name.endswith("-working")
    ]
    if not sessions:
        raise RuntimeError(f"no finalized incremental session beneath {incremental}")
    latest = max(sessions, key=lambda path: (path.stat().st_mtime_ns, path.name))
    return latest / SNAPSHOT


def inode(path):
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_dev, stat.st_ino


def binary_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def monitor_working(incremental, stop, inodes):
    while not stop.is_set():
        for path in incremental.glob(f"*/s-*-working/{SNAPSHOT}"):
            if (observed := inode(path)) is not None:
                inodes.add(observed)
        stop.wait(0.001)


def invoke(command, environment, incremental):
    observed = set()
    stop = threading.Event()
    monitor = threading.Thread(
        target=monitor_working, args=(incremental, stop, observed), daemon=True
    )
    monitor.start()
    try:
        child = subprocess.Popen(
            command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        try:
            stdout, stderr = child.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate()
            raise
    finally:
        stop.set()
        monitor.join()
    stderr = stderr.decode()
    events = [
        line.removeprefix(PREFIX)
        for line in stderr.splitlines()
        if line.startswith(PREFIX)
    ]
    return child.pid, child.returncode, stdout.decode(), stderr, events, observed


def run(args):
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    fixture = root / "fixture.rs"
    work = {mode: root / mode for mode in ("candidate", "stock")}
    for path in work.values():
        (path / "incremental").mkdir(parents=True)
    environment = os.environ.copy()
    environment.pop(FLAG, None)
    environment[TRACE] = "1"
    results = []
    process_ids = set()

    def step(name, mode, marker, *, structural=False, broken=False, expect=()):
        fixture.write_text(source(marker, structural=structural, broken=broken))
        directory = work[mode]
        incremental = directory / "incremental"
        executable = directory / ("fixture.exe" if os.name == "nt" else "fixture")
        try:
            prior_inode = inode(snapshot_path(incremental))
        except RuntimeError:
            prior_inode = None
        before = binary_hash(executable) if executable.exists() else None
        command = [
            str(args.rustc.resolve()),
            "--crate-name=fixture",
            "--edition=2021",
            "-Cdebuginfo=0",
            "-Ccodegen-units=8",
            f"-Cincremental={incremental}",
            str(fixture),
            "-o",
            str(executable),
        ]
        if args.sysroot:
            command.extend(["--sysroot", str(args.sysroot.resolve())])
        env = environment | ({FLAG: "1"} if mode == "candidate" else {})
        pid, returncode, stdout, stderr, events, observed = invoke(
            command, env, incremental
        )
        (directory / f"{name}.stderr").write_text(stderr)
        (directory / f"{name}.stdout").write_text(stdout)
        if events != list(expect):
            raise AssertionError(
                f"{name}: expected trace {expect}, got {events}:\n{stderr}"
            )
        if broken:
            if not returncode or "missing_function" not in stderr:
                raise AssertionError(f"{name}: expected compile error:\n{stderr}")
            if before is None or before != binary_hash(executable):
                raise AssertionError(
                    f"{name}: previous executable changed after a compile error"
                )
        else:
            if returncode:
                raise AssertionError(f"{name}: failed to build:\n{stderr}")
            completed = subprocess.run(
                [executable], capture_output=True, text=True, check=True
            )
            if completed.stdout != f"{marker + CHECKSUM}\n":
                raise AssertionError(
                    f"{name}: stale/wrong executable: {completed.stdout!r}"
                )
            if (
                before is not None
                and name in {"structural", "repair", "missing", "corrupt", "wrong"}
                and before == binary_hash(executable)
            ):
                raise AssertionError(
                    f"{name}: a behavioral change left executable bytes unchanged"
                )
        result = {
            "name": name,
            "mode": mode,
            "fresh_compiler_process": pid not in process_ids,
            "events": events,
            "compile_error": broken,
            "test_ran": not broken,
            "shared_source_inode_observed": prior_inode in observed
            if prior_inode
            else None,
        }
        process_ids.add(pid)
        results.append(result)

    step("initial", "candidate", 2, expect=("written",))
    first = snapshot_path(work["candidate"] / "incremental").read_bytes()
    step("warm", "candidate", 2, expect=("loaded", "written"))
    step("structural", "candidate", 9, structural=True, expect=("loaded", "written"))
    step("compile-error", "candidate", 0, broken=True, expect=("loaded",))
    step("repair", "candidate", 13, structural=True, expect=("loaded", "written"))

    snapshot_path(work["candidate"] / "incremental").unlink()
    step("missing", "candidate", 21, expect=("fallback", "written"))

    snapshot = snapshot_path(work["candidate"] / "incremental")
    damaged = bytearray(snapshot.read_bytes())
    damaged[-8] ^= 1
    snapshot.write_bytes(damaged)
    step("corrupt", "candidate", 34, structural=True, expect=("fallback", "written"))

    snapshot_path(work["candidate"] / "incremental").write_bytes(first)
    step("wrong", "candidate", 55, expect=("fallback", "written"))
    step("final-warm", "candidate", 55, expect=("loaded", "written"))
    step("stock-initial", "stock", 55, expect=())
    step("stock-warm", "stock", 55, expect=())

    if len(process_ids) != len(results):
        raise AssertionError(
            f"expected a fresh compiler PID in every scenario: {results}"
        )
    loaded = [result for result in results if "loaded" in result["events"]]
    inode_checks = sum(
        result["shared_source_inode_observed"] is True for result in loaded
    )
    if sys.platform == "darwin" and not inode_checks:
        raise AssertionError(
            "no loaded working session was observed mapping the finalized APFS inode"
        )
    report = {
        "schema": 1,
        "fresh_compiler_processes": len(process_ids),
        "cache_hits": len(loaded),
        "stock_fallbacks": sum("fallback" in result["events"] for result in results),
        "same_finalized_and_working_inode_observations": inode_checks,
        "compile_errors_without_execution": sum(
            result["compile_error"] for result in results
        ),
        "results": results,
    }
    (root / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rustc", required=True, type=Path)
    parser.add_argument("--sysroot", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
