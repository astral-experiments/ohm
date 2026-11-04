"""Freeze authenticated, original Actions metadata and the exact released source protocols."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output",type=Path)
    p.add_argument("studies",nargs="+",type=Path,help="pilot readback.json, then independent confirmation readback.json")
    p.add_argument("--repo",type=Path,required=True)
    p.add_argument("--gh-auto",required=True)
    a = p.parse_args()
    assert 1 <= len(a.studies) <= 2
    prefix = "scripts/ruff-static-array-cost/"
    def git(head,name):
        return subprocess.check_output(["git","show",head+":"+name],cwd=a.repo)
    def api(path):
        return json.loads(subprocess.check_output([a.gh_auto,"api","repos/astral-experiments/ohm/actions/"+path],cwd=a.repo))
    a.output.mkdir(parents=True,exist_ok=True)
    studies = []
    common = None
    transport_bytes = None
    for phase,path in zip(("pilot","confirm"),a.studies):
        report = json.loads(path.read_bytes())
        head = report["head"]
        run = report["run"]
        rev = str(run)
        result = api("runs/"+rev)
        assert (result["head_sha"], result["run_attempt"], result["event"], result["conclusion"]) == (head,1,"workflow_dispatch","success")
        assert (api("runs/"+rev+"/attempts/1/jobs?per_page=100")["total_count"]) == len(report["rows"])
        assets = api("runs/"+rev+"/artifacts?per_page=100")["artifacts"]
        assert len(assets)==len(report["rows"])
        r = git(head,prefix+"registration.json")
        t = git(head,prefix+"transports.json")
        if transport_bytes is None:
            transport_bytes = t
        assert transport_bytes==t
        reg = json.loads(r)
        if phase == "confirm":
            assert reg["admitted_pilot"]["readback_sha256"] == sha(a.studies[0].read_bytes())
        files = {n: sha(git(head,prefix+n)) for n in reg["sources"]}
        assert files == {n:spec["sha256"] for n,spec in reg["sources"].items()}
        if common is None:
            common = files
        assert common == files
        for block, record in report["originals"].items():
            m, = [v for v in assets if v["id"]==record["artifact"]]
            job = api("jobs/"+str(record["job"]))
            assert job["head_sha"]==head and job["run_id"]==run and job["run_attempt"]==1 and job["conclusion"]=="success"
            assert job["name"]=="Ruff Unicode rand edit "+block
            assert m["workflow_run"]["head_sha"]==head and m["workflow_run"]["id"]==run
            assert m["size_in_bytes"]==record["bytes"] and m["digest"]=="sha256:"+record["sha256"]
        (a.output/(phase+"-registration.json")).write_bytes(r)
        studies.append({"phase":phase,"run":run,"head":head,"attempt":1,"event":result["event"],
                        "run_url":result["html_url"],"registered_workflow_sha256":sha(git(head,".github/workflows/ci.yml")),
                        "readback_sha256":sha(path.read_bytes()),"registration_sha256":sha(r),
                        "originals":report["originals"]})
    (a.output/"transports.json").write_bytes(transport_bytes)
    manifest = {"studies":studies,"common_files":common,"transports_sha256":sha(transport_bytes)}
    (a.output/"originals.json").write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n")


if __name__=="__main__":
    assert __debug__
    main()
