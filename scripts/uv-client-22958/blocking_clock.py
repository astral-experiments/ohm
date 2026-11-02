"""Time a native argv with blocking waitpid. The enclosing benchmark job owns timeouts."""
from pathlib import Path
import os
import subprocess
import time


def measure(argv, *, cwd, env, stdout, stderr):
    if not argv or not Path(argv[0]).is_absolute():
        raise ValueError("expected an absolute executable")
    start_ns = time.monotonic_ns()
    child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stdout, stderr=stderr)
    pid, status = os.waitpid(child.pid, 0)
    end_ns = time.monotonic_ns()
    child.returncode = os.waitstatus_to_exitcode(status)
    assert pid == child.pid and start_ns < end_ns
    return {
        "pid": pid, "exit": child.returncode, "start_ns": start_ns,
        "end_ns": end_ns, "ns": end_ns - start_ns, "argv": list(argv),
        "wait": "os.waitpid(child.pid, 0)",
    }
