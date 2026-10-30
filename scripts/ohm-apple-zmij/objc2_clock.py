"""Measure genuine ty builds with complete binary and native input validation on Cargo #293."""
import argparse
import gzip
import itertools
import json
from pathlib import Path
import shutil

from cohort import fingerprint_sources, summarize
from crc_clock import clone
from measure import capture, fresh, retire, select
from objc2_cli import CMD, NEW, OLD, SOURCES, CliTrace, checkout, phase as trace_phase, witness
from receipt_cargo import CANDIDATE
from study import CHILD, MISSING, PARENT, RECHECK, check_host, compress_bytes, digest, env_for, load, need, save, sdk_id, sha
from ty_disk import snapshot

ENDPOINTS = ("edit","repeat-1","repeat-2")
SCORES = (*ENDPOINTS, "edit+repeat-1")
DESIGN = "objc2 normal ty CLI on exact Cargo #293 / independent inclusive 12 v1"
ALLOCATION = int(digest((" ".join((DESIGN,PARENT,CHILD,OLD,NEW,CANDIDATE))).encode()),16) % 924
FIRST = set(list(itertools.combinations(range(12),6))[ALLOCATION])
ORDERS = {"screen":["PC","CP"], "confirmation":["PC" if i in FIRST else "CP" for i in range(12)]}

def signature(stdout, root):
    messages = list(map(json.loads, stdout.splitlines()))
    need(messages[-1]=={"reason":"build-finished","success":True}, "incomplete Cargo verdict")
    units = [u for u in messages if u["reason"]=="compiler-artifact"]
    binary, = [u for u in units if u["target"]["name"]=="ty" and u["target"]["kind"]==["bin"] and u["executable"] and not u["profile"]["test"]]
    objc, = [u for u in units if u["target"]["name"]=="objc2" and u["target"]["kind"]==["lib"]]
    need(str(Path(binary["target"]["src_path"]).resolve()).startswith(str((root/"ruff/crates/ty").resolve())+"/"), "unrelated CLI")
    src = Path(objc["target"]["src_path"]).parent
    need(all(sha(src/n)==h for n,h in SOURCES.items()), "objc2 source changed")
    def key(u):
        return json.dumps([u[k] for k in ("package_id","target","profile","features","filenames","executable")],sort_keys=True,separators=(",",":"))
    roster = sorted(key(u) for u in units)
    dirty = sorted(key(u) for u in units if not u["fresh"])
    focus = [u for u in units if u is binary or u is objc or str(Path(u["target"]["src_path"])).startswith(str(root/"ruff/crates/ty")+"/")]
    info = {"roster_sha256":digest(json.dumps(roster).encode()),"count":len(roster),"dirty":dirty,
            "focus":sorted([key(u), u["fresh"]] for u in focus)}
    archive, = [Path(f) for f in objc["filenames"] if f.endswith(".rlib")]
    return Path(binary["executable"]),archive,info

def anchor(root, role, step):
    name = "old" if step=="cold" else "new"
    base = root/"receipts/objc2-cli/PC"/role
    ref = load(base/("clean-"+name)/"clean/verified.json")["product"]
    with gzip.open(base/"visits"/step/"stdout.gz","rb") as f:
        _,_,expected = signature(f.read(),root)
    return ref,expected

def timed(root, out, role):
    work = root/"objc2-work"
    sdk = select(root,role)
    env = env_for(work,sdk)
    check_host(root,24)
    fresh(work,root/"seed")
    identity = sdk_id(sdk,env)
    held = work/"clock-held"
    need(not held.exists(),"stale held outputs")
    phases = {}
    dep = None
    for step in ("cold", *ENDPOINTS):
        rev = OLD if step=="cold" else NEW
        if step in ("cold","edit"):
            checkout(root/"ruff",rev,False)
        dest = out/step
        code,stdout,stderr,events,clock = capture(CMD,root/"ruff",env,dest,clock=step!="cold")
        need(code==0 and events is None, f"unexpected Cargo failure: {stderr[-500:]!r}")
        exe,archive,typed = signature(stdout,root)
        need(exe.samefile(work/"target/debug/ty"),"different ty output")
        copy = held/step/"ty"
        clone(exe,copy)
        if dep is None:
            basename = archive.stem.removeprefix("lib")+".d"
            places = {(p.stat().st_dev,p.stat().st_ino):p for area in ("target","shared") for p in (work/area).rglob(basename)}
            dep, = places.values()
        phases[step] = (rev,dest,typed,clock,copy,dep.read_bytes())
    rows = {}
    for step,(rev,dest,typed,clock,copy,marker) in phases.items():
        ref,control = anchor(root,role,step)
        observed = witness(root,dest,copy,rev)
        need(observed==ref, "complete held CLI differs from its independent clean reference")
        need((typed['count'],typed['roster_sha256'],typed['focus'])==
             (control['count'],control['roster_sha256'],control['focus']), "complete roster or measured target freshness changed")
        need(b'objc2-0.6.3/src/' in marker and (MISSING in marker)==(role=="P") and (RECHECK in marker)==(role=="C"),"objc2 marker changed")
        row = dict(endpoint=step,signature=typed,reference=control,product=observed,expected=ref,cargo=clock,
                   depinfo=compress_bytes(dest/"objc2.dep.gz",marker))
        save(dest/"result.json",row)
        rows[step] = row
    shutil.rmtree(held)
    disk = snapshot(work,out/"steady-disk")
    need(identity==sdk_id(sdk,env), "native compiler changed")
    retire(work)
    print(role,out.parent.name,rows["repeat-1"]["cargo"]["ns"],disk["all"]["allocated_bytes"],flush=True)
    return rows

def enroll(root):
    native = load(root/"receipts/provider-matrix/terminal.json")
    need(native["passed"] and native["commands"]==392 and not any(native["wrong_or_raw_mismatch"].values()),"native protection failed")
    proof = load(root/"receipts/objc2-cli/mechanism.json")
    need(proof["command"]==CMD and set(proof["orders"])=={"PC","CP"}, "missing mirrored native reference")
    for order,study in proof["orders"].items():
        need(all(all(checks.values()) for checks in study["clean"].values()), "incorrect real CLI")
        for step in ENDPOINTS:
            need([study["physical"][r][step]["objc2"] for r in "PC"]==[1,0], "objc2 compiler work did not change")
    need(load(root/"receipts/fixed-cargo-293.json")["commit"]==CANDIDATE,"wrong Cargo pin")
    return {"compiler":[PARENT,CHILD],"cargo":CANDIDATE,"ruff":[OLD,NEW],"providers":sha(root/"receipts/provider-matrix/terminal.json"),
            "Ruff":sha(root/"receipts/objc2-cli/mechanism.json")}

def run_stage(root,mode):
    top=root/"receipts"/("objc2-clock-"+mode)
    subjects=enroll(root)
    sources=fingerprint_sources()
    order=ORDERS[mode]
    if mode=="confirmation":
        screen=load(root/"receipts/objc2-clock-screen/result.json")
        need(screen["subjects"]==subjects and screen["harness"]==sources and screen["complete"], "pilot validation missing")
    save(top/"registration.json",dict(order=order,assignment=ALLOCATION,subjects=subjects,harness=sources,argv=CMD,primary="repeat-1",
         secondary=["edit","repeat-2","edit+repeat-1"],design=DESIGN))
    pairs=[]
    for i,which in enumerate(order,1):
        pair={r:timed(root,top/f"pair-{i:02}"/r,r) for r in which}
        for arm in pair.values():
            clocks = [arm[k]["cargo"] for k in ENDPOINTS[:2]]
            arm["edit+repeat-1"]={"cargo":{k:clocks[0][k]+clocks[1][k] for k in ("ns","user","system","instructions") if all(k in v for v in clocks)}}
        pairs.append(pair)
    metrics={"monotonic_ns":summarize(pairs,order,endpoints=SCORES)}
    cal=load(root/"receipts/calibration/result.json")
    if cal["tree_CPU_calibrated"]:
        for pair in pairs:
            for arm in pair.values():
                for k in SCORES:
                    clock=arm[k]["cargo"]
                    clock["cpu"]=clock["user"]+clock["system"]
        metrics["tree_cpu_seconds"]=summarize(pairs,order,"cpu",SCORES)
    if cal["retired_instruction_scope"]=="whole-tree-calibrated":
        metrics["retired_instructions"]=summarize(pairs,order,"instructions",SCORES)
    primary=metrics["monotonic_ns"]["repeat-1"]
    if mode=="confirmation":
        trace=CliTrace()
        try:
            trace.ready()
            work=root/"objc2-work"
            for role in "CP":
                sdk=select(root,role)
                env=env_for(work,sdk)
                fresh(work,root/"seed")
                checkout(root/"ruff",NEW,False)
                row=trace_phase(root,work,sdk,env,top/"terminal-clean"/role,"clean",NEW,trace)
                need(row["product"]==anchor(root,role,"edit")[0],"terminal independent empty CLI changed")
                retire(work)
        finally:
            trace.close()
    qualifies=mode=="confirmation" and primary["median_CI_96.14pct"][0]>2 and primary["one_sided_balanced_sharp_2x_p"]<=.05
    save(top/"result.json",dict(complete=True,twofold_first_repeat=qualifies,harness=sources,subjects=subjects,order=order,
         metrics=metrics,counter_calibration=cal["retired_instruction_scope"]))
    print(mode,primary,flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=ORDERS)
    parser.add_argument("root",type=Path)
    args=parser.parse_args()
    run_stage(args.root.resolve(strict=True),args.mode)
