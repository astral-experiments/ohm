"""Reopen all six registered fresh-host archives, then compute the exact paired result."""
import argparse
import hashlib
import json
import math
import shutil
import statistics
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify import digest,must,reader

def close(directory,assets,output):
    meta=json.loads(assets.read_bytes());rows=meta["assets"];run=meta["run"];head=meta["head"]
    must(meta["conclusion"]=="success" and len(rows)==len({r["id"]for r in rows})==6 and len(meta["jobs"])==6,"incomplete independent source jobs")
    evidence=[];inputs=[];boots=set();old=set();new=set();resource=[]
    for slot,order in enumerate(("PC","CP","CP","PC","PC","CP")):
        row,=(r for r in rows if r["name"]==f"matched-ty-ide-bucket-confirm-{run}-{slot}")
        path=directory/(str(slot)+".zip");sha=row["digest"].removeprefix("sha256:")
        job,=(j for j in meta["jobs"]if j["name"]==f"Ruff #29697 {slot} {order}")
        must(row["workflow_run"]["id"]==run and not row["expired"] and job["conclusion"]=="success" and row["size_in_bytes"]==path.stat().st_size and digest(path)==sha,"physical source asset")
        must(shutil.disk_usage(directory).free>16*2**30,"temporary native verification space")
        with tempfile.TemporaryDirectory(dir=directory)as scratch:r=reader(path,Path(scratch))
        boot=str(uuid.UUID(r["boot_id"]));must(boot not in boots and r["slot"]==slot,"reused host");boots.add(boot)
        p,=(h for h in r["histories"]if h["role"].endswith("P"));c,=(h for h in r["histories"]if h["role"].endswith("C"))
        must(p["old"]==c["old"] and p["new"]==c["new"] and p["old"]!=p["new"],"mismatched local native verdict")
        old.add(c["old"]);new.add(c["new"]);pair,=r["pairs"];gain=1-c["primary"]/p["primary"]
        must(gain==pair["reduction"] and c["retained"]-p["retained"]==pair["additional_objects"],"independent denominator")
        inside={};clean={}
        with zipfile.ZipFile(path)as z:
            reg=json.loads(z.read("registration.json"));factory=json.loads(z.read("factory-consumed.json"))
            must(reg["factory"]==factory["binding"] and reg["order"]==list(order),"source custody")
            comm=json.loads(z.read("terminal.json"));actual={}
            for v in comm["roles"]:
                obs=v["observed"];role=v["role"];actual[role]={"same_donors":v["observer_matches_primary"],"physical":obs["process_instructions"],"truncated_clock":obs["positive_instructions_without_clock"]}
                for cl in ("old","edit","repair","independent-clean"):
                    name=str(v["index"])+role+"/"+cl
                    clean[name]=json.loads(z.read(name+"/result.json"))["elf"]["sha256"]
            inside=actual
        for h in (p,c):resource.append({"slot":slot,"role":h["role"][-1],"cold":h["cold"],"noop":h["noop"],"storage":h["storage"]})
        evidence.append({"slot":slot,"order":order,"boot":boot,"runner":r["runner"],"P":p["primary"],"C":c["primary"],"reduction":gain,"speedup":p["primary"]/c["primary"],"objects_P":p["retained"],"objects_C":c["retained"],"CGUs":c["objects"],"physical_files_reopened":r["native_bodies"],"process_replay":inside,"local_clean_ELFs":clean})
        inputs.append({"id":row["id"],"bytes":row["size_in_bytes"],"sha256":sha,"slot":slot,"job":job["id"]})
    ratios=[x["speedup"]for x in evidence];gains=[x["reduction"]for x in evidence];positive=sum(v>0 for v in gains);negative=sum(v<0 for v in gains);n=positive+negative
    pvalue=min(1,2*sum(math.comb(n,k)for k in range(min(positive,negative)+1))/2**n)
    all_native_equal=len(old)==len(new)==1
    out={"run":run,"head":head,"assets":inputs,"boots":evidence,"resources":resource,"old_cross_boot":sorted(old),"new_cross_boot":sorted(new),"all_cross_boot_ELFs_equal":all_native_equal,"paired_two_sided_exact_sign_p":pvalue,"median_reduction":statistics.median(gains),"median_speedup":statistics.median(ratios),"median_range_coverage":1-2/2**len(gains),"median_reduction_interval":[min(gains),max(gains)],"speedup_interval":[min(ratios),max(ratios)],"admitted_2x":all_native_equal and all(x>=2 for x in ratios) and all(r["objects_C"]>r["objects_P"]for r in evidence)}
    output.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n");return out
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("directory",type=Path);parser.add_argument("--assets",type=Path,required=True);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    x=close(args.directory,args.assets,args.output);print(x["median_speedup"],x["speedup_interval"],x["paired_two_sided_exact_sign_p"],x["admitted_2x"])
