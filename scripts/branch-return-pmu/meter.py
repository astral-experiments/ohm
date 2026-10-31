"""Run the previously validated inherited-counter calibration on this worker's own hardware."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from bindings import CAL, OBS, OUT, ROOT, need, prepare_checkout, save


def calibrate(calibration_src, observers):
    import os, subprocess

    prepare_checkout(calibration_src, CAL, "scripts/gnu-renderer-pfc-hardware")
    prepare_checkout(observers, OBS, "scripts/gnu-example-ceiling")
    base = calibration_src / "scripts/gnu-renderer-pfc-hardware"
    subprocess.run(
        ["sha256sum", "--strict", "--check", "--status", "SHA256SUMS"], cwd=base, check=True
    )
    sys.path.insert(0, str(base))
    import calibration

    boot = calibration.host(observers, OUT)
    binary = calibration.setup(observers, ROOT, OUT)
    need(
        binary == OUT / "observers/plain" and len(os.sched_getaffinity(0)) == 8,
        "unapproved clock binary or affinity",
    )
    save(
        OUT / "meter-ready.json",
        dict(
            boot=boot,
            affinity=sorted(os.sched_getaffinity(0)),
            observer=OBS,
            calibrator=CAL,
            plain=str(binary),
        ),
    )


def clock(path, expected):
    import json

    r = json.loads(path.read_bytes())
    need(
        set(r)
        == {
            "start",
            "stop",
            "user_us",
            "system_us",
            "instructions",
            "enabled",
            "running",
            "event_errno",
            "code",
        }
        and all(type(v) is int for v in r.values()),
        ("clock ABI", path),
    )
    need(
        r["code"] == expected
        and r["event_errno"] == 0
        and 0 < r["running"] <= r["enabled"]
        and 1000 * r["running"] >= 995 * r["enabled"]
        and r["instructions"] > 0
        and r["start"] < r["stop"]
        and r["user_us"] + r["system_us"] > 0,
        ("invalid unscaled inherited instructions", path, r),
    )
    return r


if __name__ == "__main__":
    calibrate(*map(Path, sys.argv[1:]))
