"""Physical workspace guard shared by both source-matched production roles."""
import ctypes
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time

GIB = 1 << 30
import runpy
HOOK=Path(__file__).resolve().parent
AUTHORITY="52779265edb1486bceb9f6abf0c7a24dfc0f234caea4a067653b0eceb514772b"
INITIAL=runpy.run_path(str(HOOK/"capacity-audit.py"))["authority"](HOOK/"capacity-admission.json",AUTHORITY,HOOK/"capacity-selector.py")
RESERVE = 16 * GIB
STOP = 48 * GIB
FLOOR = 32 * GIB
INTERVAL = 0.25
MAX_GAP = 2.0
CHILD_GRACE_NS = 5_000_000_000
BRANCH = "refs/heads/charlie/codex-21577-driver-link-production23-prelto"
STAGES = ("materialize", "prerequisites", "bolt-tools", "wild", "production", "native-qa")
SENTINEL = ".ctfe22-physical-emergency-reserve"


def put(path, value):
    with path.open("x") as f:
        json.dump(value, f, sort_keys=True, indent=1)
        f.write("\n")


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def fd_filesystem(fd):
    with open("/proc/self/mountinfo") as f:
        ids = {int(l.split()[0]): l.split(" - ", 1)[1].split()[0] for l in f}
    info = Path(f"/proc/self/fdinfo/{fd}").read_text()
    mid = int(re.search(r"(?m)^mnt_id:\s*(\d+)$", info)[1])
    fs = os.fstatvfs(fd)
    return {"device": os.fstat(fd).st_dev, "mount_id": mid, "kind": ids[mid],
            "statvfs_fsid": fs.f_fsid, "bytes_total": fs.f_blocks*fs.f_frsize, "fs_block": fs.f_frsize}


def same_mount(a, b):
    # Overlay mounts may report different st_dev for a directory and a regular
    # file. Retain both object st_dev values and identify the live VFS mount by FD.
    return all(a[k] == b[k] for k in ("mount_id","kind","statvfs_fsid","bytes_total","fs_block"))


def filesystem(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        result = fd_filesystem(fd)
        assert result["device"] == path.stat().st_dev
        return result
    finally:
        os.close(fd)


def space(work):
    fs = os.statvfs(work)
    return fs.f_bavail*fs.f_frsize


def allocate(path, size):
    before = space(path.parent)
    with path.open("xb", buffering=0) as f:
        try:
            os.posix_fallocate(f.fileno(), 0, size)
            os.fsync(f.fileno())
            st = os.fstat(f.fileno())
            reserve_fs = fd_filesystem(f.fileno())
            parent_fs = filesystem(path.parent)
            name_stat = path.stat(follow_symlinks=False)
            assert (name_stat.st_dev,name_stat.st_ino)==(reserve_fs["device"],st.st_ino)
            after = space(path.parent)
            assert st.st_size == size and st.st_blocks*512 >= size
            assert before-after >= size-min(size//16, 8<<20), (size,before,after)
        except BaseException:
            path.unlink()
            raise
    return {"inode":st.st_ino,"device":st.st_dev,"bytes":size,"allocated_bytes":st.st_blocks*512,
            "available_before":before,"available_after":after,"file_filesystem":reserve_fs,"parent_filesystem":parent_fs}


def verify_held(path, held, workspace_fs):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        st = os.fstat(fd)
        fs = fd_filesystem(fd)
        current = path.stat(follow_symlinks=False)
        assert stat.S_ISREG(st.st_mode) and st.st_nlink == 1
        assert (current.st_dev,current.st_ino)==(st.st_dev,st.st_ino)==(held["device"],held["inode"])
        assert st.st_size==held["bytes"] and st.st_blocks*512>=held["bytes"]
        assert fs==held["file_filesystem"] and workspace_fs==held["parent_filesystem"] and same_mount(workspace_fs,fs)
    finally:
        os.close(fd)


def release(path, held):
    st = path.lstat()
    assert stat.S_ISREG(st.st_mode) and st.st_nlink == 1
    assert (st.st_ino, st.st_dev, st.st_size) == (held["inode"], held["device"], held["bytes"])
    assert st.st_blocks*512 >= held["bytes"]
    path.unlink()


def context():
    e = os.environ
    assert e["GITHUB_REPOSITORY"] == "astral-experiments/ohm" and e["GITHUB_EVENT_NAME"] == "workflow_dispatch"
    assert e["GITHUB_REF"] == BRANCH and e["BENCH_ARM"]=="T"
    assert e["GITHUB_ACTIONS"]=="true" and e["GITHUB_JOB"]=="build" and e["GITHUB_RUN_ATTEMPT"]=="1" and e["GITHUB_WORKFLOW_SHA"]==e["GITHUB_SHA"] and e["GITHUB_WORKFLOW_REF"]==e["GITHUB_REPOSITORY"]+"/.github/workflows/ci.yml@"+BRANCH
    assert e["RUNNER_OS"]=="Linux" and e["RUNNER_ARCH"]=="X64" and e["RUNNER_NAME"].startswith("nsc-runner-")
    assert re.fullmatch(r"/home/runner/work/ohm/ohm/?",e["GITHUB_WORKSPACE"])
    assert e["GITHUB_SHA"] == e["REVIEWED_HEAD"] and re.fullmatch("[0-9a-f]{40}",e["GITHUB_SHA"])
    w = Path(e["GITHUB_WORKSPACE"]).resolve()
    head=subprocess.check_output(["git","-C",w,"rev-parse","HEAD","HEAD^"],text=True).splitlines()
    assert head==[e["GITHUB_SHA"],'e295118d5a8fd2fbe672d16c28d0df80ff1c2d20']
    assert e["GITHUB_RUN_ATTEMPT"]=="1"
    return w, w/"capacity-evidence"


def initialize(w, evidence):
    evidence.mkdir()
    (w/"trait-evidence").mkdir()
    available_df=subprocess.check_output(["df","-B1",str(w)]);(w/"trait-evidence/capacity-initial.txt").write_bytes(available_df);sys.stdout.buffer.write(available_df)
    initial = space(w)
    record = {"schema":1,"eligible_sdk":False,"role":os.environ["BENCH_ARM"],"admission_sha256":AUTHORITY,"workspace":str(w),"filesystem":filesystem(w),
              "runner":os.environ["RUNNER_NAME"],"head":os.environ["GITHUB_SHA"],
              "run":int(os.environ["GITHUB_RUN_ID"]),"attempt":int(os.environ["GITHUB_RUN_ATTEMPT"]),
              "initial_requirement":INITIAL,"sample_ms":250,"sample_max_gap_s":MAX_GAP,"initial_available":initial,
              "physical_reserve":RESERVE,"raw_free_stop":STOP,"raw_free_floor":FLOOR,
              "runner_temp_fs":filesystem(Path(os.environ["RUNNER_TEMP"]))}
    put(evidence/"intake.json",record)
    assert record["filesystem"]["device"] == record["runner_temp_fs"]["device"] and same_mount(record["filesystem"],record["runner_temp_fs"]) and initial >= INITIAL
    held = allocate(w/SENTINEL, RESERVE)
    put(evidence/"reserve.json",held)
    try:verify_held(w/SENTINEL,held,record["filesystem"])
    except BaseException:
        release(w/SENTINEL,held)
        raise


def remaining_subtree(root):
    todo = [root]
    children = set()
    while todo:
        p = todo.pop()
        try:
            for task in Path(f"/proc/{p}/task").iterdir():
                try:ids = (task/"children").read_text().split()
                except (OSError,ValueError):continue
                for item in ids:
                    n = int(item)
                    if n not in children:
                        children.add(n)
                        todo.append(n)
        except OSError:
            pass
    return children


def adopted_states():
    # Log only PID and state of this single-threaded subreaper's current direct children.
    ids = Path(f"/proc/self/task/{os.getpid()}/children").read_text().split()
    states = []
    for item in ids[:32]:
        try:
            row = Path(f"/proc/{int(item)}/stat").read_bytes().rsplit(b")", 1)[1].split()
        except (FileNotFoundError, ProcessLookupError):
            continue
        if int(row[1]) == os.getpid():
            states.append([int(item), row[0].decode("ascii")])
    return {"direct_count_at_read": len(ids), "first_32": states}


def drain_adopted(diagnostic, mon):
    drain = diagnostic.get("adopted")
    if drain is None:
        drain = diagnostic["adopted"] = {"start_ns": mon, "grace_ns": CHILD_GRACE_NS,
                                         "initial": adopted_states(), "reaped": [], "samples": 0}
    drain["samples"] += 1
    drain["last_sample_ns"] = mon
    # The foreground Popen was already reaped. waitpid now covers only this
    # subreaper's descendants. Each tick is bounded so the space watchdog keeps running.
    reason = "reap batch limit"
    for _ in range(128):
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            drain["no_children"] = True
            return True
        if pid == 0:
            reason = "live adopted child"
            break
        code = os.waitstatus_to_exitcode(status)
        drain["reaped"].append([pid, status, code])
        if code != 0:
            raise RuntimeError("adopted child exited unsuccessfully")
    if mon - drain["start_ns"] >= CHILD_GRACE_NS:
        drain["at_timeout"] = adopted_states()
        raise RuntimeError("release command child grace expired: " + reason)
    return False


def stop_owned(p):
    # New sessions remain in the child-subreaper's subtree. Avoid unrelated runner processes.
    denied = set()
    for sig in (signal.SIGSTOP, signal.SIGKILL, signal.SIGKILL):
        # Once the foreground was reaped, its former numerical process group
        # may be reused. The subreaper's current subtree is sufficient then.
        if p.poll() is None:
            try:os.killpg(p.pid,sig)
            except ProcessLookupError:pass
            except PermissionError:denied.add(p.pid)
        for pid in remaining_subtree(os.getpid()):
            try:os.kill(pid,sig)
            except ProcessLookupError:pass
            except PermissionError:denied.add(pid)
        if sig == signal.SIGKILL:time.sleep(.05)
    try:p.wait(timeout=2)
    except subprocess.TimeoutExpired:pass
    while True:
        try:pid,_=os.waitpid(-1,os.WNOHANG)
        except ChildProcessError:break
        if not pid:break
    return {"denied":sorted(denied),"surviving":sorted(remaining_subtree(os.getpid()))}


def pressure(now, last, gap):
    if now <= STOP:return "workspace free-space threshold"
    if gap > MAX_GAP:return "watchdog sampling gap"
    if 0 < gap and now < 2*STOP and now-(max(last-now,0)/gap)*2 <= STOP:
        return "workspace free-space downward trend"
    return None


def native_phase(w):
    q=w/"trait-evidence"
    for f,label in (("optimized-run-make.log","installed-original"),("run-make.log","run-make"),("unit.log","unit")):
        if (q/f).exists():return label
    return "distribution-and-install"


def watch(w, evidence, stage, shellfile):
    assert stage in STAGES
    baseline = json.loads((evidence/"intake.json").read_bytes())["filesystem"]
    held = json.loads((evidence/"reserve.json").read_bytes())
    cwd_fs = filesystem(Path.cwd())
    assert filesystem(w) == baseline and cwd_fs["device"] == baseline["device"] and same_mount(cwd_fs,baseline)
    verify_held(w/SENTINEL,held,baseline)
    assert ctypes.CDLL(None).prctl(36,1,0,0,0) == 0  # PR_SET_CHILD_SUBREAPER, Linux
    diagnostic = {"stage":stage,"raw_samples":0,"min_available":None,"max_gap_s":0.0,"cause":None}
    proc = None
    last_mon = time.monotonic_ns()
    last_free = space(w)
    with (evidence/f"{stage}.samples.jsonl").open("x",buffering=1) as stream:
        try:
            while True:
                mon = time.monotonic_ns()
                utc = time.time_ns()
                free = space(w)
                gap = (mon-last_mon)/1e9
                phase = native_phase(w) if stage=="native-qa" else stage
                stream.write(json.dumps([utc,mon,free,phase],separators=(",",":"))+"\n")
                diagnostic["raw_samples"]+=1
                diagnostic["min_available"]=free if diagnostic["min_available"] is None else min(free,diagnostic["min_available"])
                diagnostic["max_gap_s"]=max(gap, diagnostic["max_gap_s"])
                cause = pressure(free,last_free,gap)
                if cause:raise RuntimeError(cause)
                if proc is None:
                    cmd = ["/bin/bash","--noprofile","--norc","-e","-o","pipefail",shellfile]
                    if stage=="production":cmd=[sys.executable,"-ISB",str(HOOK.parent/"rc23-driver-link/watch.py"),shellfile]
                    proc = subprocess.Popen(cmd,start_new_session=True)
                elif proc.poll() is not None:
                    diagnostic["exit"]=proc.returncode
                    if proc.returncode:raise RuntimeError("release command failed")
                    if drain_adopted(diagnostic,mon):break
                last_mon,last_free=mon,free
                time.sleep(INTERVAL)
        except BaseException as e:
            diagnostic["cause"]=str(e) or type(e).__name__
            if proc is not None:diagnostic["termination"]=stop_owned(proc)
            if (w/SENTINEL).exists():release(w/SENTINEL,held)
            diagnostic["available_after_release"]=space(w)
            raise
        finally:
            stream.flush()
            os.fsync(stream.fileno())
            put(evidence/f"{stage}.json",diagnostic)


def events(build_log):
    pat = re.compile(r"\[(\d{4}-\d\d-\d\dT[^\s]+Z) INFO\s+opt_dist::timer\] Section `([^`]+)` (starts|ended: (?:OK|ERR[^ ]*))")
    found = []
    if build_log.exists():
        with build_log.open(errors="replace") as f:
            for line in f:
                if m:=pat.search(line):
                    when=int(datetime.datetime.fromisoformat(m[1]).timestamp()*1e9)
                    found.append((when,m[2],m[3]))
    return found


def score(w,evidence):
    data=json.loads((evidence/"intake.json").read_bytes())
    file=evidence/"reserve.json"
    held=json.loads(file.read_bytes()) if file.exists() else None
    if held and (w/SENTINEL).exists():release(w/SENTINEL,held)
    sections=events(w/"trait-evidence/build.log")
    put(evidence/"sections.json",sections)
    stats={}
    inclusive={}
    by_stage={}
    samples={}
    def minimum(db,key,free):
        row=db.setdefault(key,{"observations":0,"raw_available_min":free})
        row["observations"]+=1
        row["raw_available_min"]=min(row["raw_available_min"],free)
    for stage in STAGES:
        path=evidence/f"{stage}.samples.jsonl"
        if not path.exists():continue
        markers=iter(sections) if stage=="production" else iter(())
        next_event=next(markers,None)
        current="setup or packaging"
        keys=set()
        prior=None
        rowcount,maxgap,maxclockdiff=0,0.0,0.0
        for line in path.open():
            utc,mon,free,phase=json.loads(line)
            if prior:
                dt=(mon-prior[1])/1e9
                assert dt>0
                maxgap=max(maxgap,dt)
                maxclockdiff=max(maxclockdiff,abs((utc-prior[0])/1e9-dt))
            prior=(utc,mon)
            rowcount+=1
            while next_event and next_event[0]<=utc:
                _,key,action=next_event
                current=key if action=="starts" else (key.rpartition(" > ")[0] or "setup or packaging")
                next_event=next(markers,None)
            label=stage+" / "+(current if stage=="production" else phase)
            minimum(stats,label,free)
            if stage=="production":
                components=current.split(" > ")
                for depth in range(1,len(components)+1):
                    minimum(inclusive," > ".join(components[:depth]),free)
            keys.add(label)
        by_stage[stage]=min(stats[k]["raw_available_min"] for k in keys) if keys else None
        samples[stage]={"count":rowcount,"max_gap_s":maxgap,"max_wall_clock_discontinuity_s":maxclockdiff}
    qa=w/"trait-evidence"
    proofs={p.name:{"bytes":p.stat().st_size,"sha256":sha(p)} for p in sorted(qa.iterdir()) if p.is_file()}
    role=json.loads((qa/"role.json").read_bytes()) if (qa/"role.json").is_file() else {}
    src=json.loads((qa/"source.json").read_bytes()) if (qa/"source.json").is_file() else {}
    for key in ("source.json","role.json"):
        if (qa/key).exists(): (evidence/key).write_bytes((qa/key).read_bytes())
    steps={k:json.loads((evidence/f"{k}.json").read_bytes()) for k in STAGES if (evidence/f"{k}.json").exists()}
    complete=all(k in steps and steps[k].get("exit")==0 and steps[k]["cause"] is None for k in STAGES)
    finished={name for _,name,act in sections if act=="ended: OK"}
    if complete:
        assert all(any(k.startswith(f"Stage {n} (") and " > " not in k for k in finished) for n in (1,3,5))
        import runpy
        gate = runpy.run_path(str(HOOK.parent/"rc23-driver-link/gate.py"))
        gate["verify_sdk_receipts"](w, src, role, proofs)
        assert all(v["min_available"]>STOP and v["max_gap_s"]<=MAX_GAP for v in steps.values())
        assert all(v["adopted"]["no_children"] is True and v["adopted"]["grace_ns"]==CHILD_GRACE_NS
                   and all(code==status==0 for _,status,code in v["adopted"]["reaped"]) for v in steps.values())
    for stage,r in steps.items():
        assert r["raw_samples"]==samples[stage]["count"] and r["min_available"]==by_stage[stage]
        if complete:
            assert samples[stage]["max_gap_s"]<=MAX_GAP and samples[stage]["max_wall_clock_discontinuity_s"]<=.5
    observed=min((v for v in by_stage.values() if v is not None), default=None)
    put(evidence/"summary.json",{"eligible_sdk":False,"only_a_capacity_observation":True,
         "full_role_recipe_and_original_qa_completed":complete,"actual_workspace_fs":data["filesystem"],
         "minimum_observed_free_with_held_reserve":observed,"minimum_observed_plus_held":(observed+held["bytes"] if held and observed is not None else None),
         "physical_reserve_bytes":held["bytes"] if held else None,"sample_below_emergency_floor":observed is not None and observed<FLOOR,
         "sampled_max_net_workspace_consumption":(held["available_after"]-observed if held and observed is not None else None),
         "raw_free_minimum_per_command":by_stage,"per_phase":stats,"inclusive_release_section_samples":inclusive,"sample_verification":samples,"finished_release_sections":sorted(finished),
         "unobserved_release_sections":sorted({s for _,s,act in sections if act=="starts"}-set(inclusive)),
         "stage_evidence":steps,"qa_hashes":proofs,"free_after_releasing_held_blocks":space(w)})
    return complete


if __name__=="__main__":
    assert __debug__
    w,evidence=context()
    mode=sys.argv[1]
    if mode=="init":initialize(w,evidence)
    elif mode=="watch":watch(w,evidence,*sys.argv[2:])
    elif mode=="summarize":
        try:passed=score(w,evidence)
        finally:
            if evidence.is_dir() and (w/"trait-evidence").is_dir():evidence.rename(w/"trait-evidence/capacity")
        sys.exit(0 if passed else 1)
    else:raise ValueError(mode)
