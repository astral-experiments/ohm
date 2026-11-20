#!/usr/bin/python3
"""Repeat a single rustc invocation with its exact pre-edit incremental state."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

args = sys.argv[1:]
subjects = os.environ.get("REPEAT_UNITS","").split(",")
subject = args[args.index("--crate-name")+1] if "--crate-name" in args else None
if subject and subject in subjects:
    pids = []
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
            p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 close_fds=False)
            assert p.wait() == 0
            pids.append(p.pid)
            for s in sessions:
                shutil.rmtree(s)
                shutil.copytree(saved/s.name, s)
    (Path(os.environ["REPEAT_DIR"])/(subject+"-repeats")).write_text(f"{subject} {repeats}\n")
    pids.append(os.getpid())
    (Path(os.environ["REPEAT_DIR"])/(subject+"-pids")).write_text(",".join(map(str,pids)))
os.execvp(args[0],args)
