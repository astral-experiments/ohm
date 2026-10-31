"""Abort only the task-owned native worker group when its runner approaches a resource floor."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent


def resources(root):
    mem=int(next(l.split()[1] for l in Path("/proc/meminfo").read_text().splitlines() if l.startswith("MemAvailable:")))*1024
    cg=Path("/sys/fs/cgroup")
    limits=[]
    # cgroup namespaces may present the effective delegated root at / or a named relative directory.
    line=next((l[3:] for l in Path("/proc/self/cgroup").read_text().splitlines() if l.startswith("0::")),None)
    if line:
        group=(cg/line.lstrip("/")).resolve()
        if group.is_relative_to(cg):
            while True:
                top,current=group/"memory.max",group/"memory.current"
                if top.is_file() and current.is_file() and (v:=top.read_text().strip())!="max":
                    limits.append(max(0,int(v)-int(current.read_text())))
                if group==cg:break
                group=group.parent
    return {"host_memory":mem,"cgroup_remaining":limits,"available_memory":min([mem,*limits]),
            "work_free":shutil.disk_usage(root/"work").free,"durable_free":shutil.disk_usage(root/"logs").free}


def passes(v,floors):
    return all(v[k]>=n*2**30 for k,n in zip(("available_memory","work_free","durable_free"),floors,strict=True))


def main():
    root=Path(os.environ["RUNNER_TEMP"])/"ohm-branch-object-qa"
    available=resources(root)
    (root/"logs"/"admission-capacity.json").write_text(json.dumps(available)+"\n")
    if not passes(available,(12,14,32)):raise RuntimeError(("entry capacity",available))
    run=subprocess.Popen([sys.executable,"-IB",HERE/"screen.py",*sys.argv[1:]],start_new_session=True)
    with (root/"logs"/"capacity.jsonl").open("x") as output:
        while True:
            try:return run.wait(timeout=3)
            except subprocess.TimeoutExpired:pass
            v=resources(root);print(json.dumps({"time_ns":time.monotonic_ns(),**v}),file=output,flush=True)
            if not passes(v,(5,3,6)):
                try:os.killpg(run.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                try:run.wait(timeout=8)
                except subprocess.TimeoutExpired:os.killpg(run.pid,signal.SIGKILL);run.wait()
                raise RuntimeError(("stopped only the enrolled native process group",v))


if __name__=="__main__":sys.exit(main())
