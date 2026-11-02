"""Replay both capacity histories using the exact producer reader and original raw journals."""
import shutil
import material as m

HEAD="cddb036d81e4313a8e422171f39f0840b44110db"
RID=41374825846
IDS={"stock_ctfe318":125052685479,"fa7a_stack_ctfe318":125052685273}
PAIR="Qualify both cache migration directions"
FILES={"arms.json":"4ad3c2fd4072b15e0aa559363cc8d9196ffd74b78db71bfc6d68ebce2f589880",
    "capacity-audit.py":"4b4290755011e5c56f5f77456dc21f12e63d87b0ecfc412ed58eaf4efa20da6b",
    "capacity-selector.py":"aa2f7c16ae424672bac26fcd2131f4b4c46a7babf7364f6acb255b46b3722453",
    "capacity-admission.json":"52779265edb1486bceb9f6abf0c7a24dfc0f234caea4a067653b0eceb514772b"}
STAGES=("materialize","prerequisites","bolt-tools","wild","production","native-qa")
BUILD_STEPS=["Admit this production workspace and allocate its physical emergency reserve","Reconstruct and verify the exact compiler source",
    "Install native GNU bootstrap prerequisites","Install pinned LLVM BOLT tools","Prepare pinned Wild linker","Build the production PGO and BOLT distribution",
    "Verify the production SDK and exercise the original regression","Validate this role's complete capacity evidence before its SDK upload",
    "Upload the native-qualified SDK","Retain role identity, release build and native diagnostics","Bind successful role inputs to the artifact service receipts"]
PAIR_STEPS=["Independently replay the two raw capacity histories","Verify the archives and exercise bidirectional cache rejection",
    "Bind the two capacity proofs to the native pair qualification","Retain paired source and cache qualification"]
def finished_steps(job,names):
    for n in names:
        one,=[s for s in job["steps"]if s["name"]==n]
        m.guard(one["status"]=="completed"and one["conclusion"]=="success","producer stage not successful: "+n)
def jobs(service):
    m.guard(len(service)==len({j["name"]for j in service})==3 and
        all(j["run_id"]==RID and j["head_sha"]==HEAD and j["status"]=="completed"and j["conclusion"]=="success"and j["run_attempt"]==1 for j in service),"producer job membership")
    by_name={j["name"]:j for j in service};result={}
    for role,ident in IDS.items():
        j=by_name["Production GNU SDK ("+role+")"]
        m.guard(j["id"]==ident and j["labels"]==["namespace-profile-ubuntu-24-04-16"]and type(j["runner_id"])is int and j["runner_id"]>0 and j["runner_name"].startswith("nsc-runner-"),"wrong role or real runner")
        finished_steps(j,BUILD_STEPS);result[role]={"id":ident,"runner_id":j["runner_id"],"runner":j["runner_name"]}
    m.guard(all(len({v[k]for v in result.values()})==2 for k in ("id","runner_id","runner")),"the build roles must use separate machines")
    pair=by_name[PAIR];m.guard(pair["labels"]==["ubuntu-24.04"]and type(pair["id"])is int and pair["id"]>0 and pair["id"]not in IDS.values(),"unexpected pair job")
    finished_steps(pair,PAIR_STEPS)
    return result
def code(src):
    for n,sha in FILES.items():
        p=src/n;m.guard(p.is_file()and not p.is_symlink()and m.filesha(p)==sha,"capacity authority, formula, reader or arms changed")
    return m.load("producer_resource_audit",src/"capacity-audit.py")
def copy(src,dst):
    m.guard(src.is_file() and not src.is_symlink() and not dst.exists() and 0<src.stat().st_size<=24<<20,"missing or excessive capacity record")
    dst.parent.mkdir(exist_ok=True,parents=True);shutil.copyfile(src,dst)
def capture(proof,builder,unpacked):
    path=proof/"producer-capacity";path.mkdir()
    src=builder/"scripts/ctfe22-gnu"
    for n in FILES:copy(src/n,path/"authority"/n)
    copy(unpacked["ctfe22-gnu-pair-qa-attempt-1"]/"capacity-admission.json",path/"paired-capacity.json")
    for role in IDS:
        qa=unpacked[f"ctfe22-gnu-build-{role}-attempt-1"]
        for n in ["source.json","role.json"]:copy(qa/n,path/role/n)
        for n in ["intake.json","summary.json","reserve.json","role.json","source.json",*(a+s for a in STAGES for s in (".json",".samples.jsonl"))]:
            copy(qa/"capacity"/n,path/role/"capacity"/n)
    m.save(path/"replay.json",replay(proof,prior=False))
def replay(proof,prior=True):
    path=proof/"producer-capacity";src=path/"authority";reader=code(src)
    authority=FILES["capacity-admission.json"];floor=reader.authority(src/"capacity-admission.json",authority,src/"capacity-selector.py")
    arms=m.read(src/"arms.json")["arms"];hosts=jobs(m.read(proof/"jobs.json")["jobs"]);native=m.read(proof/"pair-passed.json")["roles"]
    m.guard(set(arms)==set(IDS)and floor==250<<30,"wrong registered source pair or capacity floor")
    rows={}
    for role,arm in arms.items():
        d=path/role;origin=proof/"role-material"/role
        m.guard(all(m.filesha(d/(n+".json"))==m.filesha(origin/(n+".json"))and m.read(d/(n+".json"))==native[role][n] for n in ("role","source")),"capacity vs actual native producer")
        r=reader.role(d,role,floor,authority,{"GITHUB_SHA":HEAD,"GITHUB_RUN_ID":str(RID),"GITHUB_RUN_ATTEMPT":"1"},arm)
        m.guard(r["runner"]==hosts[role]["runner"],"capacity receipt on a different physical machine")
        rows[role]=r
    exact={"scope":"physical workspace capacity only","head":HEAD,"run":RID,"authority_sha256":authority,"same_initial_admission":floor,"roles":rows}
    m.guard(exact==m.read(path/"paired-capacity.json"),"service pair differs from the independenty replayed raw role journals")
    result={"raw_resource_journals":len(rows)*len(STAGES),"producer_jobs":hosts,"producer_pair":m.filesha(path/"paired-capacity.json"),"raw_replay":exact}
    if prior:m.guard(result==m.read(path/"replay.json"),"archived independent resource readback")
    return result
