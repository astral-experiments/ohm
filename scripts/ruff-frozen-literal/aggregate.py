"""Authenticate all preregistered workflow runs before opening the physical per-rank results."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import read as source
import reopen_fixed as fixed
from confirmation_plan import registration
need=source.need
REPO="repos/astral-experiments/ohm/"

def write(path,value):
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n")

def api(gh,path):
    return json.loads(subprocess.check_output([gh,"api",REPO+path]))

def intake(gh,slot,run,head):
    label=f"Ruff literal confirmation {slot} {head}"
    info=api(gh,f"actions/runs/{run}")
    jobs=api(gh,f"actions/runs/{run}/attempts/1/jobs?per_page=100")
    artifacts=api(gh,f"actions/runs/{run}/artifacts?per_page=100")
    need(info["id"]==run and info["display_title"]==label and info["event"]=="workflow_dispatch" and info["run_attempt"]==1 and info["head_sha"]==head and info["head_branch"]==source.REG["branch"] and info["status"]=="completed","missing terminal registered attempt")
    job,=jobs["jobs"];artifact,=artifacts["artifacts"]
    need(jobs["total_count"]==artifacts["total_count"]==1 and job["name"]=="Ruff literal edit and parser control" and job["run_id"]==run and job["runner_id"]>0 and job["status"]=="completed","different physical worker")
    need(artifact["name"]==f"ruff-frozen-literal-pilot-{run}" and not artifact["expired"] and artifact["workflow_run"]["id"]==run and artifact["workflow_run"]["head_sha"]==head and 0<artifact["size_in_bytes"]<600<<20 and artifact["digest"].startswith("sha256:"),"wrong original")
    return dict(rank=slot,run=run,head=head,status=info["conclusion"],job=job["id"],job_status=job["conclusion"],runner=job["runner_name"],runner_id=job["runner_id"],artifact=artifact["id"],bytes=artifact["size_in_bytes"],sha256=artifact["digest"].split(":")[1],url=info["html_url"])

def physical(gh,out,reg):
    original=out/"original.zip"
    if not original.exists():
        with tempfile.NamedTemporaryFile(prefix="download-",suffix=".part",dir=out,delete=False)as outp:
            part=Path(outp.name)
            subprocess.run([gh,"api",REPO+f"actions/artifacts/{reg['artifact']}/zip"],stdout=outp,check=True)
        with part.open("rb")as inp:
            need(hashlib.file_digest(inp,"sha256").hexdigest()==reg["sha256"] and part.stat().st_size==reg["bytes"],"invalid download")
        part.rename(original)
    with original.open("rb")as inp:need(hashlib.file_digest(inp,"sha256").hexdigest()==reg["sha256"] and original.stat().st_size==reg["bytes"],"different physical artifact")
    with zipfile.ZipFile(original)as z:
        need(len({i.filename for i in z.infolist()})==len(z.infolist()),"duplicate original member")
        w=json.loads(z.read("worker.json"))
        need(all(w[k]==reg[k]for k in ("head","job","runner","runner_id","run"))and w["boot"],"original owner identity")
        need(json.loads(z.read("confirmation-enrollment.json"))==registration(reg["rank"]),"different physical registration")
    return original,w["boot"]

def paired(values):
    n=len(values);need(n==6,"six independent pairs")
    positive=sum(v>0 for v in values);nonzero=n-values.count(0);side=min(positive,nonzero-positive)
    return dict(reductions=values,median=statistics.median(values),median_interval_96_875=[min(values),max(values)],two_sided_sign_p=min(1,2*sum(math.comb(nonzero,k)for k in range(side+1))/2**nonzero))

def main():
    pp=argparse.ArgumentParser();pp.add_argument("roster",type=Path);pp.add_argument("out",type=Path);pp.add_argument("--gh",default=shutil.which("gh-auto")or"gh-auto");args=pp.parse_args()
    roster=json.loads(args.roster.read_bytes());head=roster["head"];runs=roster["runs"]
    need(len(head)==40 and len(runs)==len(set(runs))==6 and registration(0)["spec"]["ranks"]==["PC","CP","PC","CP","PC","CP"],"bad original schedule")
    args.out.mkdir(parents=True,exist_ok=True);rows=[];boots=[];originals=[]
    # Seal all public attempt/host and physical boot identities before looking at numerical results.
    for slot,run in enumerate(runs):rows.append(intake(args.gh,slot,run,head))
    write(args.out/"transport.json",rows)
    for r in rows:
        d=args.out/f"rank-{r['rank']}";d.mkdir(exist_ok=True);original,boot=physical(args.gh,d,r);originals.append(original);boots.append(boot)
    write(args.out/"admitted.json",dict(originals=rows,boots=boots))
    need(all(r["status"]==r["job_status"]=="success" for r in rows) and len(set(boots))==len({r["job"]for r in rows})==len({r["runner_id"]for r in rows})==6,"distinct fully successful independent boots")
    scopes=[];errors=[]
    for r,original in zip(rows,originals):
        d=original.parent
        try:
            with tempfile.TemporaryDirectory(prefix="native-",dir=d)as scratch:
                source.extract(original,Path(scratch));x=fixed.run(Path(scratch))
            need(x["rank"]==r["rank"] and x["worker"]["boot"]==boots[r["rank"]] and len(x["pairs"])==1 and x["pairs"][0]["order"]==registration(r["rank"])["spec"]["ranks"][r["rank"]],"incorrect enrollment binding")
            write(d/"reopened.json",x)
            scopes.append(dict(transport=r,boot=boots[r["rank"]],order=x["pairs"][0]["order"],pair=x["pairs"][0],fixed=x["fixed"],fixed_reduction=x["fixed_reduction"],nonincremental=x["nonincremental"],nonincremental_reduction=x["nonincremental_reduction"],qualified=x["qualified"],native=x["native"],zip=x["zip"],visits=[{k:v[k]for k in ("role","scope","prices","empty_new","edited_metadata")}for v in x["visits"]]))
        except Exception as e:
            errors.append(dict(rank=r["rank"],error=repr(e)))
    write(args.out/"reopen-status.json",dict(scopes=scopes,errors=errors))
    need(not errors,"at least one original refused; all reopens retained")
    estimators={key:paired([v["pair"]["reductions"][phase][field] for v in scopes])for key,phase,field in (("edited_rustc","edit","owner"),("edited_cargo","edit","plain"),("edited_independent_cargo","edit","traced_whole"),("parser_rustc","parser","owner"),("parser_cold","parser","cold"),("cold_cargo","cold","plain"),("unchanged_cargo","new-idle","plain"))}
    estimators["fixed_rustc"]=paired([v["fixed_reduction"]for v in scopes]);estimators["nonincremental_rustc"]=paired([v["nonincremental_reduction"]for v in scopes])
    accepted=all(r["qualified"]for r in scopes) and estimators["edited_rustc"]["two_sided_sign_p"]<.05
    write(args.out/"summary.json",dict(head=head,spec=registration(0)["spec"],source=source.BIND,estimators=estimators,qualified=accepted,scopes=scopes))
    print(json.dumps(dict(qualified=accepted,estimators=estimators),sort_keys=True))
    if not accepted:raise SystemExit(2)

if __name__=="__main__":main()
