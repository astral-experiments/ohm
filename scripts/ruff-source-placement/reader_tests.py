"""Exercise the original Actions API rows and the two factory/distribution provenance tables."""
import copy
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import HERE, need, sha
from originals import INPUTS, ORIGINAL_QA, ORIGIN, check_producer
from readback import kit_sources

origin=json.loads((HERE/"attempts/native-reader.json").read_bytes())
need(all(sha(HERE/k)==v for k,v in origin["unchanged_source_sha256"].items()),"different acquisition or SDK inputs")
args=(origin["metadata"],origin["jobs"],origin["artifacts"])
for slot in (1,2):
    def probe(args,*,frozen=True):
        return check_producer(*args,ORIGIN,ORIGINAL_QA,"admit",slot,"raw",frozen=frozen)
    need(probe(args)["id"]==INPUTS[slot][1],"wrong working native corpus")
    for changed in ("id","head_sha","status","source","digest","size","expired","raw_job"):
        meta,jobs,artifacts=copy.deepcopy(args)
        job=next(j for j in jobs if j["id"]==INPUTS[slot][0]);art=next(a for a in artifacts if a["id"]==INPUTS[slot][1])
        if changed in ("id","head_sha","status"):job[changed]="wrong"
        if changed=="raw_job":job["conclusion"]="failure"
        if changed=="source":meta["head_branch"]="wrong"
        if changed=="digest":art["digest"]="sha256:"+"1"*64
        if changed=="size":art["size_in_bytes"]-=1
        if changed=="expired":art["expired"]=True
        try:probe((meta,jobs,artifacts))
        except (RuntimeError,AssertionError,ValueError):pass
        else:raise AssertionError(changed)
    meta,jobs,artifacts=copy.deepcopy(args);meta.update(status="queued",conclusion=None)
    variables={"GITHUB_REPOSITORY":meta["head_repository"]["full_name"],"GITHUB_SHA":ORIGINAL_QA,
               "GITHUB_RUN_ID":str(ORIGIN),"GITHUB_RUN_ATTEMPT":"1"}
    old=os.environ.copy()
    try:
        os.environ.update(variables)
        need(probe((meta,jobs,artifacts),frozen=False)["id"]==INPUTS[slot][1],"queued sibling blocks completed exact producer")
        next(j for j in jobs if j["id"]==INPUTS[slot][0])["status"]="in_progress"
        try:probe((meta,jobs,artifacts),frozen=False)
        except (RuntimeError,AssertionError,ValueError):pass
        else:raise AssertionError("unfinished producer admitted")
    finally:os.environ.clear();os.environ.update(old)
names={"cargo":"bin/cargo","wild":"lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd",
       "front":"bin/rustc","driver":"lib/librustc_driver-S.so","llvm":"lib/libLLVM.so"}
rows={k:{"name":n,"sha":k} for k,n in names.items()}
source={"files":{rows[k]["name"]:[k,9,493] for k in ("front","driver","llvm")}}
signed={rows[k]["name"]:["actual",493,9,k] for k in ("wild","cargo")}
kit_sources(rows,source,{"driver":"driver"},signed)
for k in names:
    wrong=copy.deepcopy(rows);wrong[k]["sha"]="altered"
    try:kit_sources(wrong,source,{"driver":"driver"},signed)
    except (RuntimeError,AssertionError,ValueError):pass
    else:raise AssertionError(k)
print("Verified original job/digest/size/source, in-flight and altered-job negatives, and distinct physical source/signed inputs.")
