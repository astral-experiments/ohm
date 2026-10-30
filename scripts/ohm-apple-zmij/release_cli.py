"""Compare shipped and integrated Cargo with exactly the same published #281 Rust and stable build paths."""
from pathlib import Path
import argparse,itertools,json,os,sys
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import cgu_inputs
from cohort import fingerprint_sources,summarize
from measure import fresh,retire,select
from objc2_cli import CMD,OLD,NEW,CliTrace,checkout,installation,phase as trace_phase
from objc2_clock import ENDPOINTS,SCORES,anchor,timed
from release_bins import selected
from release_import import SHA as MERGED
from study import CHILD,CARGO_SOURCE,digest,env_for,load,need,save,sha
from versioned_select import AWARE,choose,current
DESIGN="Signed #294 vs release-integrated fd55, one exact published #281 ObjC Rust, independent Apple developer ty installations v1"
INDEX=int(digest((" ".join((DESIGN,CARGO_SOURCE,AWARE,CHILD,OLD,NEW))).encode()),16)%924
FIRST=set(list(itertools.combinations(range(12),6))[INDEX])
ORDER={"screen":["PC","CP"],"confirmation":["PC" if n in FIRST else "CP" for n in range(12)]}
NAMES={"P":"signed","C":"aware"}
def ref(root,role):
    return root/"receipts/release-cli/PC"/role/"C"
def pick(root,role):
    o=choose(root,NAMES[role]);s=select(root,"C")
    assert o["source"]=={"P":CARGO_SOURCE,"C":AWARE}[role] and (s/"bin/cargo").samefile(root/("signed/bin/cargo" if role=="P" else "cargo-aware"))
    assert sha(next((s/"lib").glob("librustc_driver*.dylib")))==load(root/"receipts/pair.json")["products"]["C"]["runtime"][next(n for n in load(root/"receipts/pair.json")["differ"] if "rustc_driver" in n)]
    return s
def gate(root):
    a=root/"receipts"; i=load(a/"cargo-aware/import.json");assert i["selected"]==MERGED
    assert load(a/"versioned/terminal.json")["passed"] and not load(a/"versioned/legacy/terminal.json")["signed_integrated_differences"]
    c=load(a/"objc2-cli/mechanism.json");assert set(c["orders"])=={"PC","CP"}
    for o in c["orders"].values():assert all(all(x.values()) for x in o["clean"].values())
    return {"signed_cargo":CARGO_SOURCE,"signed_bytes":load(a/"release.json")["cargo"]["sha256"],"integrated_cargo":AWARE,"integrated_bytes":MERGED,
            "rust":CHILD,"qualified_rust":load(a/"pair.json")["products"]["C"]["source"],"ruff":[OLD,NEW],
            "provider_v2":sha(a/"versioned/terminal.json"),"provider_v1":sha(a/"versioned/legacy/terminal.json"),
            "unicode":i["artifacts"]["unicode"]["archive"],"compiler_only_rosters":sha(a/"objc2-cli/mechanism.json")}
def mechanism(root):
    subjects=gate(root);assert subjects["qualified_rust"]==CHILD and (root/"release-cargo-bins/frozen.json").is_file()
    folder=root/"receipts/release-cli";trace=CliTrace();trace.ready();orders={}
    try:
        for order in ("PC","CP"):
            results={}
            for logical in order:
                sdk=pick(root,logical);prefix=folder/order/logical
                facts,comparisons=installation(root,"C",trace,prefix)
                assert all(comparisons.values())
                for step,b in facts.items():
                    row=load(prefix/"C/visits"/step/"verified.json")
                    assert all(not e["hard"] and e["recheck"] and not e["v1_rule"] for e in row["objc2"])
                    if step in ("cold","edit","repair"):assert row["code"]==0
                results[logical]={"physical":facts,"clean":comparisons,"cargo":current(root)}
            cross={}
            for flavour in ("clean-old","clean-new"):
                p,c=[load(folder/order/r/"C"/flavour/"clean/verified.json") for r in "PC"]
                assert p["product"]["stdout"]==c["product"]["stdout"] and p["product"]["stderr"]==c["product"]["stderr"] and p["product"]["exit"]==c["product"]["exit"]
                assert p["cgu"]["cross_path_image"]==c["cgu"]["cross_path_image"] and p["cgu"]["modules"]==c["cgu"]["modules"],"unexplained cross-Cargo native program or root object"
                cross[flavour]=p["cgu"]["cross_path_image"]
            for repeat in ("repeat-1","repeat-2"):
                p,c=[results[r]["physical"][repeat] for r in "PC"]
                assert p["objc2"]==1 and c["objc2"]==0 and p["rustc"]>c["rustc"] and c["ld"]<=p["ld"],(order,repeat,p,c)
            orders[order]={"roles":results,"cross":cross};save(folder/(order+"-closed.json"),orders[order])
    finally:trace.close()
    save(folder/"terminal.json",{"subjects":subjects,"orders":orders,"command":CMD})
def workload(root,mode):
    top=root/"receipts"/("release-clock-"+mode);g=gate(root)
    registration={"subjects":g,"sources":fingerprint_sources(),"native_gate":sha(root/"receipts/release-cli/terminal.json"),
                  "root_argv":CMD,"order":ORDER[mode],"allocation":INDEX,"design":DESIGN,"first_unchanged_primary":True}
    if mode=="confirmation":
        before=load(root/"receipts/release-clock-screen/terminal.json")
        assert before["admit_confirmation"] and before["registration"]["subjects"]==g and before["registration"]["sources"]==registration["sources"]
    save(top/"registration.json",registration)
    pairs=[]
    for i,order in enumerate(ORDER[mode],1):
        pair={}
        for r in order:
            sdk=pick(root,r);out=top/f"pair-{i:02d}"/r
            save(out/"cargo-selection.json",current(root))
            arm=pair[r]=timed(root,out,"C",ref(root,r))
            summed=[arm[k]["cargo"] for k in ENDPOINTS[:2]]
            arm["edit+repeat-1"]={"cargo":{k:sum(q[k] for q in summed) for k in ("ns","user","system","instructions") if all(k in q for q in summed)}}
        pairs.append(pair)
    metrics={"monotonic_ns":summarize(pairs,ORDER[mode],endpoints=SCORES)}
    calibr=load(root/"receipts/calibration/result.json")
    if calibr["tree_CPU_calibrated"]:
        for pair in pairs:
            for arm in pair.values():
                for k in SCORES:
                    s=arm[k]["cargo"];s["cpu"]=s["user"]+s["system"]
        metrics["tree_CPU"]=summarize(pairs,ORDER[mode],"cpu",SCORES)
    if calibr["retired_instruction_scope"]=="whole-tree-calibrated":
        metrics["retired_instructions"]=summarize(pairs,ORDER[mode],"instructions",SCORES)
    primary=metrics["monotonic_ns"]["repeat-1"]
    if mode=="confirmation":
        tr=CliTrace();tr.ready();work=root/"objc2-work"
        try:
            for r in "CP":
                sdk=pick(root,r);environment=env_for(work,sdk);fresh(work,root/"seed");checkout(root/"ruff",NEW,False)
                row=trace_phase(root,work,sdk,environment,top/"terminal-clean"/r,"clean",NEW,tr)
                expected=anchor(root,"C","edit",ref(root,r))[0]
                assert cgu_inputs.same_product(row["product"],expected["product"],row["cgu"],expected["cgu"])
                retire(work)
        finally:tr.close()
    admit=mode=="screen" and min(primary["ratios_P_over_C"])>2.0
    success=mode=="confirmation" and primary["median_CI_96.14pct"][0]>2.0 and primary["one_sided_balanced_sharp_2x_p"]<=0.05
    save(top/"terminal.json",{"registration":registration,"metrics":metrics,"admit_confirmation":admit,"twofold_qualified":success,
         "counter":calibr["retired_instruction_scope"]})
    if mode=="screen" and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"],"a") as d:d.write("admitted="+str(admit).lower()+"\n")
    print(mode,primary,flush=True)
if __name__=="__main__":
    x=argparse.ArgumentParser();x.add_argument("mode",choices=("native","screen","confirmation"));x.add_argument("where",type=Path)
    q=x.parse_args();r=q.where.resolve()
    mechanism(r) if q.mode=="native" else workload(r,q.mode)
