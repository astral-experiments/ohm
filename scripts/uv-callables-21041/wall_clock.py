"""Time an unmodified command using blocking waitpid, with a separate kernel deadline."""
import hashlib
import json
import os
from pathlib import Path
import signal
from statistics import median
import subprocess
import time

HERE = Path(__file__).resolve().parent


def guard(ok, error):
    if not ok:
        raise ValueError(error)


def save(path, obj):
    with path.open("x") as f:
        json.dump(obj, f, sort_keys=True, indent=2)
        f.write("\n")


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()


def current():
    return {"boot":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "cpus":sorted(os.sched_getaffinity(0))}


class Deadline(Exception):
    pass


def invoke(argv, cwd, env, out, err, seconds):
    """Launch the actual binary, block until reaped, and kill its private group on deadline."""
    proc = None
    def expire(signum, frame):
        raise Deadline("hard child deadline")
    guard(signal.getitimer(signal.ITIMER_REAL)==(0.0,0.0),"another real timer is active")
    original=signal.signal(signal.SIGALRM,expire)
    timed_out=False
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        start=time.monotonic_ns()
        proc=subprocess.Popen(argv,cwd=cwd,env=env,stdout=out,stderr=err,start_new_session=True)
        code=proc.wait()
        end=time.monotonic_ns()
    except Deadline:
        timed_out=True
        if proc is None:
            raise
        try:
            os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:
            pass
        code=proc.wait()
        end=time.monotonic_ns()
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,original)
    return {"start_ns":start,"end_ns":end,"ns":end-start,"exit":code,"pid":proc.pid,"deadline_fired":timed_out}


def command(path,argv,mode,cwd,env,seconds=1500,success=True):
    path.mkdir()
    before=current()
    with (path/"cargo.stdout").open("xb") as out,(path/"cargo.stderr").open("xb") as err:
        r=invoke(argv,cwd,env,out,err,seconds)
    guard(before==current() and r["ns"]>0,"machine changed")
    r.update(before,argv=argv,invoked=argv,mode=mode,env=env,timer="CLOCK_MONOTONIC; waitpid blocking; ITIMER_REAL watchdog")
    save(path/"ordinary.json",r)
    if success:
        guard(r["exit"]==0 and r["deadline_fired"] is False,("native command failed",path))
    return r


def physical_cores():
    selected={}
    for cpu in sorted(os.sched_getaffinity(0)):
        base=Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
        key=tuple((base/name).read_text().strip() for name in ("physical_package_id","core_id"))
        selected.setdefault(key,cpu)
    ids=list(selected.values())[:8]
    guard(len(ids)==8,"eight distinct physical cores required")
    return ids


def calibrate(folder,exe):
    folder.mkdir()
    if not exe.exists():
        subprocess.run(["/usr/bin/cc","-std=c11","-O2","-Wall","-Wextra","-Werror",HERE/"wall_probe.c","-o",exe],check=True)
    identity=current()
    env={"PATH":"/usr/bin:/bin","LC_ALL":"C"}
    samples=[]
    for i in range(5):
        for delay in (0,3,13,31,53):
            q=folder/f"probe-{i}-{delay}"
            r=command(q,[str(exe),str(delay),"0"],"calibration",folder,env)
            a,b=map(int,(q/"cargo.stdout").read_bytes().split())
            overhead=r["ns"]-(b-a)
            guard(r["start_ns"]<=a<=b<=r["end_ns"] and b-a>=delay*1_000_000 and
                  0<=overhead<=12_000_000,"clock precision or child interval")
            samples.append({"ms":delay,"internal_ns":b-a,"external_ns":r["ns"],"enclosing_overhead_ns":overhead})
    guard(median(r["enclosing_overhead_ns"] for r in samples)<=4_000_000,"median overhead")
    rc=command(folder/"nonzero",[str(exe),"0","17"],"known-nonzero",folder,env,success=False)
    guard(rc["exit"]==17 and not rc["deadline_fired"],"nonzero child status")
    deadline=command(folder/"deadline",[str(exe),"2000","0"],"known-timeout",folder,env,.07,False)
    guard(deadline["deadline_fired"] and deadline["exit"]==-signal.SIGKILL and
          60_000_000<=deadline["ns"]<1_000_000_000 and not (folder/"deadline/cargo.stdout").read_bytes(),"watchdog control")
    result=dict(machine=identity,probe=sha(exe),source=sha(HERE/"wall_probe.c"),clock_source=sha(__file__),
                samples=samples,nonzero_exit=rc["exit"],deadline_exit=deadline["exit"],deadline_ns=deadline["ns"])
    save(folder/"passed.json",result)
    return result
