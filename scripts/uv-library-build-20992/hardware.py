"""Enforce one fresh machine, blocking-wait isolation and both original native PMU calibrations."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import native
import kernel
HERE=Path(__file__).resolve().parent
PILOT="5c651f1d38c629da2a75d5cac3588db0be8104d7"
CAL="2f413ca94b84af2dbd6d6231bcf8d860c97ebee8"
OBS="8a659140df8ab27fd6a8cc61f5eb38717b3f8bbc"
def boot():return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
def machine():
    cpus=sorted(os.sched_getaffinity(0));cores={}
    for i in cpus:
        t=Path(f"/sys/devices/system/cpu/cpu{i}/topology")
        group=tuple((t/name).read_text().strip() for name in ("physical_package_id","core_id"));cores.setdefault(group,i)
    assert len(cores)>=8;selected=sorted(list(cores.values())[:8]);os.sched_setaffinity(0,selected)
    return dict(boot=boot(),cpus=selected,runner=os.environ["RUNNER_NAME"],run=int(os.environ["GITHUB_RUN_ID"]),job_key=os.environ["GITHUB_JOB"],attempt=int(os.environ["GITHUB_RUN_ATTEMPT"]),head=os.environ["GITHUB_SHA"])
def preflight_scope():
    assert os.environ["GITHUB_REPOSITORY"]=="astral-experiments/ohm" and os.environ["GITHUB_EVENT_NAME"]=="workflow_dispatch"
    assert os.environ["GITHUB_REF"]=="refs/heads/charlie/codex-20992-production-build-guard" and os.environ["GITHUB_RUN_ATTEMPT"]=="1"
    assert os.environ["RUNNER_OS"]=="Linux" and os.environ["RUNNER_ARCH"]=="X64"
    return machine()
def caller_watchdog():
    free=min(shutil.disk_usage(p).free for p in (native.TRANSIENT,native.V,native.ROOT))
    owned={p:int(subprocess.check_output(["du","-sb",p],text=True).split()[0])for p in (native.TRANSIENT,native.V,native.ROOT)}
    total=sum(owned.values());assert total<24<<30 and free>(20<<30)+(24<<30)-total,(free,owned)
def clock_control(slot):
    where=native.ROOT/slot;where.mkdir();c=HERE/"timer.c";exe=native.TRANSIENT/"timer"
    subprocess.run(["cc","-std=gnu11","-O2","-Wall","-Wextra","-Werror",c,"-o",exe],check=True)
    trials=[];delays=[9,51,15,36,4,28,67,11,24,41]
    for i,ms in enumerate(delays):
        w=where/str(i);r=native.run_command(w,[exe,str(ms)],env={"PATH":"/usr/bin:/bin","LC_ALL":"C"})
        observed=int((w/"stdout").read_text());over=r["wall_ns"]-observed
        assert ms*10**6<=observed and 0<=over<20*10**6,(ms,observed,r,over)
        trials.append(dict(request_ns=ms*10**6,native_elapsed_ns=observed,blocking_parent_ns=r["wall_ns"],over_ns=over))
    native.save(where/"passed.json",dict(boot=boot(),driver_sha=native.sha(c),blocking_processes=trials))
def calibrate():
    info=preflight_scope();assert info["boot"]not in native.read(HERE/"host-exclusions.json")
    native.ROOT.mkdir(exist_ok=True);native.TRANSIENT.mkdir(exist_ok=True)
    assert not native.V.exists();native.V.mkdir(mode=0o700);native.SRC.mkdir();(native.V/".owned-20992").touch(exist_ok=False)
    native.save(native.ROOT/"host.json",info);caller_watchdog();clock_control("clock-pre")
    w=Path(os.environ["GITHUB_WORKSPACE"]);tmp=Path(os.environ["RUNNER_TEMP"])
    for name,ref in (("pilot",PILOT),("calibrator",CAL),("observers",OBS)):
        assert subprocess.check_output(["git","-C",w/name,"rev-parse","HEAD"],text=True).strip()==ref
        assert subprocess.check_output(["git","-C",w/name,"status","--porcelain","--untracked-files=no"])==b""
    pilot=w/"pilot/scripts/branch-return-pmu"
    for n,h in (("meter.py","5884db65be186a23811bfbf7743a46c25679c995"),("bindings.py","8345df71c46383086cc82745b6091c07b5598271")):
        assert subprocess.check_output(["git","hash-object",pilot/n],text=True).strip()==h
    dest=tmp/"ohm-branch-object-qa/logs";dest.mkdir(parents=True)
    subprocess.run([sys.executable,"-IB",pilot/"meter.py",w/"calibrator",w/"observers"],check=True,timeout=480)
    ready=native.read(dest/"meter-ready.json");assert ready["boot"]==info["boot"] and ready["affinity"]==info["cpus"] and ready["calibrator"]==CAL and ready["observer"]==OBS
    plain=Path(ready["plain"]);assert plain==dest/"observers/plain"
    clocks=sorted((dest/"calibration").glob("whole-*-*.json"));assert len(clocks)==28
    for p in clocks:
        row=native.read(p);assert row["code"]==row["event_errno"]==0 and row["instructions"]>0 and row["enabled"]==row["running"]>0
    shutil.copytree(dest,native.ROOT/"inherited-controls")
    meter=HERE/"thread-meter"
    subprocess.run(["sha256sum","--strict","--check","--status","SHA256SUMS"],cwd=meter,check=True)
    for n,flags,out in (("pmu.c",["-fPIC","-shared"],"libohm_pmu.so"),("workload.c",["-pthread"],"thread-work")):
        subprocess.run(["cc","-O2","-Wall","-Wextra","-Werror",*flags,meter/n,"-o",native.TRANSIENT/out],check=True)
    t=native.ROOT/"thread-controls";t.mkdir()
    subprocess.run([sys.executable,"-ISB",meter/"per_rustc.py","calibrate",t,native.TRANSIENT/"libohm_pmu.so",native.TRANSIENT/"thread-work"],check=True)
    tc=native.read(t/"calibration.json");assert tc["reexec_rejected"] and set(tc["known_two_instruction_loop"])=={"serial","threads","fork"}
    native.save(native.ROOT/"calibration.json",dict(host=info,clock=native.sha(native.ROOT/"clock-pre/passed.json"),thread=native.sha(t/"calibration.json"),plain=str(plain),plain_sha=native.sha(plain),inherited={p.name:native.sha(p)for p in clocks},registration=native.sha(HERE/"protocol.json")))
def enter():
    x=native.read(native.ROOT/"calibration.json");assert x["host"]==preflight_scope() and x["plain_sha"]==native.sha(Path(x["plain"]));return x
def whole_record(r):
    assert set(r)=={"start","stop","user_us","system_us","instructions","enabled","running","event_errno","code"} and all(type(x)is int for x in r.values())
    assert r["code"]==r["event_errno"]==0 and r["instructions"]>0 and r["enabled"]==r["running"]>0 and 0<=r["start"]<r["stop"] and min(r["system_us"],r["user_us"])>=0
    return r
def inherited(where):
    bare=kernel.command();measure=where/"instructions.json";plain=Path(enter()["plain"])
    native.run_command(where,[plain,measure,*bare]);return whole_record(native.read(measure))
def per_compiler(where,opening):
    where.mkdir();command=kernel.command();request=where.parent/(where.name+"-request.json")
    v=kernel.vectors(opening);native.save(request,dict(command=command,environment=native.environment(),cwd=str(native.SRC),compiler_path=str(native.SDK/"bin/rustc"),selectors=v))
    subprocess.run([sys.executable,"-ISB",HERE/"thread-meter/per_rustc.py","capture",request,where,native.TRANSIENT/"libohm_pmu.so"],check=True)
    actual=kernel.read_enrollment(where,"B");kernel.match(opening,actual)
    measurement=native.read(where/"per-rustc.json")["targets"];assert measurement.keys()==v.keys()
    for n,m in measurement.items():
        assert m["pid"]==actual["targets"][n]["pid"] and m["argv"]==v[n] and m["time_running_ns"]==m["time_enabled_ns"]>0 and m["instructions"]>0
    return measurement

