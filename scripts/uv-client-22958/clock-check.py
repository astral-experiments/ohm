"""Calibration only. Contrast the blocking clock with the released historical Python timer."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from statistics import median
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from blocking_clock import measure


def run(dest):
    assert not dest.exists()
    dest.mkdir()
    cflags = ["-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    exe = dest / "child"
    subprocess.run(["/usr/bin/cc", *cflags, str(HERE / "clock-fixture.c"), "-o", str(exe)], check=True)
    durations = [11, 19, 37, 71, 109, 137, 169, 211, 247, 283, 347, 389]
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
    rows = {"blocking": [], "prior_timeout": []}
    def one(i, ms, rc, mode, stdout, stderr):
        argv = [str(exe), str(ms), str(rc)]
        with stdout.open("xb") as stream, stderr.open("xb") as errors:
            if mode == "blocking":
                x = measure(argv, cwd=dest, env=env, stdout=stream, stderr=errors)
            else:
                start = time.monotonic_ns()
                c = subprocess.run(argv, cwd=dest, env=env, stdout=stream, stderr=errors, timeout=1500)
                end = time.monotonic_ns()
                x = dict(start_ns=start, end_ns=end, ns=end-start, exit=c.returncode)
        pid, child_start, child_finish = map(int, stdout.read_bytes().split())
        assert x["exit"] == rc and stderr.read_bytes() == b""
        assert x.get("pid", pid) == pid and x["start_ns"] <= child_start <= child_finish <= x["end_ns"]
        assert child_finish-child_start >= ms*1_000_000
        return dict(pair=i, delay_ms=ms, child_pid=pid, child_start_ns=child_start,
                    child_pre_exit_ns=child_finish, observed_after_child_ns=x["end_ns"]-child_finish,
                    on_launch_before_child_ns=child_start-x["start_ns"], clock=x)
    for i, ms in enumerate(durations):
        order = ("blocking","prior_timeout") if not i%2 else ("prior_timeout","blocking")
        for mode in order:
            where = dest / f"{i:02d}-{mode}"
            rows[mode].append(one(i, ms, 0, mode, where.with_suffix(".stdout"), where.with_suffix(".stderr")))
    neg = one(-1, 1, 7, "blocking", dest/"nonzero.stdout", dest/"nonzero.stderr")
    assert neg["clock"]["exit"] == 7
    bounds = {}
    for mode, xs in rows.items():
        lag = [item["observed_after_child_ns"] for item in xs]
        bounds[mode] = dict(min_ns=min(lag), median_ns=median(lag), max_ns=max(lag))
    assert bounds["blocking"]["median_ns"] < 2_000_000 and bounds["blocking"]["max_ns"] < 10_000_000
    info = time.get_clock_info("monotonic")
    assert info.monotonic and not info.adjustable and info.resolution <= .000001
    return dict(boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        affinity=sorted(os.sched_getaffinity(0)), sources={n:hashlib.sha256((HERE/n).read_bytes()).hexdigest() for n in ("blocking_clock.py","clock-fixture.c","clock-check.py")},
        binary_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(), cflags=cflags, clock=vars(info),
        python=sys.version, bounds=bounds, rows=rows, proved_native_nonzero=7,
        eligible_blocking_calibration=True, uv_observed=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fresh_destination", type=Path)
    args = parser.parse_args()
    dest = args.fresh_destination.resolve()
    data = run(dest)
    (dest/"verified.json").write_text(json.dumps(data, sort_keys=True, indent=2)+"\n")
    print(json.dumps(data["bounds"],sort_keys=True))
