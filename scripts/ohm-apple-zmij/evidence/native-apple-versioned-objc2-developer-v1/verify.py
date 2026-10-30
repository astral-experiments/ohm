"""Check the measured Apple observations offline using the committed portable projections."""
from collections import Counter
import gzip
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
from statistics import mean,median

HERE=Path(__file__).resolve().parent
def H(b):return hashlib.sha256(b).hexdigest()
def rd(name):
    f=HERE/name
    return json.loads(gzip.decompress(f.read_bytes()) if name.endswith(".gz") else f.read_bytes())
def must(x):assert x
def verify():
    line=lambda r:r.split("  ",1)
    files=dict((n,key) for key,n in map(line,(HERE/"SHA256SUMS").read_text().splitlines()))
    assert len(files)==len(set(files))==len(list(HERE.iterdir()))-1 and set(files)|{"SHA256SUMS"}=={p.name for p in HERE.iterdir()}
    for k,h in files.items():assert H((HERE/k).read_bytes())==h
    subj=rd("matrix.json")["subjects"];families=rd("matrix.json")["families"];st=rd("subjects.json");cust=rd("custody.json")
    assert len(cust)==4 and all(x["carried_unchanged"]==(None if i==0 else cust[i-1]["members"]) for i,x in enumerate(cust) if i>0)
    assert all(q["sha256"]==rd("github.json")[i]["sha256"] and q["bytes"]==rd("github.json")[i]["bytes"] for i,q in enumerate(cust))
    assert rd("matrix.json")["archive"]==cust[0]["sha256"]
    for role,src in (("P","rust-parent"),("C","rust-objc")):
        assert tuple(subj["rust"][role][k] for k in ("source","tree","compiler_tree"))==tuple(st[src][k] for k in ("source","tree","compiler_tree"))
    assert subj["rust"]["P"]["driver"]!=subj["rust"]["C"]["driver"] and subj["rust"]["P"]["std"]==subj["rust"]["C"]["std"]
    assert len({v["sha"] for v in subj["cargo"].values()})==3 and subj["cargo"]["aware"]["source"]==st["cargo-apple"]["source"]
    allrows=rd("provider-rows.json.gz");switch=rd("migration-rows.json.gz");registry=rd("registry.json.gz");names=rd("named.json.gz")
    assert set(allrows)==set(families)==set(names)==set(registry)=={"signed","classic","aware"}
    for receiver in families:
        summary=families[receiver];f=allrows[receiver];assert summary["passed"] and summary["commands"]==2*len(f)==392
        assert len(summary["judgments"])==20 and not any(x["required_failed"] for x in summary["judgments"].values())
        assert all(r["verdict_equal"] and r["checked"] is not False for r in f.values() if r["same_required"])
        assert any(x["warm"]["error"] for x in f.values() if x["warm"]["status"]==101)
        assert all(x[1]==subj["stock_ld"] for x in summary["physical_xcode"]) and summary["true_producer_rows"]>=100
        for key,row in f.items():
            if "overwrite-same-stamp" in key:
                assert row["replacement"]["modification"] and row["warm"]["answer"]==row["empty"]["answer"]==[17,7] and row["checked"]
            assert row["warm"]["cargo_cdhash"]==row["empty"]["cargo_cdhash"]==summary["kernel_cargo"]
        assert set(registry[receiver])=={"cold","first-repeat","second-repeat","empty"}
        for phase,row in registry[receiver].items():
            assert set(row["producer"])=={"zmij","zlib_rs"}
            assert all(p["physical"]==int(phase in ("cold","empty") or receiver!="aware") for p in row["producer"].values())
            assert row["norm"]==registry[receiver]["empty"]["norm"] and row["module_sha"]==registry[receiver]["empty"]["module_sha"]
        assert set(names[receiver])=={"none","v1","v2","both"}
        for key,endpoints in names[receiver].items():
            assert set(endpoints)=={"cold","empty","repeat"}
            for phase,n in endpoints.items():
                assert n["fresh"]==(key=="none" and receiver=="aware" and phase=="repeat") and n["cargo_cdhash"]==summary["kernel_cargo"]
                assert all(n[k]==endpoints["empty"][k] for k in ("norm","module_sha","output"))
                for file in n["files"].values():
                    if file["kind"]=="encoded":
                        e=file["decoded"];assert e["has_LNK1"]==(key=="none" and receiver=="aware")
                        assert e["marker_v2"] and e["linked_marker"]==("/dev/null/ohm-recheck-dependent-links-v2" if e["has_LNK1"] else None)
    assert sum(len(tests)*2 for tests in switch.values())==72
    for role,tests in switch.items():
        assert len(tests)==9 and len({tuple(n["driver"]) for n in tests.values()})==1
        for phase,row in tests.items():
            assert row["receiver"]==("aware" if phase.startswith("upgrade") else role.split("-")[0])
            assert (row["warm"]["status"],row["warm"]["answer"])==(row["reference"]["status"],row["reference"]["answer"])
            assert row["images_equal"]==(True if row["warm"]["status"]==0 else None)
    app=rd("application.json.gz");assert app["archive"]==cust[1]["sha256"] and len(app["rows"])==32
    for order in ("PC","CP"):
        for role in order:
            base="objc2-cli/"+order+"/"+role
            env=app["environment"][order+"/"+role];assert not {"CI","GITHUB_ACTIONS","TF_BUILD","CARGO_INCREMENTAL","RUSTFLAGS"}&set(env)
            for label in ("edit","repeat-1","repeat-2"):
                row=app["rows"][base+"/visits/"+label];x=row["observation"]
                assert x["objc2"]==int(role=="P") and x["status"]==0 and x["verdict"]==1
                ref=app["rows"][base+"/clean-new/clean"]["product"];assert row["product"]["outcome"]==ref["outcome"] and row["product"]["native"]["norm"]==ref["native"]["norm"]
            assert app["rows"][base+"/visits/invalid"]["observation"]["status"]==101 and app["rows"][base+"/visits/repair"]["observation"]["verdict"]==1
    host=rd("host.json");assert host["conclusion"]=="success" and host["status"]=="completed"
    assert host["source"]==rd("qa-commit.json")["commit"] and host["artifact_ids"]==[a["id"] for a in rd("github.json")]
    source=rd("published-source.json")
    assert source["commits"][-1]["measured"]==st["rust-objc"]["source"] and source["commits"][-1]["compiler"]==st["rust-objc"]["compiler_tree"]
    independent=rd("independent-clocks.json.gz")
    assert independent["archive"]==cust[-1]["sha256"] and independent["clock_count"]==72
    allsets=list(combinations(range(12),6))
    for i,stage in enumerate(("screen","confirmation")):
        data=rd(stage+".json.gz");order=data["order"];n=len(order);assert data["archive"]==cust[i+2]["sha256"]
        assert (n,len(data["raw_clocks"]),len(data["typed_products"]))==((2,12,16) if i==0 else (12,72,96))
        expected=(["PC","CP"] if not i else ["PC" if idx in allsets[720] else "CP" for idx in range(12)]);assert order==expected
        times={(x["pair"],x["role"],x["phase"]):x for x in data["raw_clocks"]}
        assert len(times)==6*n and len(data["cache"])>=2*n and all(v["objects"]>0 and v["graph"]>0 for v in data["cache"])
        for name,metric in data["scores"].items():
            phases=["edit","repeat-1"] if name=="edit+repeat-1" else [name]
            pairs=[[sum(times[b,r,p]["end"]-times[b,r,p]["start"] for p in phases) for r in "PC"] for b in range(1,n+1)]
            assert metric["pairs"]==pairs and all(x>0 and y>0 for x,y in pairs)
            ratio=[x/y for x,y in pairs];assert metric["paired"]==median(ratio)
            assert [metric["median_P"],metric["median_C"]]==[median(a)/1e9 for a in zip(*pairs)]
            if n==12:
                assert metric["ci"]==[sorted(ratio)[2],sorted(ratio)[9]]
                obs=mean(math.log(v/2) for v in ratio);flips=[math.log(v/2)*(1 if r=="PC" else -1) for r,v in zip(order,ratio)]
                p=sum(sum(x if j in alloc else -x for j,x in enumerate(flips))/12>=obs-1e-12 for alloc in allsets)/924
                assert metric["p"]==p
                cross=independent["metrics"][name]
                assert [cross[k] for k in ("pairs","paired","ci","p")]==[pairs,median(ratio),metric["ci"],p] and independent["order"]==order
        s=data["scores"]["repeat-1"];assert data["twofold_primary"]==(n==12 and s["ci"][0]>2 and s["p"]<=.05)
    print("Three native receivers, 1,176 provider commands, 72 receiver transfers, 36 named-path and 12 true registry commands, 32 traced Ruff commands, and 84 ordinary clocks verified.")
    return rd("confirmation.json.gz")["scores"]["repeat-1"]
if __name__=="__main__":print(verify())
