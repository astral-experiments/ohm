"""Verify the portable table, or independently rebuild it with --raw SIGNED.zip QUALIFIED.zip."""
import argparse
import gzip
import itertools
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from project import ARCHIVES, CHILD, PARENT, PHASES, encoded, projection, sha


def estimate(rows, order):
    ratios = [a/b for a,b in rows]
    result = {"raw_PC":rows, "ratios_P_over_C":ratios, "median_ratio":statistics.median(ratios),
              "parent_median":statistics.median(a for a,_ in rows), "child_median":statistics.median(b for _,b in rows),
              "geometric_ratio":math.exp(statistics.mean(map(math.log,ratios)))}
    if len(ratios) == 12:
        signs = [1 if v=="PC" else -1 for v in order]
        tested = [math.log(r/2) for r in ratios]
        obs = statistics.mean(tested)
        residual = [x*s for x,s in zip(tested,signs)]
        values = [sum(x if i in positive else -x for i,x in enumerate(residual))/12
                  for positive in itertools.combinations(range(12),6)]
        assert len(values)==924
        result.update(assignments=len(values), **{"median_CI_96.14pct":sorted(ratios)[2:3]+sorted(ratios)[-3:-2]},
                      one_sided_balanced_sharp_2x_p=sum(x>=obs-1e-12 for x in values)/len(values))
    return result


def verify(data):
    assert data["source"]["parent"]==PARENT and data["source"]["child"]==CHILD
    assert data["source"]["ruff"]=="ef23c9c39eb3029bab0139c3ea7ae6d95c4131e0"
    assert data["source"]["ruff_lock"]=="9e59dd9a48f343e2edbecfad4d47ce8dd38017cb8b773d385b8f8b1556df01bc"
    assert data["sdk"]["members"]==2466 and len(set(data["sdk"]["driver"].values()))==2
    assert data["calibration"]["tree_CPU_calibrated"] and set(data["calibration"]["retired_deltas"].values())=={None}
    assert data["causal"]=={"untouched":[1,1,1],"omit-vector-comment":[1,0,0],"restored":[1,1,1]}
    assert set(data["proc_macro"])=={"signed-S","qualified-S","qualified-P","qualified-C"}
    for probe in data["proc_macro"].values(): assert probe["value"]==3
    assert set(data["providers"])=={m+"-"+r for m in ("screen","confirm") for r in "PC"}
    for control in data["providers"].values():
        for stage,val in (("initial",17),("unchanged",17),("replace",29),("malformed",None),("missing",None),("repair",29),("empty-reference",29)):
            assert control[stage]["cargo_exit"]==(101 if val is None else 0) and control[stage].get("value")==val
        assert control["initial"]["executable"]!=control["replace"]["executable"]==control["repair"]["executable"]==control["empty-reference"]["executable"]
    for h,product in data["objects"].items():
        assert sha(encoded(product))==h and len(product["objects"])==16 and set(product["metadata"])=={"lib.rmeta","lib.rmeta-link"}
    seed = sha(("ohm/Apple-zmij/confirm/1:"+data["sdk"]["release_sha"]+":"+data["source"]["ruff"]).encode())
    possible=list(itertools.combinations(range(12),6)); rank=int(seed,16)%len(possible);assert rank==695
    expected=["PC" if i in possible[rank] else "CP" for i in range(12)]
    all_results={}
    for mode,order in (("screen",["PC","CP"]),("confirm",expected)):
        c=data[mode];assert c["accepted"] and c["order"]==order
        cases=c["cohorts"];assert len(cases)==8+len(order)*2
        counts=Counter(); details={}
        for arm in "PC":
            base=cases["native-before/"+arm+"/actual"];post=cases["native-after/"+arm]
            cold=base["cold"]["native"]
            assert len(cold["full"])==39 and not cold["link_only"] and cold["apple_ld"]==8
            for label in PHASES:
                native=base[label]["native"]
                expected_full=(["ruff_python_ast"] if label=="edit" else [])+(["zmij"] if arm=="P" else [])
                assert native["full"]==expected_full and native["link_only"]==[] and native["apple_ld"]==0
                assert all(post[label]["native"][k]==native[k] for k in ("full","link_only","apple_ld"))
                expected_dirty=["compact_str","ruff_python_ast","zmij"] if arm=="P" else (["ruff_python_ast"] if label=="edit" else [])
                assert base[label]["dirty"]==expected_dirty
            for key, phases in cases.items():
                key_role=key.split("/")[1]
                if key_role!=arm: continue
                for label,row in phases.items():
                    assert row["zmij"]["hard"]==(arm=="P") and row["zmij"]["recheck"]==(arm=="C")
                    if row["state"]=="invalid":
                        assert not row["success"] and row["codes"]==["E0425"] and "product" not in row
                        continue
                    baseline_state=row["state"]
                    ref=cases["native-before/"+arm+"/empty-"+baseline_state]["clean-"+baseline_state]
                    ref_body=data["objects"][ref["product"]];product=data["objects"][row["product"]]
                    assert row["success"] and not row["codes"]
                    assert product["value"] == ref_body["value"] == ("3.14 3.14 3.10" if baseline_state=="old" else "3.15 3.15 3.11")
                    assert sorted((x["size"],x["sha256"]) for x in product["objects"].values())==sorted((x["size"],x["sha256"]) for x in ref_body["objects"].values())
                    if key.startswith("pair-") and label in PHASES:
                        assert row["typed_identity"]==base[label]["typed_identity"] and row["dirty"]==base[label]["dirty"]
                        counts["comparisons"]+=1
                        for field in ("archive","reader","metadata","objects"): counts[field]+=product[field]==ref_body[field]
                        for member in ("lib.rmeta","lib.rmeta-link"):counts[member]+=product["metadata"][member]==ref_body["metadata"][member]
        assert counts["comparisons"]==len(order)*6
        for ph in PHASES:
            timings=[[cases[f"pair-{i:02}/{role}"][ph]["ns"] for role in "PC"] for i in range(1,len(order)+1)]
            result=estimate(timings,order)
            reported=c["reported"][ph]
            assert set(result)==set(reported)
            for k,v in result.items():
                if isinstance(v,float): assert math.isclose(v,reported[k],rel_tol=1e-12)
                else: assert v==reported[k],k
            details[ph]={"paired_median":result["median_ratio"],"parent_median_s":result["parent_median"]/1e9,
                         "child_median_s":result["child_median"]/1e9}
            if mode=="confirm":details[ph].update(CI=result["median_CI_96.14pct"],p=result["one_sided_balanced_sharp_2x_p"])
        if mode=="screen":assert all(x>2 for x in c["reported"]["repeat-1"]["ratios_P_over_C"])
        else:assert details["repeat-1"]["CI"][0]>2 and details["repeat-1"]["p"]<=.05
        all_results[mode]={"effects":details,"comparisons_with_empty_new":dict(counts),"pairs":len(order)}
    return all_results


if __name__=="__main__":
    if not __debug__:
        raise SystemExit("Run Python without -O so the assertions are enabled.")
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw",nargs=2,metavar=("SIGNED.zip","QUALIFIED.zip"))
    args=parser.parse_args()
    packet=json.loads(gzip.decompress((HERE/"observations.json.gz").read_bytes()))
    if args.raw:
        assert projection(*args.raw)==packet, "different physical observations"
    print(json.dumps(verify(packet),indent=2,sort_keys=True))
