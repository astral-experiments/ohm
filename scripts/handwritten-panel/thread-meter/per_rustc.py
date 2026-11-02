"""Measure userspace instructions in selected, unwrapped Cargo compiler processes and their threads."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import runpy
import struct
import subprocess
import sys

EVENTS = runpy.run_path(str(Path(__file__).with_name("exec_events.py")))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write_json(path, value):
    with path.open("x") as out:
        json.dump(value, out, indent=2, sort_keys=True)
        out.write("\n")


def read_counter(raw):
    require(len(raw) == 32, "short pinned hardware-counter read")
    value, enabled, running, event_id = struct.unpack("=4Q", raw)
    require(value > 0 and event_id > 0 and enabled == running > 0, "zero or multiplexed instruction counter")
    return dict(instructions=value, time_enabled_ns=enabled, time_running_ns=running, event_id=event_id,
                raw_hex=raw.hex())


def capture(request, dest, library):
    require(dest.is_dir() and not any(dest.iterdir()), "capture output must be an empty directory")
    cmd = request["command"]
    compiler = Path(request["compiler_path"])
    require(compiler.is_absolute() and Path(cmd[0]).is_absolute(), "absolute compiler and root command required")
    file_id = EVENTS["file_id"](compiler)
    selectors = request["selectors"]
    require(isinstance(selectors, dict) and 1 <= len(selectors) <= 128, "one to 128 exact selectors required")
    by_argv = {}
    for label, argv in selectors.items():
        require(isinstance(label, str) and re.fullmatch(r"[A-Za-z0-9_-]+", label), "invalid target label")
        require(isinstance(argv, list) and argv and all(type(x) is str for x in argv), "invalid exact argv")
        require(tuple(argv) not in by_argv, "two labels share one compiler selector")
        by_argv[tuple(argv)] = label
    opener = ctypes.CDLL(str(library), use_errno=True).ohm_open_user_instructions
    opener.restype = ctypes.c_int
    opener.argtypes = (ctypes.c_int,)
    handles = {}
    seen = {}

    def on_exec(pid, previous_tid, snapshot):
        require(pid not in handles and previous_tid not in handles, "measured process executed a second image")
        if snapshot["file"] != file_id:
            return
        label = by_argv.get(tuple(snapshot["argv"]))
        if label is None:
            return
        require(label not in seen, "multiple processes matched the same exact selector")
        tasks = list((Path("/proc") / str(pid) / "task").iterdir())
        require([t.name for t in tasks] == [str(pid)], "selected image was already multithreaded")
        fd = opener(pid)
        if fd == -1:
            error = ctypes.get_errno()
            raise OSError(error, f"perf_event_open for stopped {label}: {os.strerror(error)}")
        handles[pid] = fd
        seen[label] = pid

    try:
        EVENTS["capture"](dest, cmd, request["environment"], request["cwd"], file_id, on_exec)
        data = json.loads((dest / "kernel-events.json").read_bytes())
        tree = EVENTS["decode"](data)
        require(tree["exits"][tree["root"]] == 0, "root Cargo invocation failed")
        require(file_id == EVENTS["file_id"](compiler) and seen.keys() == selectors.keys(), "missing compiler selection")
        reports = {}
        for label, pid in seen.items():
            argv = selectors[label]
            matching = [r for r in tree["images"] if r["file"] == file_id and r.get("argv") == argv]
            require(len(matching) == 1 and matching[0]["pid"] == pid and tree["exits"].get(pid) == 0,
                    "completed selected compiler has the wrong kernel lineage")
            reports[label] = dict(pid=pid, exe=matching[0]["exe"], argv=argv, file=file_id,
                                  **read_counter(os.read(handles[pid], 32)))
        require(len({r["event_id"] for r in reports.values()}) == len(reports), "hardware event ID reused")
        write_json(dest / "per-rustc.json", {"scope": "retired userspace instructions in the selected process and its threads",
                                            "root": tree["root"], "targets": reports})
    finally:
        for fd in handles.values():
            os.close(fd)


def calibrate(dest, library, workload):
    require(sys.platform == "linux" and os.uname().machine == "x86_64", "calibration requires Linux x86-64")
    require(dest.is_dir() and not any(dest.iterdir()), "calibration output must be an empty directory")
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
    results = {}
    small, large = 3000000, 14000000
    for mode, multiplier in (("serial", 1), ("threads", 3), ("fork", 0), ("reexec", None)):
        counts = []
        for n in (small, large) if multiplier is not None else (small,):
            name = f"{mode}-{n}"
            visit = dest / name
            visit.mkdir()
            argv = [str(workload), mode, str(n)]
            request = dict(command=argv, cwd=str(dest), environment=env, compiler_path=str(workload),
                           selectors={"probe": argv})
            request_file = dest / (name + ".json")
            write_json(request_file, request)
            proc = subprocess.run([sys.executable, "-ISB", __file__, "capture", str(request_file), str(visit),
                                   str(library)], capture_output=True)
            (dest / (name + ".stderr")).write_bytes(proc.stderr)
            if multiplier is None:
                require(proc.returncode != 0 and b"measured process executed a second image" in proc.stderr,
                        "second exec in selected process must be refused")
                require(not (visit / "per-rustc.json").exists(), "rejected image produced a score")
                continue
            require(proc.returncode == 0, f"calibration visit {name} failed: {proc.stderr[-450:]!r}")
            require((visit / "stdout").read_bytes() == f"completed {mode} {n}\n".encode(), "wrong native workload")
            report = json.loads((visit / "per-rustc.json").read_bytes())["targets"]["probe"]
            require(read_counter(bytes.fromhex(report["raw_hex"]))["instructions"] == report["instructions"],
                    "calibration counter receipt mismatch")
            events = json.loads((visit / "kernel-events.json").read_bytes())
            forks = [(row[1] >> 16) for row in events["events"]
                     if isinstance(row[1], int) and os.WIFSTOPPED(row[1]) and row[0] == events["root"]]
            if mode == "threads":
                require(forks.count(3) == 3, "missing native pthread births")
            if mode == "fork":
                require(forks.count(1) + forks.count(2) == 1, "missing excluded native fork")
            counts.append(report["instructions"])
        if multiplier is not None:
            expected = 2 * multiplier * (large - small)
            observed = counts[1] - counts[0]
            require(abs(expected - observed) <= 100000, f"{mode} instruction slope differs from known work")
            results[mode] = dict(counts=counts, expected_delta=expected, measured_delta=observed)
    write_json(dest / "calibration.json", dict(known_two_instruction_loop=results, reexec_rejected=True))


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("kernel lineage assertions must be enabled")
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("capture")
    for name in ("request", "output", "library"):
        c.add_argument(name, type=Path)
    p = sub.add_parser("calibrate")
    for name in ("output", "library", "workload"):
        p.add_argument(name, type=Path)
    args = parser.parse_args()
    if args.command == "capture":
        capture(json.loads(args.request.read_bytes()), args.output.resolve(), args.library.resolve())
    else:
        calibrate(args.output.resolve(), args.library.resolve(), args.workload.resolve())
