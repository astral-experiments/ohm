"""Read-only authenticated GitHub input for the private, source-built P/C cohort."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent
STAGE=HERE
sys.path.insert(0,str(HERE))
import capsule

REPO = "astral-experiments/ohm"
BRANCH = "charlie/qa-ruff-workspace-link-census-20261102"
BUILD = 41425541148
BUILD_QA = "f4d11670f8eca799dbaaad35b456a5371954248c"
CONFIRM = "d09957ddf8f4965d902119ca415c18bc06803cd2416c4b19d4fa1701e9b4d3c9"
need, sha, save = capsule.need, capsule.sha, capsule.save
fetch = lambda p: json.loads(subprocess.check_output(["gh","api",f"repos/{REPO}/actions/"+p]))


def run_identity(run_id, head, completed=True):
    run=fetch(f"runs/{run_id}")
    need(run["id"]==run_id and run["run_attempt"]==1 and run["head_sha"]==head and
         run["repository"]["full_name"]==REPO and run["event"]=="workflow_dispatch" and
         run["head_branch"]==BRANCH and (not completed or run["conclusion"]=="success"),"wrong immutable workflow or unsuccessful source")
    return run


def acquire(row, dst, bound, *, floor=15 << 30):
    size=row["size_in_bytes"]
    need(0 < size <= bound and not row["expired"] and re.fullmatch(r"sha256:[0-9a-f]{64}",row["digest"]) and
         shutil.disk_usage(dst.parent).free >= floor+size,"unavailable or oversize artifact")
    with dst.open("xb") as f:
        subprocess.run(["gh","api",f"repos/{REPO}/actions/artifacts/{row['id']}/zip"],stdout=f,check=True)
    need(dst.stat().st_size==size and "sha256:"+sha(dst)==row["digest"],"transport failed physical SHA")
    return {k:row[k] for k in ("id","name","digest","size_in_bytes")}


def artifact(rows,name):
    row,=[r for r in rows if r["name"]==name]
    return row


def unzip_member(z,name,dst,limit):
    info=z.getinfo(name)
    need(info.file_size<=limit and info.file_size>0 and not info.is_dir(),"invalid ZIP payload size")
    with z.open(info) as src, dst.open("xb") as out:
        shutil.copyfileobj(src,out,1 << 20)
    need(dst.stat().st_size==info.file_size,"incomplete ZIP payload")


def unpack_tar(src, root):
    seen=set()
    objects=0
    total=0
    with subprocess.Popen(["zstd","-qd","-c",src],stdout=subprocess.PIPE) as pipe:
        with tarfile.open(fileobj=pipe.stdout,mode="r|") as payload:
            for entry in payload:
                name=entry.name.rstrip("/")
                need(name not in seen and len(seen)<420,"duplicate or excess ELF capsule member")
                seen.add(name)
                path=root/name
                if name in ("capsule","capsule/objects"):
                    need(entry.isdir(),"not a genuine capsule directory")
                    path.mkdir()
                    continue
                obj=re.fullmatch(r"capsule/objects/[0-9a-f]{64}",name)
                need((obj or name in ("capsule/qualified.json","capsule/P.json","capsule/C.json")) and
                     entry.isfile() and (entry.mode&~0o777)==0 and 0<entry.size<=700*(1<<20),"unregistered archive entry")
                if obj:
                    objects+=1
                total+=entry.size
                need(total<=3500*(1<<20),"oversize real SDK transport")
                with payload.extractfile(entry) as stream,path.open("xb") as out:
                    shutil.copyfileobj(stream,out,1<<20)
                need(path.stat().st_size==entry.size,"incomplete compiler member")
                path.chmod(entry.mode&0o777)
                os.utime(path,ns=(0,0))
        pipe.stdout.read()
        need(pipe.wait()==0,"failed complete zstd decompression")
    need(objects>0,"empty compiler transport")
    return capsule.admit(root/"capsule")


SDK_ARTIFACT=(13131394450,185555780,"sha256:11368598860f3621dda6d84e87df7b84acaf4b44920e6387ace3be412c78b45a")
SOURCE_ARTIFACT=(13131254799,46047,"sha256:619dc244583dbc19852e6810a2c7056b4758450bc4c8628faadb09ba9c78810c")
ARCHIVE="ce40a93214d71775636ec0fccf5d629f63ef282e070d49bb4a8562a58e8d43a1"


def factory(root, parked):
    need(sha(HERE/"confirmation.json")==CONFIRM,"the original physical schedule changed")
    root.mkdir()
    logs=root/"logs"
    logs.mkdir()
    run=run_identity(BUILD,BUILD_QA,completed=False)
    need(run["status"]=="completed" and run["conclusion"]=="failure","the original build must retain its actual refusal")
    jobs=fetch(f"runs/{BUILD}/jobs?per_page=100")["jobs"]
    job,=[j for j in jobs if j["name"]=="ldv-physical-stage"]
    actual={j["name"]:j["conclusion"] for j in job["steps"]}
    need(all(actual.get(step)=="success" for step in ("Admit this reviewed nonrelease worker",
        "Build the isolated stage1 pair and verify ordinary Cargo", "Package authenticated content-addressed compiler objects",
        "Retain the matched compiler capsule","Retain source, tool and smoke evidence")) and
        actual.get("Observe the physical compiler passes in the two actual frozen drivers")=="failure",
        "cannot separately attribute the true construction and the observability refusal")
    rows=fetch(f"runs/{BUILD}/artifacts?per_page=100")["artifacts"]
    sdk=artifact(rows,"ohm-ldv-physical-stage1"); receipts=artifact(rows,"ohm-ldv-physical-stage1-receipts")
    for row,pin in ((sdk,SDK_ARTIFACT),(receipts,SOURCE_ARTIFACT)):
        need((row["id"],row["size_in_bytes"],row["digest"])==pin,"not the originally sealed source products")
    zr=root/"source-receipts.zip"
    report=acquire(receipts,zr,1<<20)
    with zipfile.ZipFile(zr) as z:
        need(len(z.namelist())==len(set(z.namelist())) and z.testzip() is None,"invalid patch-source receipts")
        for f in ("archive.sha256","accepted.json","source.json","smoke.json","ldv-driver-P.json","ldv-driver-C.json","P.json","C.json"):
            unzip_member(z,f,logs/f,16<<20)
    original=read(logs/"accepted.json")
    smoke=read(logs/"smoke.json")["arms"]
    need(smoke["normal"]["versions"]==smoke["defer"]["versions"] and len(smoke)==2 and
         all(v["invalid"]=="E0308" and len(v["qualified_codegen"])==4 and v["repair_test"] for v in smoke.values()),
         "unqualified authentic initial smoke")
    archive=root/"source-capsule.zip"
    summary=acquire(sdk,archive,512<<20)
    tar=root/"matched-stage.tar.zst"
    with zipfile.ZipFile(archive) as z:
        need(z.namelist()==[tar.name],"additional compiler artifact member")
        unzip_member(z,tar.name,tar,512<<20)
    need(sha(tar)==ARCHIVE and (logs/"archive.sha256").read_text()==ARCHIVE+"  matched-stage.tar.zst\n",
         "different physical tar")
    specs=unpack_tar(tar,root)
    need(original==read(root/"capsule/qualified.json") and original["source_sha256"]==sha(logs/"source.json"),
         "different original four-source readback")
    for role in specs:
        need(sha(root/"capsule"/(role+".json"))==sha(logs/(role+".json"))==original["manifests"][role],"different source-cap target inventory")
    capsule.reopen(root/"capsule",root/parked)
    save(logs/"original-source.json",{"build":BUILD,"qa":BUILD_QA,"artifacts":[summary,report],
         "archive":ARCHIVE,"source":original,"smoke_sha":sha(logs/"smoke.json"),"original_failed_step":"Observe the physical compiler passes in the two actual frozen drivers"})


def read(path):
    return json.loads(path.read_bytes())


if __name__=="__main__":
    root=Path(sys.argv[1])
    factory(root,"reopened")
    import physical
    physical.contact(root)
