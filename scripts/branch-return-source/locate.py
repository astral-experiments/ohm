"""Authenticate the two original artifacts of one approved source qualification."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from registration import need, REPO

def locate(run,qa,program):
    def api(s):return json.loads(subprocess.check_output([program,"api","repos/"+REPO+"/actions/"+s]))
    entry=api("runs/"+str(run))
    need((entry["id"],entry["head_sha"],entry["head_branch"],entry["run_attempt"],entry["event"],entry["conclusion"])==
         (int(run),qa,"charlie/qa-branch-return-source-20261031",1,"workflow_dispatch","success"),"unqualified source run")
    jobs=api(f"runs/{run}/attempts/1/jobs")["jobs"];job,=jobs
    need((job["name"], job["head_sha"],job["status"],job["conclusion"])==
          ("Exact Full and Packed source, Rust tests and native providers",qa,"completed","success"),"wrong native job")
    for name in ("Reopen normal GNU native tools from the signed release","Independently bootstrap both complete SDKs and exercise branch flags, corruption and native input changes"):
        step,=[s for s in job["steps"] if s["name"]==name];need(step["conclusion"]=="success","missing native gate")
    artifacts=api(f"runs/{run}/artifacts")["artifacts"];result={}
    need({a["name"] for a in artifacts}=={"branch-return-source-sdk","branch-return-source-observations"} and len(artifacts)==2,"source transfer ambiguity")
    for a in artifacts:
        need(not a["expired"] and a["workflow_run"]["head_sha"]==qa and a["workflow_run"]["id"]==int(run) and
             a["digest"].startswith("sha256:") and len(a["digest"])==71,"wrong artifact provenance")
        result[a["name"]]=[a["id"],a["size_in_bytes"],a["digest"][7:]]
    return dict(run=int(run),qa=qa,attempt=1,job=job["id"],artifacts=result)

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("run",type=int);p.add_argument("qa");p.add_argument("--gh",default="/home/dev-user/.local/bin/gh-auto")
    a=p.parse_args();print(json.dumps(locate(a.run,a.qa,a.gh),indent=2,sort_keys=True))
