#!/usr/bin/python3
"""Repeat a single rustc invocation with its exact pre-edit incremental state."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

args = sys.argv[1:]
subject = os.environ.get("REPEAT_UNIT")
if subject and "--crate-name" in args and args[args.index("--crate-name")+1] == subject:
    root, = [Path(v.partition("incremental=")[2]) for v in args
             if v.startswith(("incremental=", "-Cincremental="))]
    sessions = list(root.glob(subject + "-*"))
    assert sessions, (root, list(root.iterdir()))
    with tempfile.TemporaryDirectory() as d:
        saved = Path(d)
        for s in sessions:
            shutil.copytree(s, saved/s.name)
        for repeat in range(47):
            subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           close_fds=False, check=True)
            for s in sessions:
                shutil.rmtree(s)
                shutil.copytree(saved/s.name, s)
    Path(os.environ["REPEAT_RECEIPT"]).write_text(subject+" 48\n")
os.execvp(args[0],args)
