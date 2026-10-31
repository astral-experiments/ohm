"""Verify all twelve original paired workers at their exact QA checkout and report the enrolled endpoints."""
import argparse
from fractions import Fraction
from math import comb
import json
from pathlib import Path
from statistics import median
import subprocess
import sys
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import score
import support as q

def ratio(x):
    return {"exact":str(x),"decimal":float(x)}

def endpoint(rows,metric):
    parent=[v["counts"]["P"][metric] for v in rows]
    cand=[v["counts"]["C"][metric] for v in rows]
    ratios=sorted(Fraction(p,c) for p,c in zip(parent,cand,strict=True))
    wins=sum(v>2 for v in ratios); n=sum(v!=2 for v in ratios)
    probability=Fraction(sum(comb(n,k) for k in range(wins,n+1)),2**n)
    return {"median":ratio(median(ratios)),"interval_96_14":[ratio(ratios[2]),ratio(ratios[9])],
            "parent_median_instructions":median(parent),"candidate_median_instructions":median(cand),
            "wins_above_2":wins,"ties":len(rows)-n,"one_sided_sign_p":str(probability)}

def main(where,structural):
    permit=q.gate(HERE.parent/"clearance.json")
    official=q.opened(where/"official.json")
    phase=permit["phase"]; head=subprocess.check_output(["git","-C",HERE,"rev-parse","HEAD"],text=True).strip()
    assert phase in ("primary","independent") and official["phase"]==phase
    assert official["head"]==head and official["attempt"]==1 and official["event"]=="workflow_dispatch"
    assert official["status"]=="completed" and official["conclusion"]=="success"
    assert official["ref"]==q.REG["ref"] and len(official["positions"])==12
    assert sorted((v["block"],v["position"]) for v in official["positions"])==[(b,p) for b in range(1,7) for p in (1,2)]
    prior=q.archive_oracle(structural)
    rows=[];storage=[]; forbidden=set(permit["other_used_boots"])|set(q.REG["screen"]["excluded_boot_ids"])
    helpers=("boot","runner","host")
    unique={k:set() for k in helpers}; job_ids=set();art_ids=set()
    for ref in sorted(official["positions"],key=lambda v:(v["block"],v["position"])):
        b,p=ref["block"],ref["position"]
        assert ref["job_name"]==f"PEP 723 {phase} block {b} position {p}" and ref["artifact_name"]==f"pep723-{phase}-block-{b}-position-{p}"
        assert ref["job_conclusion"]=="success" and ref["job"] not in job_ids and ref["id"] not in art_ids
        job_ids.add(ref["job"]);art_ids.add(ref["id"])
        path=where/f"{b:02}-{p}.zip"
        assert path.stat().st_size==ref["bytes"]
        result=score.verified_position(path,ref["sha256"],prior)
        assert result["head"]==head and int(result["run"])==official["run"] and result["boot"] not in forbidden
        assert result["position"]==p and result["order"]==permit["position_orders"][p-1]
        for k in helpers:
            assert result[k] and result[k] not in unique[k]
            unique[k].add(result[k])
        with zipfile.ZipFile(path) as z:
            actual=json.loads(z.read("counts/confirmation-host.json"))
            expected={"phase":phase,"block":b,"position":p,"order":result["order"],"run":official["run"],"head":head,"boot":result["boot"],
                      "input_plan":permit["confirmation_plan"],"clearance":q.AUTHORIZED_CLEARANCE_SHA256}
            assert actual==expected
            disk=json.loads(z.read("counts/pair.json"))["storage"]
            assert all(all(n<=0 for n in x["physical_payload_count_delta"].values()) for x in disk.values())
            storage.append({stage:r["C"]-r["P"] for stage,r in disk.items()})
        result["block"]=b;result["source_zip"]=ref["sha256"];rows.append(result)
    for i in range(0,12,2):
        block=rows[i:i+2]
        pair=score.paired_ratios(block)
        for item,checked in zip(block,pair["positions"],strict=True):
            assert item["boot"]==checked["boot"]
            item["counts"]=checked["counts"]
    metrics={name:endpoint(rows,name) for name in ("repeat","edit","edit+repeat")}
    edits=[Fraction(r["counts"]["C"]["edit"],r["counts"]["P"]["edit"]) for r in rows]
    qualifies=Fraction(metrics["repeat"]["interval_96_14"][0]["exact"])>2 and median(edits)<=Fraction(103,100)
    return {"run":official["run"],"head":head,"phase":phase,"plan":permit["confirmation_plan"],"qualifies":qualifies,
            "metrics":metrics,"edit_C_over_P_median":ratio(median(edits)),"storage_C_minus_P":storage,"positions":rows}
if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive_directory",type=Path);parser.add_argument("original_structural_zip",type=Path)
    args=parser.parse_args()
    print(json.dumps(main(args.archive_directory,args.original_structural_zip),sort_keys=True,indent=2))
