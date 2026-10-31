"""Authenticate both official native runs before exposing either complete compiler."""
import json
from pathlib import Path
import shutil
import sys
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"rdr-root-field"))
import inputs
from restore_candidate import restore_candidate

CQA="ef86b0020a0a2d99a0533ce8cc5b897aa3bd277f"
CRUN=41194085719
CJOB=124516622634
CMANIFEST="8ee087282fc82752973111097ba1ef40869f474da62a560d39be236914e72822"
CFILES={"rdr-root-qualified-native":(13039368932,40115758,"d39d6486e5753bf29916e884d4f663a0668c8a48471319e693f6b26a3c1f15dc"),
        "rdr-root-observations":(13039259106,69577,"0447a7707da896f0921d82e9076b6b3a3c9a2edde4d9f355b1aea24f4b93160f")}
PROVENANCE={"P":"451280868674ca80f62a0c45d64e636be9c967f1801fd0c8e3099797a21b9093",
            "C":"3a1474e3604d3c73ded29d7b0e58fbf2a89e1958853e88ed8d88d23d37052576"}
sha, need, put=inputs.build.sha, inputs.need, inputs.build.write
def candidate(meta,observation):
    m=json.loads(meta);q=json.loads(observation)
    need(inputs.source.digest(meta)==CMANIFEST and q["transfer"]==CMANIFEST and
         (int(m["run"]),m["qa"],int(m["attempt"]))==(CRUN,CQA,1) and
         {k:m["roles"][k]["commit"] for k in ("P","C")}=={"P":inputs.P,"C":inputs.C} and
         set(m["differences"])=={"bin/rustdoc",m["driver"]} and q["same_non_driver"]==m["same_non_driver"]==79,"changed native enrollment")
    need(q["baseline_driver"][0]==PROVENANCE["P"] and q["candidate_driver"][0]==PROVENANCE["C"],"wrong driver")
    return m

def freeze(root,out):
    raw=root/"incoming";raw.mkdir()
    inputs.official(raw)
    base=inputs.parent(raw,root)
    r=inputs.api(f"runs/{CRUN}");j=inputs.api(f"jobs/{CJOB}")
    need((r["head_sha"],r["run_attempt"],r["conclusion"],r["head_branch"],r["event"],j["run_id"],j["head_sha"],j["conclusion"])==(CQA,1,"success","charlie/qa-rdr-root-field-20261031","workflow_dispatch",CRUN,CQA,"success"),"unapproved C run")
    listing=inputs.api(f"runs/{CRUN}/artifacts?per_page=100")["artifacts"]
    need(len(listing)==2,"unqualified/extra C artifacts")
    for a in listing:
        n=a["name"];idx,size,digest=CFILES[n]
        need((a["id"],a["size_in_bytes"],a["digest"],a["expired"])==(idx,size,"sha256:"+digest,False),"official C artifact mismatch")
        dest=raw/(n+".zip");inputs.api(f"artifacts/{idx}/zip",dest)
        need(dest.stat().st_size==size and sha(dest)==digest,"downloaded C artifact mismatch")
    delta=root/"candidate-transfer";delta.mkdir()
    with zipfile.ZipFile(raw/"rdr-root-qualified-native.zip") as z:
        need(len(z.namelist())==2 and set(z.namelist())=={"manifest.json","changed-native.tar.zst"},"unexpected delta")
        for n in z.namelist():
            with z.open(n) as f,(delta/n).open("xb") as dst:shutil.copyfileobj(f,dst)
    with zipfile.ZipFile(raw/"rdr-root-observations.zip") as z:
        obs=z.read("receipts/qualified.json")
        wire=json.loads(z.read("receipts/wire/qualified.json"))
        need(wire["commands"]==116,"missing upstream wire gate")
        for role,want in (("P",101),("C",0)):
            gate=json.loads(z.read("receipts/"+role+"/rmake.json"))
            need((gate["returncode"],gate["rustc_calls"],gate["loaded"],gate["fresh"],gate["privacy_errors"])==(want,42,14,4,3),"unqualified physical checked-in fixture")
    c=candidate((delta/"manifest.json").read_bytes(),obs)
    restore_candidate(root/"parent-sdk",base,delta,root/"candidate-sdk",CQA,CRUN,1)
    put(out/"original-artifacts.json",dict(P=inputs.MEMBERS,C=CFILES,Pqa=inputs.QA,Cqa=CQA,P_run=inputs.RUN,C_run=CRUN,Pjob=inputs.JOB,Cjob=CJOB))
    put(out/"source-native.json",dict(parent=base["roles"]["P"],candidate=c["roles"]["C"],driver=c["driver"],manifest=CMANIFEST,differences=c["differences"],wire=116))
    return {"P":base["files"],"C":c["files"]},c["driver"]
