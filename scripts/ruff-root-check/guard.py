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
    memberships=[l[3:] for l in Path("/proc/self/cgroup").read_text().splitlines() if l.startswith("0::")]
    mounts=[l.split(" - ",1) for l in Path("/proc/self/mountinfo").read_text().splitlines()]
    cgroup2=[left.split() for left,right in mounts if right.split()[0]=="cgroup2" and left.split()[4]==str(cg)]
    if len(memberships)!=1 or len(cgroup2)!=1 or cgroup2[0][3]!="/" or "memory" not in (cg/"cgroup.controllers").read_text().split():
        raise RuntimeError("cannot establish a complete visible cgroup2 memory hierarchy")
    leaf=memberships[0];group=(cg/leaf.lstrip("/")).resolve()
    if not group.is_relative_to(cg) or str(os.getpid()) not in (group/"cgroup.procs").read_text().splitlines():
        raise RuntimeError("unmapped process memory cgroup")
    levels=[]
    while True:
        top,current=group/"memory.max",group/"memory.current"
        if group==cg and not top.exists() and not current.exists():
            levels.append({"group":"/","max":"unlimited-unified-root","current":None})
        else:
            maximum=top.read_text().strip();current_bytes=int(current.read_text())
            levels.append({"group":"/" if group==cg else "/"+str(group.relative_to(cg)),"max":maximum if maximum=="max" else int(maximum),"current":current_bytes})
        if group==cg:break
        group=group.parent
    limits=[max(0,v["max"]-v["current"]) for v in levels if type(v["max"]) is int]
    return {"host_memory":mem,"cgroup_remaining":limits,"cgroup_leaf":leaf,"cgroup_levels":levels,"available_memory":min([mem,*limits]),
            "work_free":shutil.disk_usage(root/"work").free,"durable_free":shutil.disk_usage(root/"logs").free}


def checked(v):
    """Recompute every visible ancestor's headroom and the effective admission value."""
    leaf=Path(v["cgroup_leaf"]);st=v["cgroup_levels"]
    if not leaf.is_absolute() or ".." in leaf.parts or [x["group"] for x in st]!=[str(x) for x in (leaf,*leaf.parents)]:return False
    for x in st:
        if x["max"]=="unlimited-unified-root":
            if (x["group"],x["current"])!=("/",None):return False
        elif not ((x["max"]=="max" or type(x["max"]) is int and x["max"]>=0) and type(x["current"]) is int and x["current"]>=0):return False
    limits=[max(0,x["max"]-x["current"]) for x in st if type(x["max"]) is int]
    return v["host_memory"]>0 and limits==v["cgroup_remaining"] and min([v["host_memory"],*limits])==v["available_memory"]


def passes(v,floors):
    return all(v[k]>=n*2**30 for k,n in zip(("available_memory","work_free","durable_free"),floors,strict=True))


def main():
    root=Path(os.environ["RUNNER_TEMP"])/"ohm-branch-object-qa"
    available=resources(root)
    (root/"logs"/"admission-capacity.json").write_text(json.dumps(available)+"\n")
    if not checked(available) or not passes(available,(12,14,32)):raise RuntimeError(("entry capacity",available))
    run=subprocess.Popen([sys.executable,"-IB",HERE/"screen.py",*sys.argv[1:]],start_new_session=True)
    try:
        with (root/"logs"/"capacity.jsonl").open("x") as output:
            while True:
                try:return run.wait(timeout=3)
                except subprocess.TimeoutExpired:pass
                v=resources(root);print(json.dumps({"time_ns":time.monotonic_ns(),**v}),file=output,flush=True)
                if not checked(v) or not passes(v,(5,3,6)):
                    raise RuntimeError(("stopped only the enrolled native process group",v))
    finally:
        # A broken cgroup read, receipt write or Ctrl-C must also release this private group.
        if run.poll() is None:
            try:os.killpg(run.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            run.wait(timeout=12)



if __name__=="__main__":sys.exit(main())
