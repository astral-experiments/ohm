"""Recompute the #22958 instruction pairs and both Cargo clocks from the original member bytes."""
from fractions import Fraction
from pathlib import Path
import argparse
import hashlib
import json
import runpy
import zipfile

ROOT=Path(__file__).resolve().parent
HEAD="323ffa372089f275a6c09654ebf5bdeb1c632435"
RUN=41411252543
JOB=125164580588
BOOT="7bf853cc-35d6-49bd-ab54-994d55b3d111"
ORIGINAL="33846becce13a3c0f552669b0d8243be0a90c64a20152eabc61f34ec2f04975a"
def read(p):return json.loads(p.read_bytes())
def sha(p):
    with p.open("rb")as f:return hashlib.file_digest(f,"sha256").hexdigest()
def run(files,archive,tracker=zipfile.ZipFile):
    paired=files/"paired-original.py";wall=files/"wall-lines.py"
    assert sha(paired)=="a1cd174c3a2ede72883e07fb41966dbb55e15cc30b3e72ef246b6940afa682e8"
    assert sha(wall)=="798544e04fdfa5106d314e0c27c16a2bcc87c1429b5d011e9c37331fec0c503d"
    score=runpy.run_path(str(paired));fn=score["main"]
    fn.__globals__.update(BOOT=BOOT,RUN=RUN,JOB=JOB,HEAD=HEAD,ZipFile=tracker)
    value=fn(archive,sha(archive))
    text=wall.read_text();before='"13895848-ed2e-435a-b313-9e006b9ff3e2"';assert text.count(before)==1
    ns={"__file__":str(wall),"__name__":"original_cargo_reported_clock"}
    exec(compile(text.replace(before,repr(BOOT)),str(wall),"exec"),ns)
    ns["ZipFile"]=tracker
    return value,ns["run"](archive)
def main(original):
    p=ROOT/"raw-members.zip";members=read(ROOT/"member-sha256.json")
    assert sha(p)==members["subset_sha256"] and members["original_sha256"]==ORIGINAL
    runinfo,jobinfo,artifact=[read(ROOT/q)for q in ("run.json","jobs.json","original-service.json")]
    job,=jobinfo["jobs"]
    assert runinfo["status"]=="completed" and runinfo["conclusion"]=="success" and runinfo["run_attempt"]==1
    assert runinfo["id"]==job["run_id"]==artifact["workflow_run"]["id"]==RUN and job["id"]==JOB
    assert runinfo["head_sha"]==job["head_sha"]==artifact["workflow_run"]["head_sha"]==HEAD
    assert artifact["id"]==13125698743 and artifact["digest"]=="sha256:"+ORIGINAL and artifact["size_in_bytes"]==120925615
    with zipfile.ZipFile(p)as z:
        assert z.testzip() is None and set(z.namelist())==set(members["members"]) and len(z.namelist())==len(members["members"])
        for name,checksum in members["members"].items():assert hashlib.sha256(z.read(name)).hexdigest()==checksum
        if original:
            assert sha(original)==ORIGINAL and original.stat().st_size==artifact["size_in_bytes"]
            with zipfile.ZipFile(original)as large:
                for name in z.namelist():assert z.read(name)==large.read(name)
    score,clocks=run(ROOT,p)
    # This call used the byte-preserving compact archive. The published original's
    # authenticated digest and the optional byte-by-byte archive comparison are above.
    score["raw_sha256"]=ORIGINAL
    assert score==read(ROOT/"expected-instructions.json") and clocks==read(ROOT/"expected-cargo-clocks.json")
    assert score["primary_and_secondary"]==[True,True]
    for group in ("uv_client","sum_two"):
        assert all(Fraction(t,m)<Fraction(4,5)for m,t in score["metrics"][group]["raw"])
    print(json.dumps({"run":RUN,"head":HEAD,"original_sha256":ORIGINAL,"raw_members":len(members["members"]),
                      "primary_and_secondary":score["primary_and_secondary"],"metrics":score["metrics"],
                      "cargo_rounded_median_ratio_range":clocks["cargo_display_median_ratio_bounds"]},indent=2,sort_keys=True))
if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--original",type=Path)
    main(parser.parse_args().original)
