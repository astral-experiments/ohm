"""Verify the compact Mac test-build observation table; --raw also reopens the original ZIP."""
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
sys.path.insert(0,str(HERE))
from project import PARENT, CHILD, QA, RUN, HARNESS_SHA, SOURCE, ORDERS, ENDPOINTS, encoded, sha, project

def paired(rows, orders):
    n=len(rows)
    ratios=[p/c for p,c in rows]
    ans={"pairs":n,"raw_PC":rows,"ratios_P_over_C":ratios,"median_ratio":statistics.median(ratios),
         "parent_median":statistics.median([p for p,c in rows]),"child_median":statistics.median([c for p,c in rows]),
         "geometric_ratio":math.exp(statistics.mean(map(math.log,ratios)))}
    if n==12:
        # Exactly P[X<=2] in the binomial(n=12, p=.5) tail on both sides.
        tail=sum(math.comb(n,k) for k in range(3))/2**n
        ranked=sorted(ratios)
        vals=[math.log(r/2) for r in ratios]
        by_period=[v*(1 if order=="PC" else -1) for v,order in zip(vals,orders)]
        stats=[sum(d if i in chosen else -d for i,d in enumerate(by_period)) for chosen in itertools.combinations(range(n),6)]
        assert len(stats)==math.comb(n,6)==924
        ans.update(median_CI_96_14pct=[ranked[2],ranked[9]],actual_sign_coverage=1-2*tail,
                   assignments=len(stats),one_sided_balanced_sharp_2x_p=sum(t>=sum(vals)-1.2e-11 for t in stats)/len(stats))
    return ans

def verify(d):
    assert d["run"]==RUN and d["qa"]==QA and d["source"]["roles"]==[PARENT,CHILD] and d["source"]["ruff"]==SOURCE
    assert len(set(d["sdk"]["drivers"].values()))==2 and d["sdk"]["members"]>2000
    assert d["sdk"]["release"]=="7cd292583785c25a315f67bf85c8f028a15ccb0be5461ac39ce6e46720807bb8"
    assert d["source"]["archives"]==423 and len(d["source"]["archive_manifest"])==64
    assert d["counter"]["retired_instruction_scope"] in {"unavailable-or-inconclusive","direct-process-only","whole-tree-calibrated"}
    assert isinstance(d["counter"]["tree_CPU_calibrated"],bool) and len(d["counter"]["timing_streams"])==18
    assert d["mach_o_preflight"]["tamper_controls"]==4
    assert len({d["proc_macro_loader"][r]["source"] for r in "SPC"})==1
    products=d["products"]
    for h,p in products.items():
        assert sha(encoded(p))==h and p["tests"]==[r[0] for r in p["verdicts"]] and {r[1] for r in p["verdicts"]}=={"ok"}
        image=d["archived_executables"][p["raw"]]
        assert image["raw"]==p["raw"] and image["text"]==p["text"] and image["size"]>p["text"][0]>0 and len(p["text"][1])==len(p["raw"])==64
    selected=set(d["modes"]);assert selected=={"screen"} or selected=={"screen","confirm"}
    assert set(d["providers"])=={"test-"+m+"-test-"+r for m in selected for r in "PC"}
    for phases in d["providers"].values():
        assert set(phases)=={"initial","unchanged","replace","malformed","missing","repair","empty-reference"}
        for phase,value in (("initial",17),("unchanged",17),("replace",29),("malformed",None),("missing",None),("repair",29),("empty-reference",29)):
            v=phases[phase];assert v["value"]==value and v["cargo_exit"]==(0 if value else 101)
            if phase in ("initial","replace","repair","empty-reference"):assert v["ld"]>=1
        assert phases["initial"]["executable"]==phases["unchanged"]["executable"]!=phases["replace"]["executable"]==phases["repair"]["executable"]==phases["empty-reference"]["executable"]
        assert phases["initial"]["archive"]!=phases["replace"]["archive"]==phases["repair"]["archive"] and phases["missing"]["archive"] is None
    results={}
    for mode in ORDERS:
        if mode not in selected:continue
        cohort=d["modes"][mode];order=cohort["orders"];assert order==ORDERS[mode] and cohort["harness_sha"]==HARNESS_SHA
        rows=cohort["rows"];clocks={};full_visits=0;valid=0;test_calls=0;ignored=0
        expected=set()
        for r in "PC":
            for flank in ("before","after"):
                for state in ("old","new"):expected.add(f"native-{flank}/{r}/empty-{state}/clean")
                for ph in ("cold",*ENDPOINTS,*(("invalid","repair") if flank=="before" else ())):
                    expected.add(f"native-{flank}/{r}/actual/{ph}")
            for i in range(1,len(order)+1):
                for ph in ("cold",*ENDPOINTS):expected.add(f"pair-{i:02}/{r}/{ph}")
                for state in ("old","new"):expected.add(f"pair-{i:02}/{r}/reference/empty-{state}/clean")
        assert set(rows)==expected
        point={}
        for r in "PC":
            for f in ("native-before","native-after"):
                assert cohort["dyld"][f+"/"+r]==d["sdk"]["drivers"][r]
            for label,state in (("cold","old"),("edit","new"),("repeat-1","new"),("repeat-2","new"),("invalid","invalid"),("repair","new")):
                prior=rows["native-before/"+r+"/actual/"+label]
                if label in ENDPOINTS:
                    post=rows["native-after/"+r+"/actual/"+label]
                    signature=lambda v:(v["full"],v["link_only"],v["ld"])
                    assert signature(prior["native"])==signature(post["native"])
                    q=prior["native"]
                    assert not q["link_only"] and (q["full"]==["ruff_python_ast","zmij"] and q["ld"]==1 if r=="P" else "zmij" not in q["full"] and set(q["full"])<={"ruff_python_ast"} and q["ld"]<=1)
                    if label=="edit" and r=="C":assert q["full"]==["ruff_python_ast"] and q["ld"]==1
                    assert prior["zmij"]["hard"]==(r=="P") and prior["zmij"]["recheck"]==(r=="C") and prior["zmij"]["fresh"]==(r=="C")
                    point[r+"/"+label]={"full":q["full"],"link_only":q["link_only"],"stock_apple_links":q["ld"],"dirty":prior["dirty"]}
        positives={(r,s):rows[f"native-before/{r}/empty-{s}/clean"]["product"] for r in "PC" for s in ("old","new")}
        for role in "PC":assert positives[role,"old"]!=positives[role,"new"]
        for state in ("old","new"):
            p,c=[products[positives[r,state]] for r in "PC"]
            assert all(p[k]==c[k] for k in ("text","tests","verdicts"))
            for flank in ("native-before","native-after"):
                x=cohort["cross"][flank+"/"+state]
                assert x["different_total"]==x["different_N_OSO"]+x["different_signature"] and x["path_count"]==(29 if state=="old" else 30)
                assert x["archive_members"]==14 and len(x["changed_pages"])>0
                for r in "PC":
                    local=rows[flank+"/"+r+"/empty-"+state+"/clean"]["product"]
                    assert x["roles"][r]["raw"]==products[local]["raw"]
            assert cohort["cross"]["native-before/"+state]["same_after_verified_paths_and_pages"]==cohort["cross"]["native-after/"+state]["same_after_verified_paths_and_pages"]
        for r in "PC":
            driver_handles={(row["selected"]["dev"],row["selected"]["ino"]) for row in cohort["installations"].values() if row["selected"]["role"]==r}
            assert len(driver_handles)==1
            for i in range(1,len(order)+1):
                case=f"pair-{i:02}/{r}";ins=cohort["installations"][case]
                assert ins["selected"]["role"]==r and ins["selected"]["image_sha"]==d["sdk"]["drivers"][r]
                for state in ("old","new"):
                    ref=rows[case+"/reference/empty-"+state+"/clean"];v=ins["states"][state]
                    assert v["raw"]==products[ref["product"]]["raw"] and v["canonical"]==cohort["cross"]["native-before/"+state]["same_after_verified_paths_and_pages"]
                    for ph in v["compared"]:assert rows[case+"/"+ph]["product"]==ref["product"]
        assert set(products[positives["P","new"]]["tests"])-set(products[positives["P","old"]]["tests"])=={"nodes::tests::f_string_parts"}
        assert len(products[positives["P","old"]]["tests"])==53 and len(products[positives["P","new"]]["tests"])==54
        for location,row in rows.items():
            if row["state"]=="invalid":
                assert "product" not in row and row["codes"]==["E0425"] and row["status"]==101
            else:
                parts=location.split("/")
                ref=("/".join(parts[:2])+"/reference/empty-"+row["state"]+"/clean" if location.startswith("pair-") else
                     "/".join(parts[:2])+"/empty-"+row["state"]+"/clean")
                assert row["status"]==0 and row["codes"]==[] and row["product"]==rows[ref]["product"]
                valid+=1;test_calls+=len(products[row["product"]]["verdicts"]);ignored+=sum(v=="ignored" for n,v in products[row["product"]]["verdicts"])
            if not location.startswith("pair-") or "/reference/" in location:continue
            key,r,label=location.split("/");idx=int(key.removeprefix("pair-"))
            off=rows["native-before/"+r+"/actual/"+label]
            assert row["roster"]==off["roster"] and row["dirty_identity"]==off["dirty_identity"] and row["typed"]==off["typed"]
            assert "native" not in row and row["role"]==r
            if label=="cold":
                assert "clock" not in row;continue
            c=row["clock"];assert c["ns"]==c["stop_ns"]-c["start_ns"]>0
            clocks[idx,r,label]=c;full_visits+=1
        assert full_visits==6*len(order)
        observed_order=sorted(clocks,key=lambda t:clocks[t]["start_ns"])
        wanted_order=[(i,r,ph) for i,s in enumerate(order,1) for r in s for ph in ENDPOINTS]
        assert observed_order==wanted_order and all(clocks[a]["stop_ns"]<clocks[b]["start_ns"] for a,b in zip(observed_order,observed_order[1:]))
        estimates={};cpu={};instructions={}
        for ph in ENDPOINTS:
            raw=[[clocks[i,r,ph]["ns"] for r in "PC"] for i in range(1,len(order)+1)]
            e=paired(raw,order);converted=dict(e)
            for k in ("pairs","actual_sign_coverage"):converted.pop(k,None)
            if "median_CI_96_14pct" in converted:converted["median_CI_96.14pct"]=converted.pop("median_CI_96_14pct")
            published=cohort["reported"][ph]
            assert set(converted)==set(published)
            for k,v in converted.items():
                if isinstance(v,float):assert math.isclose(v,published[k],rel_tol=1e-12)
                else:assert v==published[k]
            estimates[ph]=e
            raw_cpu=[[round(1000*(clocks[i,r,ph]["user"]+clocks[i,r,ph]["system"])) for r in "PC"] for i in range(1,len(order)+1)]
            if d["counter"]["tree_CPU_calibrated"]:
                cpu[ph]=paired(raw_cpu,order) if all(p>0 and c>0 for p,c in raw_cpu) else {"raw_PC":raw_cpu,"unavailable":"native time resolution"}
            if d["counter"]["retired_instruction_scope"]=="whole-tree-calibrated":
                raw_ir=[[clocks[i,r,ph]["instructions"] for r in "PC"] for i in range(1,len(order)+1)]
                instructions[ph]=paired(raw_ir,order)
        e=estimates["repeat-1"];rule=(min(e["ratios_P_over_C"])>2) if mode=="screen" else (e["median_CI_96_14pct"][0]>2 and e["one_sided_balanced_sharp_2x_p"]<=0.05)
        assert cohort["accepted"]==rule
        results[mode]={"primary_pass":rule,"estimates_ns":estimates,"cpu_ms":cpu,"calibrated_instructions":instructions,"comparisons":full_visits,
                       "native":point,"positive_harness_runs":valid,"enumerated_test_verdicts":test_calls,"ignored":ignored,"product_ids":{r+"/"+state:h for (r,state),h in positives.items()}}
    assert ("confirm" in selected)==results["screen"]["primary_pass"]
    return results

if __name__=="__main__":
    if not __debug__:raise SystemExit("Use python without -O.")
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("--raw",type=Path);args=ap.parse_args()
    obs=json.loads(gzip.decompress((HERE/"observations.json.gz").read_bytes()))
    if args.raw:
        assert project(args.raw)==obs, "physical raw/projection disagreement"
    print(json.dumps(verify(obs),indent=2,sort_keys=True))
