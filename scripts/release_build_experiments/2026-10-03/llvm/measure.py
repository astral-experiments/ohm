#!/usr/bin/env python3
"""Capture serialized release-build commands and reject compiler contention."""
import argparse
import hashlib
import json
import os
import resource
import re
from pathlib import Path
import subprocess
import threading
import time

COMPILERS = {"rustc", "cargo", "clang", "clang++", "cc1", "cc1plus", "gcc", "g++", "ld", "lld", "rust-lld", "ld.lld"}


def external_compilers():
    output = subprocess.check_output(["ps", "-eo", "pid=,ppid=,comm="], text=True)
    processes = {}
    for line in output.splitlines():
        pid, ppid, command = line.split(None, 2)
        processes[int(pid)] = (int(ppid), Path(command).name)
    def belongs(pid):
        seen = set()
        while pid in processes and pid not in seen:
            if pid == os.getpid():
                return True
            seen.add(pid)
            pid = processes[pid][0]
        return pid == os.getpid()
    return sorted(f"{pid} {command}" for pid, (_, command) in processes.items()
                  if command in COMPILERS and not belongs(pid))


def cpu_snapshot():
    total = [int(n) for n in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    processes = {}
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        try:
            raw = (path / "stat").read_text()
            start, end = raw.index("("), raw.rindex(")")
            fields = raw[end + 2:].split()
            processes[int(path.name)] = (int(fields[1]), raw[start + 1:end], int(fields[11]) + int(fields[12]))
        except (OSError, ValueError, IndexError):
            continue
    return total, processes


def external_cpu(previous, current):
    _, before = previous
    _, after = current
    ticks = os.sysconf("SC_CLK_TCK")
    def ours(pid):
        seen = set()
        while pid in after and pid not in seen:
            if pid == os.getpid(): return True
            seen.add(pid)
            pid = after[pid][0]
        return pid == os.getpid()
    activity = []
    for pid, (_, name, usage) in after.items():
        if ours(pid) or pid not in before:
            continue
        delta = max(0, usage - before[pid][2]) / ticks
        if delta:
            activity.append({"pid": pid, "name": name, "cpu_seconds": delta})
    return activity


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--allow-exit", type=int, action="append", default=[0])
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    args.output.mkdir(parents=True, exist_ok=True)
    stderr = args.output / (args.name + ".stderr")
    stdout = args.output / (args.name + ".stdout")
    receipt = args.output / (args.name + ".json")
    if any(path.exists() for path in (stderr, stdout, receipt)):
        raise SystemExit("refusing to replace existing evidence")
    interference = set(external_compilers())
    if interference:
        raise SystemExit(f"host busy: {interference}")
    errors = []
    cpu_samples = []
    initial_cpu = cpu_snapshot()
    stop = threading.Event()
    def monitor():
        previous = initial_cpu
        while not stop.wait(0.5):
            try:
                interference.update(external_compilers())
                current = cpu_snapshot()
                cpu_samples.append({"time_unix": time.time(), "total_cpu_ticks": current[0], "loadavg": Path("/proc/loadavg").read_text().strip(), "external_activity": external_cpu(previous, current)})
                previous = current
            except Exception as error:
                errors.append(str(error))
                return
    worker = threading.Thread(target=monitor, daemon=True)
    worker.start()
    started_unix = time.time()
    started = time.perf_counter()
    with stdout.open("wb") as out, stderr.open("wb") as err:
        result = subprocess.run(command, cwd=args.cwd, stdout=out, stderr=err)
    wall = time.perf_counter() - started
    stop.set()
    worker.join()
    log = stderr.read_text(errors="replace")
    contention = "blocking waiting for file lock" in log.lower()
    expected_package = command[command.index("-p") + 1] if "rustc" in command and "-p" in command else None
    compiled = expected_package is None or re.search(r"\bCompiling\s+" + re.escape(expected_package) + r"\s", log) is not None
    environment_keys = {"CARGO_HOME", "CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR", "CARGO_BUILD_JOBS", "CARGO_INCREMENTAL", "CARGO_PROFILE_RELEASE_LTO", "CARGO_PROFILE_RELEASE_CODEGEN_UNITS", "CARGO_PROFILE_RELEASE_OPT_LEVEL", "RUSTC", "RUSTDOC", "RUSTC_WRAPPER", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTUP_TOOLCHAIN"}
    measured_environment = {key: os.environ[key] for key in sorted(environment_keys) if key in os.environ}
    cpu_path = args.output / (args.name + ".cpu.json")
    cpu_path.write_text(json.dumps({"initial_cpu_ticks": initial_cpu[0], "samples": cpu_samples}, indent=2) + "\n")
    external_seconds = sum(row["cpu_seconds"] for sample in cpu_samples for row in sample["external_activity"])
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    data = {"command": command, "cwd": str(args.cwd.resolve()),
        "environment": measured_environment, "start_unix": started_unix,
        "wall_seconds": wall, "returncode": result.returncode, "external_cpu_seconds": external_seconds, "max_rss_kib": usage.ru_maxrss, "children_user_seconds": usage.ru_utime, "children_system_seconds": usage.ru_stime,
        "external_compilation": sorted(interference), "monitor_errors": errors,
        "cargo_lock_contention": contention, "expected_package": expected_package, "compilation_observed": compiled, "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "valid": result.returncode in args.allow_exit and not interference and not errors and not contention and compiled,
        "stdout_sha256": hashlib.sha256(stdout.read_bytes()).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr.read_bytes()).hexdigest()}
    receipt.write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps(data), flush=True)
    raise SystemExit(0 if data["valid"] else 1)


if __name__ == "__main__":
    main()
