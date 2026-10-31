"""Authenticate a GitHub original and independently reconstruct its native and counter receipt."""
import argparse
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import confirmation as c

BRANCH="charlie/qa-ruff-integration-f-confirmation-20261031"
PREFLIGHT="Reopen both eligible pilot originals"
LABEL="Confirm F whole-Cargo integration "
ARTIFACT="ruff-integration-f-confirmation-"
need=c.need

def encoded(v):
    return (json.dumps(v,sort_keys=True,separators=(",",":"))+"\n").encode()

def seal(path,data):
    if path.exists():
        need(path.read_bytes()==data,("original local receipt differs",str(path)));return
    with tempfile.NamedTemporaryFile(dir=path.parent) as t:
        t.write(data);t.flush();os.chmod(t.name,0o444)
        try:os.link(t.name,path)
        except FileExistsError:need(path.read_bytes()==data,"concurrent custody mismatch")

def query(args,path):
    return json.loads(subprocess.check_output([args.gh,"api",f"repos/{c.admission.REPO}/actions/{path}"],cwd=HERE))

def catalog(args):
    run=query(args,f"runs/{args.run}")
    need((run["id"],run["head_sha"],run["head_branch"],run["run_attempt"],run["event"],
          run["repository"]["full_name"],run["path"],run["display_title"])==
         (args.run,args.head,BRANCH,1,"workflow_dispatch",c.admission.REPO,".github/workflows/ci.yml",
          f"Twelve independent Ruff integration-test confirmations {args.head}"),"foreign/retried workflow")
    data=query(args,f"runs/{args.run}/attempts/1/jobs?per_page=100")
    jobs={j["name"]:j for j in data["jobs"]}
    expected={PREFLIGHT,*(LABEL+p for p in c.POSITIONS)}
    refused=(run["status"]=="completed" and run["conclusion"]!="success")
    need(data["total_count"]==len(jobs)==len({j["id"] for j in jobs.values()}) and set(jobs)<=expected and
         (set(jobs)==expected or refused) and all(j["head_sha"]==args.head and j["run_id"]==args.run for j in jobs.values()),
         "missing, extra or duplicate positions")
    data=query(args,f"runs/{args.run}/artifacts?per_page=100")
    artifacts={a["name"]:a for a in data["artifacts"]}
    need(data["total_count"]==len(artifacts)==len({a["id"] for a in artifacts.values()})<=12 and
         set(artifacts)<={ARTIFACT+p for p in c.POSITIONS},"substituted or repeated ZIP")
    for a in artifacts.values():
        need(a["workflow_run"]["id"]==args.run and a["workflow_run"]["head_sha"]==args.head and not a["expired"] and
             0<a["size_in_bytes"]<700*2**20 and c.re.fullmatch(r"sha256:[0-9a-f]{64}",a["digest"]),"unauthenticated original")
    return run,jobs,artifacts

def shape(z):
    members=z.infolist()
    need(len(members)==len(set(z.namelist()))<5000 and sum(i.file_size for i in members)<4*2**30 and
         all(not PurePosixPath(i.filename).is_absolute() and ".." not in PurePosixPath(i.filename).parts and
             not stat.S_ISLNK(i.external_attr>>16) for i in members),"unsafe or unbounded original ZIP")
    need(z.testzip() is None,"corrupt archived member")

def qualify(args,raw,job,a):
    need(raw.seek(0,2)==a["size_in_bytes"],"archive length")
    raw.seek(0);need(hashlib.file_digest(raw,"sha256").hexdigest()==a["digest"][7:],"archive SHA256")
    raw.seek(0)
    receipt={"run":args.run,"head":args.head,"position":args.position,"job":job["id"],"job_name":job["name"],
             "conclusion":job["conclusion"],"archive":{k:a[k] for k in ("name","id","size_in_bytes","digest")}}
    with zipfile.ZipFile(raw) as z:
        shape(z)
        if job["conclusion"]!="success":
            receipt["refusal"]={f:z.read(f).decode(errors="replace") for f in ("failure.txt","rejected.txt") if f in z.namelist()}
            return receipt
        names=set(z.namelist())
        need({"enrollment.json","complete.json","independent-confirmation.json"}<=names and
             not names.intersection({"failure.txt","rejected.txt"}),"missing or refused native proof")
        with tempfile.TemporaryDirectory(prefix="ohm-f-integration-readback-",dir=args.tmpdir) as td:
            tmp=Path(td);payload=tmp/"data";z.extractall(payload);out=tmp/"whole.json"
            env=os.environ|{"RUNNER_TEMP":td,"TMPDIR":td,"GIT_NO_LAZY_FETCH":"1","PYTHONDONTWRITEBYTECODE":"1"}
            with out.open("xb") as dest:
                subprocess.run([sys.executable,"-IB",HERE/"verify.py","worker",payload,args.calibrator,args.observers],
                               env=env,cwd=HERE,stdout=dest,check=True,timeout=1800)
            verified=json.loads(out.read_bytes())
            need(verified==json.loads(z.read("independent-confirmation.json")) and
                 (verified["run"],verified["head"],verified["position"])==(args.run,args.head,args.position),"independent worker differs")
            seal(args.out/f"worker-{args.position}.json",encoded(verified))
            receipt["worker_sha256"]=c.sha(encoded(verified))
            receipt["boot"]=verified["boot"]
            empty={}
            for arm in c.ARMS:
                for branch in ("A","B"):
                    prefix=f"clean/{arm}/{branch}/"
                    k=json.loads(z.read(prefix+"kernel-commits.json"))
                    inv=json.loads(gzip.decompress(z.read(prefix+"native-execs.json.gz")))
                    empty[f"{arm}/{branch}"]={"tasks":k["waited_tasks"],"image_installs":k["installed_images"],
                             "nonexecuting_uncertain_tasks":len(k["noninstalled_terminal_tasks"]),
                             "kernel_sha256":k["kernel_sha256"],"syscall_sha256":k["syscall_sha256"],
                             "rustc_count":len(inv["rustcs"]),"wild_outputs":len(inv["wild_processes"]),
                             "owners":json.loads(z.read(prefix+"physical-owners.json"))["owners"]}
            seal(args.out/f"empty-native-{args.position}.json",encoded(empty))
            receipt["empty_native_sha256"]=c.sha(encoded(empty))
    return receipt


def acquire(args,job,artifact):
    pos=args.position
    need(job["status"]=="completed","position is still running")
    if artifact is None:
        need(job["conclusion"]!="success","successful position without original")
        return {"head":args.head,"run":args.run,"position":pos,"job":job["id"],"job_name":job["name"],"conclusion":job["conclusion"],"archive":None}
    need(shutil.disk_usage(args.tmpdir).free>4*2**30+2*artifact["size_in_bytes"],"insufficient scratch for bounded readback")
    if args.original_directory:
        with (args.original_directory/f'{args.run}-{artifact["id"]}.zip').open("rb") as f:
            return qualify(args,f,job,artifact)
    if args.archive_store:
        store=args.archive_store.resolve(strict=True)
        need(store==args.archive_store.absolute() and store.stat().st_uid==os.getuid() and
             not stat.S_IMODE(store.stat().st_mode)&0o022,"unowned or writable-by-others original store")
        path=store/f'{args.run}-{artifact["id"]}.zip'
        # The lock covers download and the complete physical replay. A second caller
        # reuses the hash-qualified original and cannot extract concurrently here.
        with (store/"readback.lock").open("ab") as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            if not path.exists():
                need(shutil.disk_usage(store).free>16*2**30+artifact["size_in_bytes"],"16 GiB original-volume reserve")
                with tempfile.NamedTemporaryFile(dir=store) as f:
                    subprocess.run([args.gh,"api",f'repos/{c.admission.REPO}/actions/artifacts/{artifact["id"]}/zip'],
                                   cwd=HERE,stdout=f,check=True,timeout=900)
                    f.flush();need(f.tell()==artifact["size_in_bytes"],"download size");f.seek(0)
                    need(hashlib.file_digest(f,"sha256").hexdigest()==artifact["digest"][7:],"download SHA256")
                    os.chmod(f.name,0o444);os.link(f.name,path)
            need(not path.is_symlink() and stat.S_IMODE(path.stat().st_mode)==0o444,"original store path changed")
            with path.open("rb") as f:return qualify(args,f,job,artifact)
    with tempfile.TemporaryFile(dir=args.tmpdir) as f:
        subprocess.run([args.gh,"api",f'repos/{c.admission.REPO}/actions/artifacts/{artifact["id"]}/zip'],cwd=HERE,
                       stdout=f,check=True,timeout=900)
        return qualify(args,f,job,artifact)

def check_result(workers,receipts,terminal,run,head):
    need(terminal["run"]["status"]=="completed" and terminal["run"]["conclusion"]=="success" and
         terminal["run"]["id"]==run and terminal["run"]["head_sha"]==head and
         terminal["jobs"][PREFLIGHT]["conclusion"]=="success" and set(workers)==set(receipts)==set(c.POSITIONS),
         "entire enrollment must be terminal, including its preflight")
    for p in c.POSITIONS:
        r,w=receipts[p],workers[p]
        j=terminal["jobs"][LABEL+p];a=terminal["artifacts"][ARTIFACT+p]
        need(r["conclusion"]==j["conclusion"]=="success" and
             (r["run"],r["head"],r["position"],r["job"],r["job_name"],r["boot"])==(run,head,p,j["id"],j["name"],w["boot"]) and
             r["archive"]=={k:a[k] for k in ("name","id","size_in_bytes","digest")} and
             r["worker_sha256"]==c.sha(encoded(w)),"external digest/position receipt disagrees with its original")
    return c.summarize(workers,run,head)


if __name__=="__main__":
    opt=argparse.ArgumentParser(description=__doc__)
    opt.add_argument("--run",type=int,required=True);opt.add_argument("--head",required=True)
    opt.add_argument("--gh",default="gh-auto");opt.add_argument("--out",type=Path,required=True)
    opt.add_argument("--tmpdir",type=Path,default=Path(tempfile.gettempdir()))
    stored=opt.add_mutually_exclusive_group();stored.add_argument("--original-directory",type=Path);stored.add_argument("--archive-store",type=Path)
    opt.add_argument("--calibrator",type=Path);opt.add_argument("--observers",type=Path)
    opt.add_argument("--position",choices=c.POSITIONS);args=opt.parse_args()
    need(subprocess.check_output(["git","-C",HERE,"rev-parse","HEAD"],text=True).strip()==args.head and
         not subprocess.check_output(["git","-C",HERE,"status","--porcelain","--",HERE]),"reader checkout/source changed")
    args.out.mkdir(parents=True,exist_ok=True)
    run,jobs,artifacts=catalog(args)
    if args.position:
        need(args.calibrator and args.observers,"both source-bound checker checkouts required")
        if LABEL+args.position in jobs:
            receipt=acquire(args,jobs[LABEL+args.position],artifacts.get(ARTIFACT+args.position))
        else:
            need(run["status"]=="completed" and run["conclusion"]!="success" and ARTIFACT+args.position not in artifacts,"missing native worker")
            receipt={"run":args.run,"head":args.head,"position":args.position,"job":None,"conclusion":"not started","archive":None}
        seal(args.out/f"receipt-{args.position}.json",encoded(receipt))
        print(args.position,receipt["conclusion"],c.sha(encoded(receipt)))
    else:
        need(run["status"]=="completed" and all(x["status"]=="completed" for x in jobs.values()),"wait for final catalog")
        seal(args.out/"terminal-catalog.json",encoded({"run":run,"jobs":jobs,"artifacts":artifacts}))
        print("Terminal",run["conclusion"],len(artifacts),"original archives")
