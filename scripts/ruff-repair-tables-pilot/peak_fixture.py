"""Validate reachable storage, detached-process observation and PSS against physical known allocations."""

from pathlib import Path
import gzip
import hashlib
import json
import os
import ctypes
import subprocess as sp
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
M = 1 << 20
PYTHON = "/usr/bin/python3"


def alloc(path, amount):
    file = path.open("w+b")
    os.posix_fallocate(file.fileno(), 0, amount * M)
    return file


def workload(root):
    private = root / "target"
    shared = root / "build"
    quiet = root / "synchronization"
    base = alloc(private / "common", 32)
    os.link(private / "common", shared / "alias")
    (shared / "pointer").symlink_to("../target/common")
    assert (private / "common").stat().st_nlink == 2
    before = (private / "common").stat()
    gone = alloc(shared / "temporary", 5)
    (shared / "temporary").unlink()
    path = shared / "closed-mapped"
    f = alloc(path, 7)
    f.flush()
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mmap.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_long,
    ]
    libc.mmap.restype = ctypes.c_void_p
    libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    mapping = libc.mmap(None, 7 * M, 3, 1, f.fileno(), 0)
    assert mapping not in (None, ctypes.c_void_p(-1).value)
    inode = os.fstat(f.fileno())
    ctypes.c_ubyte.from_address(mapping).value = 17
    f.close()
    path.unlink()
    for entry in Path("/proc/self/fd").iterdir():
        try:
            st = entry.stat()
        except FileNotFoundError:
            continue
        assert (st.st_dev, st.st_ino) != (inode.st_dev, inode.st_ino)
    (quiet / "mapped-ino").write_text(json.dumps([inode.st_dev, inode.st_ino]))
    child = os.fork()
    if child == 0:
        os.setsid()
        one = os.fork()
        if one:
            os._exit(0)
        memory = bytearray(32 * M)
        for pos in range(0, len(memory), 4096):
            memory[pos] = 29
        w = private / "debug/incremental/0123456789abcdef/test-cgu/s-calibration-working"
        w.mkdir(parents=True)
        first = alloc(w / "dep-graph.bin", 16)
        second = alloc(w / "ohm-packed-dep-graph.bin", 8)
        conventional = shared / "debug/incremental/test-cgu/s-calibration2-working"
        conventional.mkdir(parents=True)
        os.link(w / "ohm-packed-dep-graph.bin", conventional / "query-cache.bin")
        yes = threading.Event()
        t = threading.Thread(target=yes.wait)
        t.start()
        (quiet / "detached").write_text(str(os.getpid()))
        time.sleep(0.65)
        yes.set()
        t.join()
        first.close()
        second.close()
        os._exit(0)
    os.waitpid(child, 0)
    main_memory = bytearray(24 * M)
    for pos in range(0, len(main_memory), 4096):
        main_memory[pos] = 17
    while not (quiet / "detached").exists():
        time.sleep(0.02)
    (quiet / "main").write_text(str(os.getpid()))
    time.sleep(0.85)
    assert main_memory[0] == 17 and (shared / "alias").stat().st_ino == before.st_ino
    base.close()
    gone.close()
    assert libc.munmap(mapping, 7 * M) == 0


def main():
    if len(sys.argv) > 1:
        return workload(Path(sys.argv[1]))
    root = Path(os.environ["SCOPED_WORK"])
    assert not list(root.iterdir())
    for key in ("target", "build", "synchronization"):
        (root / key).mkdir()
    outside = os.environ["OBSERVATION_OUTER_PIDNS"]
    assert os.getpid() == 1 and outside != os.readlink("/proc/self/ns/pid")
    opts = [
        PYTHON,
        "-ISB",
        str(HERE / "peak.py"),
        "--root",
        str(root / "target"),
        "--root",
        str(root / "build"),
        "--outside",
        outside,
        "--result",
        str(root / "data.json.gz"),
        "--period",
        "0.02",
        "--",
        PYTHON,
        "-ISB",
        str(Path(__file__).resolve()),
        str(root),
    ]
    refused = sp.run(opts, capture_output=True)
    assert (
        refused.returncode
        and b"fresh, owned PID namespace" in refused.stderr
        and not (root / "data.json.gz").exists()
    )
    # Run in the single approved namespace. The actual monitor itself must be its init.
    import importlib.util

    spec = importlib.util.spec_from_file_location("qualified_sampler", HERE / "peak.py")
    sampler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sampler)
    command = opts[opts.index("--") + 1 :]
    result = sampler.observe(command, [root / "target", root / "build"], outside, root / "data.json.gz", 0.02)
    assert result == 0, result
    raw = (root / "data.json.gz").read_bytes()
    q = json.loads(gzip.decompress(raw))
    child = (root / "synchronization/detached").read_text()
    mainpid = (root / "synchronization/main").read_text()
    samples = q["samples"]
    mapped_inode = json.loads((root / "synchronization/mapped-ino").read_bytes())

    def maps_accounted(r):
        known = r["open_deleted"] == 12 * M and not r["unresolved_deleted_maps"]
        unknown = r["open_deleted"] == 5 * M and any(
            v[:2] == mapped_inode for v in r["unresolved_deleted_maps"]
        )
        return mapped_inode in r["deleted_mapping_inodes"] and (known or unknown)

    matches = [
        r
        for r in samples
        if r["allocated"] >= 56 * M
        and r["aliases"] == 2
        and maps_accounted(r)
        and child in r["processes"]
        and mainpid in r["processes"]
        and r["processes"][child]["threads"] >= 2
        and r["pss_anon"] >= 56 * M
        and r["pss"] >= r["pss_anon"]
        and len(r["working_tables"]) == 2
        and all(v for v in r["working_tables"].values())
        and r["processes"][mainpid]["rss"] >= r["processes"][mainpid]["pss"] >= 24 * M
        and r["processes"][child]["rss"] >= r["processes"][child]["pss"] >= 32 * M
    ]
    assert (
        len(matches) >= 3
        and q["allocated_peak"] - q["before"]["allocated"] <= 57 * M
        and q["allocated_including_deleted_peak"] >= 61 * M
    )
    assert len(q["lifetime_sampled_max"]) >= 2
    if q["sampled_deleted_accounting_complete"]:
        assert all(r["open_deleted"] == 12 * M for r in matches)
    else:
        assert any(r["unresolved_deleted_maps"] for r in matches)
    assert int(child) != q["main_pid"] and q["reaped"][child] == 0 and q["reaped"][mainpid] == 0
    assert q["outside_namespace"] == outside and q["namespace"] != outside
    report = dict(
        physically_verified=[
            "separate PID namespace/procfs",
            "untrusted outside-namespace invocation refused",
            "32 MiB cross-root hardlink counted once",
            "5 MiB open-unlinked file counted separately",
            "7 MiB mmap survived last FD close and unlink, fresh inode matched or unstatable snapshot marked incomplete",
            "two concurrent real allocations plus a detached adopted child with two TIDs",
            "scoped task working directory pair observed",
            "aggregate process PSS from smaps_rollup",
        ],
        mapped_stat_available=q["sampled_deleted_accounting_complete"],
        result=q["exit"],
        n_samples=len(samples),
        matched=len(matches),
        allocated_peak=q["allocated_peak"],
        allocated_including_unlinked_peak=q["allocated_including_deleted_peak"],
        pss_peak=q["pss_peak"],
        pss_anon_peak=q["pss_anon_peak"],
        rss_peak=q["rss_peak"],
        lifetime_sampled_max=q["lifetime_sampled_max"],
        largest_runnable_gap_ns=max(r["runnable_window_ns"] for r in samples),
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        command=command,
    )
    (root / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {k: report[k] for k in ("matched", "n_samples", "allocated_peak", "pss_peak", "raw_sha256")}
        )
    )


if __name__ == "__main__":
    main()
