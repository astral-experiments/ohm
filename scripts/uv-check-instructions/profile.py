"""Sample two units at the first held-out uv check after the twenty-edit replay."""

import argparse
import collections
import gzip
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import CHECK, TIP, HOLDOUT, command, git, sha


def find_perf():
    for path in [shutil.which("perf"), *Path("/usr/lib/linux-tools").glob("*/perf")]:
        if path and subprocess.run([path, "--version"], capture_output=True).returncode == 0:
            return path
    raise RuntimeError("install linux-tools-generic")


import run

PERF = find_perf()
real_command = run.command
def record(argv, cwd, env, log):
    if log.name != "check.log" or log.parent.name != "21":
        return real_command(argv, cwd, env, log)
    data = cwd.parent / "check.data"
    real_command([PERF, "record", "-e", "instructions:u", "-c", "170003", "-m", "256",
                  "-o", data, "--", *argv], cwd, env, log)
    # perf script preserves actual process ids per sample before symbol aggregation.
    units = run.read_counts(log.parent/"units.tsv")
    dst = log.parents[2]
    for u in units:
        pid = u["pid"]
        name = u["name"]
        if name not in ("uv_lock","uv_project_commands"):
            continue
        report = subprocess.check_output([PERF,"report","--stdio","--pid",str(pid),"-i",data,
                  "--sort=pid,comm,dso,symbol","--fields=period,sample,comm,dso,symbol,pid",
                  "--percent-limit=0","--field-separator=|","--no-children"],env=env)
        with gzip.open(dst/(name+"-symbols.txt.gz"),"wb") as f:
            f.write(report)
        (dst/(name+"-repeats")).write_text(name+" 1\n")
    exact = subprocess.check_output([PERF,"script","-i",data,"-F","pid,comm,sym,dso"],env=env)
    with gzip.open(dst/"events.txt.gz","wb") as f:
        f.write(exact)
    (dst/"profile-role").write_text(log.parents[1].name)
    (dst/"period").write_text("170003")
    data.unlink()

run.command=record
run.main()
