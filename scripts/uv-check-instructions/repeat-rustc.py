#!/usr/bin/python3
"""Repeat a single rustc invocation with its exact pre-edit incremental state."""
from pathlib import Path
import os
import json
import fcntl
import shutil
import subprocess
import sys
import tempfile

args = json.loads(Path(sys.argv[1]).read_text()) if os.getenv("IN_PERF")=="yes" else sys.argv[1:]
subjects = os.environ.get("REPEAT_UNITS","").split(",")
subject = args[args.index("--crate-name")+1] if "--crate-name" in args else None
if subject and subject in subjects:
    if os.environ.get("IN_PERF") != "yes":
        os.environ["IN_PERF"]="yes"
        perf = os.environ["PROFILER"]
        output = os.path.join(os.environ["PERF_DIR"], subject+".data")
        argfile = Path(output+".args")
        argfile.write_text(json.dumps(args))
        lock = open(Path(output).parent / "perf.lock","w")
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        p = subprocess.run([perf,"record","-e","instructions:u","-c","900001",
                            "--call-graph","dwarf,4096","-m","256","-o",output,"--",__file__,str(argfile)],
                           close_fds=False)
        sys.exit(p.returncode)
    root, = [Path(v.partition("incremental=")[2]) for v in args
             if v.startswith(("incremental=", "-Cincremental="))]
    sessions = list(root.glob(subject + "-*"))
    assert sessions, (root, list(root.iterdir()))
    with tempfile.TemporaryDirectory() as d:
        saved = Path(d)
        for s in sessions:
            shutil.copytree(s, saved/s.name)
        repeats = int(os.environ.get("REPEAT_COUNT", "48"))
        for repeat in range(repeats - 1):
            subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           close_fds=False, check=True)
            for s in sessions:
                shutil.rmtree(s)
                shutil.copytree(saved/s.name, s)
    (Path(os.environ["REPEAT_DIR"])/(subject+"-repeats")).write_text(f"{subject} {repeats}\n")
os.execvp(args[0],args)
