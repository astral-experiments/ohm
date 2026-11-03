"""Bind each hardware pair series to a real new Actions job and the prior calibrated machine."""
from common21577 import *
import uuid
from zipfile import ZipFile
from media import Transport
REPO=PLAN["repo"]; BRANCH=PLAN["branch"]
def identity():
    e=os.environ;w=Path(e["GITHUB_WORKSPACE"]).resolve();tmp=Path(e["RUNNER_TEMP"]).resolve()
    assert __debug__ and e["GITHUB_ACTIONS"]=="true" and e["GITHUB_REPOSITORY"]==REPO and e["GITHUB_REPOSITORY_ID"]==str(PLAN["repo_id"])
    assert e["GITHUB_EVENT_NAME"]=="workflow_dispatch" and e["GITHUB_REF"]=="refs/heads/"+BRANCH and e["GITHUB_RUN_ATTEMPT"]=="1"
    head=e["REVIEWED_HEAD"];assert head==e["GITHUB_SHA"] and subprocess.check_output(["git","-C",w/"coordinator","rev-parse","HEAD"],text=True).strip()==head
    assert sha(HERE/"protocol.json")==e["PROTOCOL"] and e["SERIES"] in PLAN["orders"]
    return w,tmp,head
def service(run,head):
    prefix=f"repos/{REPO}/actions/runs/{run}";record=Transport.gh_json("api",prefix);jobs=Transport.gh_json("api",prefix+"/jobs?per_page=100")
    assert record["id"]==run and record["head_sha"]==head and record["head_branch"]==BRANCH and record["run_attempt"]==1 and record["event"]=="workflow_dispatch"
    assert record["path"]==".github/workflows/ci.yml" and record["repository"]["id"]==record["head_repository"]["id"]==PLAN["repo_id"] and record["repository"]["private"]
    assert record["actor"]["login"]==record["triggering_actor"]["login"]=="charliermarsh" and jobs["total_count"]==len(jobs["jobs"])==1
    job,=jobs["jobs"];assert job["head_sha"]==head and job["run_id"]==run and job["run_attempt"]==1 and job["runner_id"]>0 and job["runner_name"]
    return record,job
def accept_prior(label,prior):
    assert label in PLAN["orders"] and isinstance(prior,list)
    assert len(prior)==(label=="independent")
    if prior:assert set(prior[0])=={"run","id","job","sha256"} and len(prior[0]["sha256"])==64
def original(rec,head,dest):
    run,job=service(rec["run"],head)
    assert job["id"]==rec["job"]
    a=Transport.gh_json("api",f"repos/{REPO}/actions/artifacts/{rec['id']}")
    assert a["id"]==rec["id"] and a["name"]=="uv-21577-first-boot" and not a["expired"] and a["digest"]=="sha256:"+rec["sha256"]
    assert 0<a["size_in_bytes"]<65536 and a["workflow_run"]["id"]==run["id"] and a["workflow_run"]["head_sha"]==head
    assert a["workflow_run"]["repository_id"]==a["workflow_run"]["head_repository_id"]==PLAN["repo_id"]
    Transport.gh_bytes(f"repos/{REPO}/actions/artifacts/{rec['id']}/zip",dest,a["size_in_bytes"],rec["sha256"])
    with ZipFile(dest) as z:
        assert z.namelist()==["boot-attestation.json"]
        raw=z.read("boot-attestation.json");b=json.loads(raw)
    assert b["run"]==run["id"] and b["job"]==job["id"] and b["runner_id"]==job["runner_id"] and b["runner_name"]==job["runner_name"]
    assert b["series"]=="first" and b["head"]==head and b["protocol"]==sha(HERE/"protocol.json")
    assert all(len(b[n])==64 for n in ("inherited","threads","blocking")) and str(uuid.UUID(b["boot"]))==b["boot"]
    return b
def start(out,tmp,head):
    label=os.environ["SERIES"];prior=json.loads(os.environ["PRIOR"]);accept_prior(label,prior)
    history=read(HERE/"prior-hosts.json");assert PLAN["exclusion"]==sha(HERE/"prior-hosts.json")
    boots=set(history["boot_uuids"]);ids=set(history["runner_ids"]);names=set(history["runner_names"]);actual=int(os.environ["GITHUB_RUN_ID"])
    listing=Transport.gh_json("api",f"repos/{REPO}/actions/runs?branch={BRANCH}&event=workflow_dispatch&head_sha={head}&per_page=100")
    assert listing["total_count"]==len(listing["workflow_runs"]) and {x["id"] for x in listing["workflow_runs"] if x["id"]<=actual}=={actual,*[p["run"]for p in prior]}
    for item in prior:
        b=original(item,head,tmp/"prior-calibrated-boot.zip")
        assert b["boot"] not in boots and b["runner_id"]not in ids and b["runner_name"]not in names and set(b["excluded"])==boots
        boots.add(b["boot"]);ids.add(b["runner_id"]);names.add(b["runner_name"])
    r,j=service(actual,head);boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    assert str(uuid.UUID(boot))==boot and boot not in boots and j["runner_id"] not in ids and j["runner_name"] not in names and j["runner_name"]==os.environ["RUNNER_NAME"]
    save(out/"official-start.json",r);save(out/"official-job.json",j)
    libc=subprocess.check_output(["getconf","GNU_LIBC_VERSION"],text=True).strip();loader=Path("/lib64/ld-linux-x86-64.so.2").resolve()
    assert platform_x86() and libc.startswith("glibc 2.39") and loader.is_file()
    save(out/"placement.json",{"run":actual,"job":j["id"],"runner_id":j["runner_id"],"runner_name":j["runner_name"],"boot":boot,"head":head,"series":label,"prior_calibrated":prior,"excluded":sorted(boots),"excluded_ids":sorted(ids),"excluded_names":sorted(names),"protocol":sha(HERE/"protocol.json"),"loader":{"file":str(loader),"sha256":sha(loader),"glibc":libc,"notes":subprocess.check_output(["readelf","-n",loader],text=True)},"cpuinfo":Path("/proc/cpuinfo").read_text().split("\n\n")[0]})
def platform_x86():
    return os.uname().machine=="x86_64"
def current(out):
    _,_,head=identity();d=read(out/"placement.json");assert d["head"]==head and d["run"]==int(os.environ["GITHUB_RUN_ID"]) and d["series"]==os.environ["SERIES"] and d["boot"]==Path("/proc/sys/kernel/random/boot_id").read_text().strip() and d["boot"]not in d["excluded"];return d
