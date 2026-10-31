"""Optional sampled filesystem high water on a dedicated task-owned loop device."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import threading
import time


def write(path, data):
    with path.open("x") as f:
        json.dump(data, f, sort_keys=True, separators=(",", ":"))
        f.write("\n")


def identity(root, work):
    rows = json.loads(
        subprocess.check_output(
            ["findmnt", "-J", "-o", "TARGET,SOURCE,FSTYPE,MAJ:MIN", "--target", work]
        )
    )["filesystems"]
    if len(rows) != 1:
        return None
    r = rows[0]
    sysfile = Path("/sys/dev/block") / r["maj:min"] / "loop/backing_file"
    if (
        r["target"] != str(work)
        or r["fstype"] != "ext4"
        or not sysfile.is_file()
        or Path(sysfile.read_text().strip()).resolve() != (root / "task-owned.ext4").resolve()
    ):
        return None
    if any(
        not (work / x).is_dir() or (work / x).stat().st_dev != work.stat().st_dev
        for x in ("target", "build")
    ):
        return None
    # The loop mount contains only our two artifact roots, its ownership marker, the
    # ext4 administrative directory. The Ruff source is outside this private mount.
    top = {x.name for x in work.iterdir()}
    if not top.issubset({"target", "build", ".owned-by-packed-study", "lost+found"}):
        return None
    return {"findmnt": r, "backing_file": str(sysfile), "top_level": sorted(top)}


def calibrate(root, work, output):
    physical = identity(root, work)
    if physical is None:
        row = {
            "available": False,
            "reason": "runner filesystem is shared or its unique backing file is unknown",
        }
    else:
        expected = 4 << 20

        def used():
            f = os.statvfs(work)
            return (f.f_blocks - f.f_bfree) * f.f_frsize

        before = used()
        name = work / ".first-checkout-calibration"
        with name.open("xb") as w:
            os.posix_fallocate(w.fileno(), 0, expected)
            os.fsync(w.fileno())
            during = used()
            inode = w.fileno()
            stat_bytes = os.fstat(inode).st_blocks * 512
        name.unlink()
        fd = os.open(work, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        # ext4 may defer a free; a failure disables only the optional sampled peak.
        after = used()
        row = {
            "available": stat_bytes == expected and during - before >= expected and before == after,
            "mount": physical,
            "before": before,
            "held": during,
            "after": after,
            "allocated_inode": stat_bytes,
        }
    write(output, row)
    return row


@contextmanager
def command(root, work, folder):
    physical = identity(root, work)
    evidence = folder / "sampled-filesystem.json"
    calibration = json.loads((root / "logs" / "peak-capability.json").read_bytes())
    if physical is None or not calibration["available"] or calibration.get("mount") != physical:
        write(
            evidence,
            {
                "available": False,
                "reason": "no verified exclusive ext4 loop mount",
                "peak": "unmeasured",
            },
        )
        yield
        return

    def sample():
        fs = os.statvfs(work)
        return [time.monotonic_ns(), fs.f_frsize, fs.f_blocks - fs.f_bfree]

    before = [sample()]
    for _ in range(4):
        time.sleep(0.025)
        before.append(sample())
    if len({tuple(s[1:]) for s in before}) != 1:
        write(
            evidence,
            {
                "available": False,
                "reason": "filesystem allocation changing at idle",
                "idle": before,
                "mount": physical,
            },
        )
        yield
        return
    samples = [before[-1]]
    stop = threading.Event()

    def collect():
        while not stop.wait(0.025):
            samples.append(sample())

    t = threading.Thread(target=collect)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join()
        samples.append(sample())
        if any(row[1] != samples[0][1] for row in samples) or identity(root, work) != physical:
            write(
                evidence,
                {
                    "available": False,
                    "reason": "mount/block size changed",
                    "samples": samples,
                    "mount": physical,
                },
            )
        else:
            write(
                evidence,
                {
                    "available": True,
                    "scope": "unmetered Cargo on dedicated mount",
                    "mount": physical,
                    "idle": before,
                    "samples": samples,
                    "max_gap_ns": max(b[0] - a[0] for a, b in zip(samples, samples[1:])),
                    "maximum_observed_allocated_bytes": max(s[1] * s[2] for s in samples),
                    "max_observed_growth_from_first_read": max(s[1] * s[2] for s in samples)
                    - samples[0][1] * samples[0][2],
                    "exact_transient_peak": None,
                },
            )
