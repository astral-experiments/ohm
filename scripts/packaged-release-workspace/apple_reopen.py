"""Reopen original whole Mach-Os, raw kernel exec/held arguments, receipts and real e2e verdicts."""
from __future__ import annotations
import json
import re
import sys
from collections import Counter,defaultdict
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent/"ohm-apple-zmij")]
from apple import A,B,PROVIDER,RUST,SUBJECTS,VISITS
from packages import CARGO,RELEASES,need
from study import digest,save
import libm_workspace_readback as lib
import reopen_cgu
from workspace_images import compare
from response_custody import resolved

def logical(unit):
    pkg,name,kind=unit;need(pkg.startswith("path+file:") and "/ruff/" in pkg,"foreign workspace unit "+pkg)
    return (pkg.split("/ruff/",1)[1].split("#",1)[0],name,tuple(kind))

def key(unit):
    d,n,k=logical(unit);return "|".join([d,n,",".join(k)])

def scan(c,base,tools,roster):
    original=json.loads(c.packed(base+"/exec.json.gz"))
    events=list(resolved(original))
    outputs={lib.logical_path(physical):v for physical,v in c.json(base+"/verified.json")["binary_roster"].items()}
    need(len({e["seq"] for e in events})==len(events),"repeated ES sequence")
    before={};rustcs=[];links=[];cargo=[]
    for e in events:
        p,a=e["path"],e["argv"]
        if p==tools["cargo"]["physical"] and "test" in a:
            need((e.get("cdhash") or "").lower()==tools["cargo"]["cdhash"],"foreign Cargo")
            cargo.append(e["pid"])
        if p==tools["rustc"]["physical"] and "--crate-name" in a:
            need((e.get("cdhash") or "").lower()==tools["rustc"]["cdhash"],"foreign rustc")
            cr=a[a.index("--crate-name")+1]
            if cr!="___" or not any(v=="--print" or v.startswith("--print=") for v in a):
                mode="link-only" if any("link-only" in x for x in a) else "full"
                rustcs.append([e["pid"],e["seq"],cr,mode])
        if Path(p).name in ("ld","ld-classic","ld64","ld-prime","ld.lld","wild","rust-lld"):
            need(p==tools["ld"]["physical"] and e["cdhash"].lower()==tools["ld"]["cdhash"],"unregistered Apple linker")
            parent=before.get(e["ppid"])
            need(parent and parent["path"]==tools["clang"]["physical"] and
                 parent["cdhash"].lower()==tools["clang"]["cdhash"],"missing real Xcode clang parent")
            chain=[parent]
            while (parent:=before.get(chain[-1]["ppid"])) and len(chain)<24:
                chain.append(parent)
            rs=next((j for j in chain if j["path"]==tools["rustc"]["physical"] and "--crate-name" in j["argv"]),None)
            pos=lib.logical_path(reopen_cgu.link_output(a));q=outputs.get(pos)
            links.append({"pid":e["pid"],"seq":e["seq"],"clang_pid":chain[0]["pid"],"cdhash":e["cdhash"],
                          "output":pos,"returned_test":key(q["unit"]) if q else None,"rustc_pid":rs["pid"] if rs else None,
                          "rustc":rs["argv"][rs["argv"].index("--crate-name")+1] if rs else None,
                          "held_response":bool(e.get("xcode_response"))})
        before[e["pid"]]=e
    q=c.json(base+"/verified.json")
    need(len(cargo)==1 and len(links)==len(q["native"]["linkers"]) and
         sorted(a[2] for a in rustcs if a[-1]=="full")==q["native"]["full"] and
         sorted(a[2] for a in rustcs if a[-1]=="link-only")==q["native"]["link_only"],"kernel stopped-work census differs")
    return {"all_xcode_ld":len(links),"returned_test_links":sum(x["returned_test"] is not None for x in links),
            "xcode_pids":links,"full_rustcs":sum(v[-1]=="full" for v in rustcs),
            "link_only_rustcs":sum(v[-1]=="link-only" for v in rustcs),"rustc_pids":rustcs,
            "linked_tests":sorted(x["returned_test"] for x in links if x["returned_test"]),
            "returned_tests":sorted(key(u) for u in roster)}

def verify(c):
    enrolled=c.json("packaged-workspace.json")
    need(enrolled["source"]==[A,B] and enrolled["wall_metric"] is False and enrolled["provider_sha256"]==PROVIDER,"changed protocol")
    reopen_cgu.program=lib.raw_image
    bodies=set()
    for name in sorted(c.names):
        if name.startswith("workspace-returned-images/images/") and name.endswith(".json"):
            q=c.json(name);lib.raw_image(c,q["raw"]);bodies.add((q["raw"],q["bytes"],tuple(q["text"])))
    need(bodies,"no original native images")
    proofs={name:reopen_cgu.verify(c,name) for name in c.proofs}
    results={};same_fails=[];math=0
    for symbol,role in SUBJECTS.items():
        sdk=c.json(role+"/custody.json"); installed=c.json(role+"/installed.json");tools=c.json(role+"/physical-tools.json")
        need(sdk["source"]["release_id"]==RELEASES[role][0] and sdk["archive_sha256"]==RELEASES[role][2]["aarch64-apple-darwin"][2] and
             sdk["provenance"]["sources"]["rust"]["revision"]==RUST[role] and
             sdk["provenance"]["sources"]["cargo"]["revision"]==CARGO,"not the enrolled published archives")
        for n,t in tools.items():
            need(re.fullmatch(r"(?i)[a-f0-9]{40}",t["cdhash"]) and re.search(r"(?im)^CDHash="+t["cdhash"]+"$",t["codesign"]) and
                 (n not in ("cargo","rustc") or t["sha256"]==installed["bin/"+n]),"uncertified actual tool")
        current={};rosters={}
        for sequence,visits in (("empty-old",[("clean","old")]),("visit",VISITS),("empty-new",[("clean","new")])):
            history={}
            for visit,state in visits:
                base=f"{lib.ROOT}/{symbol}/{sequence}/{visit}"
                stage=visit if sequence=="visit" else "clean-"+state
                r,typed,count=lib.compare_phase(c,base,state,symbol,history,bodies,proofs)
                math+=count; rosters[stage]=r;current[stage]=scan(c,base,tools,r)
                if r:
                    need(len(r)==83 and len(current[stage]["returned_tests"])==len(set(current[stage]["returned_tests"]))==83,"wrong unique 83-program receipt")
                    current[stage].update(e2e_links=c.json(base+"/verified.json")["e2e_links"],
                                          e2e_sha=typed["raw"],e2e_catalog=len(typed["inventory"]))
        for stage,state in [("clean-old","old"),*VISITS,("clean-new","new")]:
            if state=="bad":continue
            actual=rosters[stage];ref=rosters["clean-"+state];need(set(actual)==set(ref),"changed logical roster")
            statuses=Counter()
            for unit,z in actual.items():
                status=compare(z["proof"],ref[unit]["proof"])
                statuses[status]+=1
                if status not in ("exact","authenticated-local-names"):same_fails.append([role,stage,key(unit),status])
            current[stage]["own_clean_status"]=dict(statuses)
            own=current["clean-"+state]
            need(current[stage]["e2e_catalog"]==own["e2e_catalog"],"wrong e2e inventory")
        need(current["edit"]["e2e_links"]==1 and current["clean-old"]["e2e_sha"]!=current["clean-new"]["e2e_sha"],"real change did not move the physical e2e output")
        results[role]=current
    delta={}
    for phase,_ in VISITS:
        a,b=(results[v][phase] for v in ("20","21"))
        aa,bb=set(a["linked_tests"]),set(b["linked_tests"])
        need(a["returned_tests"]==b["returned_tests"] or phase=="invalid","release logical test inventory changed")
        delta[phase]={"skipped_on_21":sorted(aa-bb),"persisted_on_both":sorted(aa&bb),"added_on_21":sorted(bb-aa)}
    need(c.json("workspace-collection.json")["all_same_role_programs_admitted"]==(not same_fails),"hosted/independent native acceptance differs")
    prior=json.loads((HERE/"previous-apple-83.json").read_bytes())
    earlier={}
    for phase,roles in prior["phases"].items():
        earlier[phase]={}
        for historic,h in roles.items():
            previous=set(h["linked_returned_tests"])
            earlier[phase][historic]={}
            for role in ("20","21"):
                actual=set(results[role][phase]["linked_tests"])
                earlier[phase][historic][role]={"previous_only":sorted(previous-actual),"still_links":sorted(previous&actual),
                                               "now_only":sorted(actual-previous)}
    return {"subjects":RUST,"source":[A,B],"ordinary":True,"timed":False,"whole_images":len(bodies),
            "previous_apple_293_artifact":prior["zip_sha256"],"previous_apple_293_linked_sets":earlier,
            "actual_cgu_certificates":len(proofs),"math_artifact_consumers":math,"phases":results,
            "same_release_clean_failures":same_fails,"paired_returned_test_sets":delta}

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("source",type=Path);parser.add_argument("--record",action="store_true");a=parser.parse_args()
    c=lib.Corpus(a.source);q=verify(c)
    if a.record:save(a.source/"independent-apple-workspace.json",q)
    else:need(q==c.json("independent-apple-workspace.json"),"archive replay differs from hosted verifier")
    print("raw outputs",q["whole_images"],"separate same-release failures",len(q["same_release_clean_failures"]),flush=True)
    for r,ph in q["phases"].items():print(r,[(k,v["all_xcode_ld"],v["returned_test_links"],v["full_rustcs"],v["link_only_rustcs"]) for k,v in ph.items()])
    need(not q["same_release_clean_failures"],"one or more own-clean binaries remain unqualified")
