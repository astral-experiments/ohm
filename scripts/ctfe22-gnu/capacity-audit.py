"""Validate the frozen capacity decision and both machines' independent native observations."""
import hashlib,json,os,re,runpy,sys
from pathlib import Path
H=Path(__file__).resolve().parent;G=1<<30
FORMULA="aa2f7c16ae424672bac26fcd2131f4b4c46a7babf7364f6acb255b46b3722453";STAGES=("materialize","prerequisites","bolt-tools","wild","production","native-qa")
def need(v,m):
    if not v:raise ValueError(m)
def load(p):return json.loads(p.read_bytes())
def sha(p):
    with p.open("rb")as f:return hashlib.file_digest(f,"sha256").hexdigest()
def authority(path,checksum,formula):
    need(__debug__ and sha(path)==checksum and sha(formula)==FORMULA,"authority bytes changed")
    a=load(path);d=a["decision"];need(a["kind"]=="verified-complete-pilot" and a["pilot_run"]==41369516093 and a["pilot_head"]=="4b08157523274b9a7546fde78ce92a0e22c9c786" and a["pilot_job"]==125036771829 and a["pilot_attempt"]==1 and a["selector_sha256"]==FORMULA and a["receiver_sha256"]=="2b530072dff834d9b3372d80c73b2717b232f3e1d2e1d39e7608e8012f3674f9","genuine successful registered pilot only")
    need(type(a["artifact_id"])is int and a["artifact_id"]>0 and re.fullmatch("[0-9a-f]{64}",a["artifact_sha256"]) and a["artifact_sha256"]==a["pilot_evidence_sha256"]["capacity-only.zip"],"service authority")
    keys={"terminal-run.json","terminal-jobs.json","terminal-artifacts.json","terminal-artifact.json","capacity-only.zip","independent-capacity.json"}
    need(set(a["pilot_evidence_sha256"])==keys and all(re.fullmatch("[0-9a-f]{64}",v)for v in a["pilot_evidence_sha256"].values())and re.fullmatch("[0-9a-f]{64}",a.get("fresh_service_receipt_sha256","")),"missing independent receipt")
    initial,peak,floor=[d[k] for k in ("pilot_initial_bytes","pilot_highwater_bytes","production_admission_bytes")]
    need(all(type(x)is int for x in(initial,peak,floor)) and d["fit_observed_machine"] is True and d["eligible_as_compiler_or_performance_evidence"] is False and initial>=floor==runpy.run_path(str(formula))["bytes_required"](initial,peak),"rejected presealed formula")
    need(a["artifact_id"]==13110730605 and a["artifact_sha256"]=="2f2b1c3a0faf5f69ccfb2eec91f7a338572eabd0eb9a8d5da502a76b93b1e9c0" and a["two_reader_qualification_sha256"]=="b2e0213943211ec676fb1df450568548c7f07145cdefeecef9a887c170674d30" and a["pilot_worker_sha256"]=="cd569f839bebccd17a1048cb85c3a150157038357ed46ab0c43a70ff6ba54de3" and a["original_selector_sha256"]=="3e1b013dd4bec7f27e14781a3fce8c1a582c0b8d54633aab4b315a6bedd1c95e" and floor==250*G,"wrong physical pilot or precommitted decision")
    return floor
def samples(path,stage):
    count=0;prior=None;low=None;gap=0;discontinuity=0
    for line in path.open():
        utc,mon,free,phase=json.loads(line);need(type(utc)is type(mon)is type(free)is int and free>48*G and phase in ({"distribution-and-install","unit","run-make","installed-original"} if stage=="native-qa" else {stage}),"wrong phase or sampled pressure")
        if prior:
            dt=(mon-prior[1])/1e9;need(0<dt<=2,"sampling gap");gap=max(gap,dt);discontinuity=max(discontinuity,abs((utc-prior[0])/1e9-dt))
            need(discontinuity<=.5,"UTC discontinuity")
            if free<96*G:need(free-max(prior[2]-free,0)/dt*2>48*G,"downward free-space pressure")
        prior=(utc,mon,free);low=free if low is None else min(low,free);count+=1
    need(count>0,"empty journal");return count,low,gap,discontinuity
def mounts(held, intake):
    keys={"device","mount_id","kind","statvfs_fsid","bytes_total","fs_block"}
    mount_fields=keys-{"device"}
    workspace,temp=intake["filesystem"],intake["runner_temp_fs"]
    file,parent=held["file_filesystem"],held["parent_filesystem"]
    for obj in (workspace,temp,file,parent):
        assert set(obj)==keys and type(obj["statvfs_fsid"]) is int and type(obj["device"]) is int
        assert type(obj["mount_id"]) is int and obj["mount_id"]>0 and obj["kind"] and obj["bytes_total"]>0 and obj["fs_block"]>0
    assert held["device"]==file["device"] and workspace==parent and workspace["device"]==temp["device"]
    assert all(file[k]==workspace[k]==temp[k] for k in mount_fields)
    assert held["bytes"]==16*(1<<30) and held["allocated_bytes"]>=held["bytes"] and held["inode"]>0

def child_receipt(receipt, raw):
    a=receipt["adopted"]
    assert receipt["cause"] is None and receipt["exit"]==0 and a["no_children"] is True
    assert a["grace_ns"]==5_000_000_000 and type(a["samples"]) is int and 0<a["samples"]<=len(raw)
    assert a["start_ns"]==raw[-a["samples"]][1] and a["last_sample_ns"]==raw[-1][1]
    assert a["last_sample_ns"]-a["start_ns"]<=a["grace_ns"]+2_000_000_000
    assert all(type(pid) is int and pid>0 and status==code==0 for pid,status,code in a["reaped"])
    assert len(a["initial"]["first_32"])<=min(32,a["initial"]["direct_count_at_read"])
    assert all(type(pid) is int and pid>0 and isinstance(state,str) and len(state)==1 for pid,state in a["initial"]["first_32"])

def role(qa,who,floor,authority_sha,env,arm):
    c=qa/"capacity";data=load(c/"intake.json");summary=load(c/"summary.json");held=load(c/"reserve.json")
    need(data["role"]==who and data["admission_sha256"]==authority_sha and data["initial_requirement"]==floor and data["initial_available"]>=floor and data["physical_reserve"]==16*G and data["raw_free_stop"]==48*G and data["raw_free_floor"]==32*G and data["head"]==env["GITHUB_SHA"] and data["run"]==int(env["GITHUB_RUN_ID"]) and data["attempt"]==int(env["GITHUB_RUN_ATTEMPT"])==1,"arm/run/initial admission")
    need(data["filesystem"]==summary["actual_workspace_fs"] and data["filesystem"]["device"]==data["runner_temp_fs"]["device"] and held["bytes"]==16*G and held["allocated_bytes"]>=16*G and held["available_before"]-held["available_after"]>=16*G-(8<<20),"physical reserve did not hold")
    need(summary["full_role_recipe_and_original_qa_completed"] is True and summary["eligible_sdk"] is False and summary["only_a_capacity_observation"] is True and summary["sample_below_emergency_floor"] is False and summary["physical_reserve_bytes"]==16*G and set(summary["sample_verification"])==set(summary["raw_free_minimum_per_command"])==set(STAGES),"incomplete role summary")
    mounts(held,data)
    minima={}
    for stage in STAGES:
        n,low,gap,dis=samples(c/(stage+".samples.jsonl"),stage);r=load(c/(stage+".json"));reported=summary["sample_verification"][stage]
        need(r["stage"]==stage and r["raw_samples"]==reported["count"]==n and r["min_available"]==summary["raw_free_minimum_per_command"][stage]==low and 0<=r["max_gap_s"]<=2 and reported["max_gap_s"]==gap and reported["max_wall_clock_discontinuity_s"]==dis and r["exit"]==0 and r["cause"] is None and "termination"not in r,"command failed or raw journal mismatch")
        child_receipt(r,[json.loads(line) for line in (c/(stage+".samples.jsonl")).read_text().splitlines()])
        minima[stage]=low
    minimum=min(minima.values());need(minimum==summary["minimum_observed_free_with_held_reserve"] and minimum+16*G==summary["minimum_observed_plus_held"] and held["available_after"]-minimum==summary["sampled_max_net_workspace_consumption"],"incorrect same-filesystem extrema")
    native=load(qa/"role.json");source=load(qa/"source.json")
    need(data["runner"].startswith("nsc-runner-") and source["reviewed_head"]==env["GITHUB_SHA"] and source["role"]==native["role"]==who and source["source"]==arm and [native[k]for k in ("source_commit","source_tree","epoch")]==[arm[k]for k in ("commit","tree","epoch")],"wrong stock/trait source on physical machine")
    for n in ("source.json","role.json"):need(sha(c/n)==sha(qa/n),"capacity/native SDK receipt mismatch")
    return {"role":who,"runner":data["runner"],"initial_available":data["initial_available"],"per_stage_minimum":minima,"summary_sha256":sha(c/"summary.json"),"role_sha256":sha(qa/"role.json")}
def cross(checksum):
    e=os.environ;ref="refs/heads/charlie/codex-ctfe22-standard-20988";repo="astral-experiments/ohm"
    need(e["GITHUB_JOB"]=="pair" and e["GITHUB_ACTIONS"]=="true" and e["GITHUB_EVENT_NAME"]=="workflow_dispatch" and e["GITHUB_REPOSITORY"]==repo and e["GITHUB_REF"]==ref and e["GITHUB_SHA"]==e["REVIEWED_HEAD"]==e["GITHUB_WORKFLOW_SHA"] and e["GITHUB_WORKFLOW_REF"]==repo+"/.github/workflows/ci.yml@"+ref,"wrong parity event")
    floor=authority(H/"capacity-admission.json",checksum,H/"capacity-selector.py");w=Path(e["GITHUB_WORKSPACE"]);arms=load(H/"arms.json")["arms"]
    result={name:role(w/"intake"/(name+"-qa"),name,floor,checksum,e,arms[name]) for name in arms}
    need(len(result)==2 and len({r["runner"]for r in result.values()})==2,"separate admitted physical jobs")
    with(w/"capacity-pair.json").open("x")as f:json.dump({"scope":"physical workspace capacity only","head":e["GITHUB_SHA"],"run":int(e["GITHUB_RUN_ID"]),"authority_sha256":checksum,"same_initial_admission":floor,"roles":result},f,indent=2,sort_keys=True)
if __name__=="__main__":
    need(__debug__ and len(sys.argv)==2,"expected authenticated decision digest");cross(sys.argv[1])
