"""Observe real ty_server builds separately from the counters and the paired whole-Cargo clocks."""
import argparse
import ctypes
import gzip
import itertools
import json
import os
from pathlib import Path
import shutil

from cohort import fingerprint_sources, summarize
from measure import capture, fresh, retire, select
from study import CHILD, PARENT, ZMIJ_LIB, check_host, compress_bytes, digest, env_for, load, need, save, sdk_id, sha
from dyld import check as check_dyld
from local_dev import verify_saved
from receipt_cargo import CANDIDATE
from ty_disk import snapshot
from ty_links import A, B, E2E, CensusTrace, actual_tests, checkout, run_focus

DESIGN="ty_server e2e real developer incremental on physical Cargo 293 / 2+12 v1"
CMD=["cargo","+ohm","test","-p","ty_server","--test","e2e","--no-run","--locked","--offline","-j4","--message-format=json"]
PHASES=("edit","repeat-1","repeat-2")
SUBJECTS={"e2e","ty_server","zmij"}
ALLOCATION=int(digest((" ".join((DESIGN,PARENT,CHILD,CANDIDATE,A,B))).encode()), 16) % 924
P_FIRST=set(list(itertools.combinations(range(12),6))[ALLOCATION])
ORDERS={"screen":["PC","CP"],"confirmation":["PC" if x in P_FIRST else "CP" for x in range(12)]}


def subjects(root):
    provider = root/"receipts/provider-matrix/terminal.json"
    gate = load(provider)
    need(gate["passed"] and gate["commands"]==392 and not any(gate["wrong_or_raw_mismatch"].values()),
         "native provider safety gate failed")
    need(load(root/"receipts/fixed-cargo-293.json")["commit"]==CANDIDATE,"different Cargo")
    return {"cargo":CANDIDATE,"rust":[PARENT,CHILD],"ruff":[A,B],"native_controls":sha(provider)}


def structural(root):
    enrolled = subjects(root)
    top = root/"receipts/ty-comparison"
    trace=CensusTrace()
    refs={}
    counts={}
    try:
        trace.ready()
        for role in "PC":
            check_dyld(root,role,select(root,role),top/role/"dyld")
            refs[role]=run_focus(root,trace,role)
            counts[role]={}
            for phase in ("cold","edit","repeat-1","repeat-2","invalid","repair"):
                x=load(top/role/"focus/visit"/phase/"verified.json")
                counts[role][phase]={"rustcs":x["native"]["full"],"link_only":x["native"]["link_only"],
                                     "real_ld":len(x["native"]["linkers"]),"e2e_ld":x["e2e_links"]}
        for state in ("old","new"):
            need(all(refs["P"][state][key] == refs["C"][state][key] for key in ("text","inventory")),
                 "independent clean compiler roles disagree on instructions or tests")
        save(top/"development-structure.json",{"subjects":enrolled,"counts":counts})
    finally:
        trace.close()


def parse(stream, repo):
    messages=list(map(json.loads,stream.splitlines()))
    need(messages[-1]=={"reason":"build-finished","success":True}, "unsuccessful Cargo stream")
    arts=[m for m in messages if m["reason"]=="compiler-artifact"]
    e2e,=[a for a in arts if a["profile"]["test"] and a["executable"] and Path(a["target"]["src_path"]).resolve()==(repo/E2E).resolve()]
    zmij,=[a for a in arts if a["target"]["name"]=="zmij" and a["target"]["kind"]==["lib"]]
    need(len(arts)==304 and sha(zmij["target"]["src_path"])==ZMIJ_LIB, "source or resolved graph changed")
    roster=sorted(json.dumps([a[k] for k in ("package_id","target","features","profile")],sort_keys=True,separators=(",",":")) for a in arts)
    return Path(e2e["executable"]),{"units":digest(json.dumps(roster).encode()),"dirty": sorted(a["target"]["name"] for a in arts if not a["fresh"])}


def hold(source, dest):
    dest.parent.mkdir(parents=True)
    clone=ctypes.CDLL(None,use_errno=True).clonefile
    clone.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint32]
    need(clone(os.fsencode(source),os.fsencode(dest),0)==0,"APFS snapshot failed")


def anchored(root, role, step):
    base=root/"receipts/ty-comparison"/role/"focus"
    phase="old" if step=="cold" else "new"
    trusted=load(base/("empty-"+phase)/"clean/verified.json")
    warm=base/"visit"/step
    with gzip.open(warm/"stdout.gz","rb") as f:
        _,signature=parse(f.read(),root/"ruff")
    return trusted["e2e"],signature


def timed(root, out, role):
    check_host(root, 24)
    repo=root/"ruff"
    work=root/"ty-focus-work"
    sdk=select(root,role)
    env=env_for(work,sdk)
    fresh(work,root/"seed")
    identity=sdk_id(sdk,env)
    held=work/"held"
    need(not held.exists(), "stale endpoint snapshots")
    snapshot_rows={}
    phases=("cold",*PHASES)
    for step in phases:
        if step in ("cold","edit"):
            checkout(repo, "old" if step=="cold" else "new")
        target=out/step
        code,data,stderr,events,clock=capture(CMD,repo,env,target,clock=step!="cold")
        need(code==0 and events is None, f"timed Cargo failed: {stderr[-500:]!r}")
        exe,sig=parse(data,repo)
        copy=held/step/exe.name
        hold(exe,copy)
        snapshot_rows[step]=(copy,sig,clock)
    # Heavy result readers, linked tests and filesystem walks all follow the last clock.
    rows={}
    for step,(copy,sig,clock) in snapshot_rows.items():
        expected, baseline=anchored(root,role,step)
        observed=actual_tests(copy,repo,env,"old" if step=="cold" else "new",out/step)
        subject=lambda signature: [name for name in signature["dirty"] if name in SUBJECTS]
        check={"expected":expected,"observed":observed,"reference_signature":baseline,"actual_signature":sig,
               "whole_image_equal":observed==expected,"roster_equal":sig["units"]==baseline["units"],
               "subject_equal":subject(sig)==subject(baseline)}
        save(out/step/"validation.json",check)
        if not check["whole_image_equal"]:
            compress_bytes(out/step/"unexpected-program.macho.gz",copy.read_bytes())
        need(check["whole_image_equal"],"native program differs from independent clean, raw failing Mach-O retained")
        need(check["roster_equal"] and check["subject_equal"],"resolved graph or focused compiler work changed")
        row={"endpoint":step,"signature":sig,"product":observed,"cargo":clock}
        save(out/step/"result.json",row)
        rows[step]=row
    shutil.rmtree(held)
    proof=load(root/"receipts/ty-comparison"/role/"focus/visit/edit/development-emitters.json")
    verify_saved(work,proof,out)
    disk=snapshot(work,out/"steady-disk")
    need(identity==sdk_id(sdk,env),"subject compiler changed")
    retire(work)
    print("verified",role,out.parent.name,"first unchanged ns",rows["repeat-1"]["cargo"]["ns"],"bytes",disk["all"]["allocated_bytes"],flush=True)
    return rows


def run_stage(root, mode):
    top=root/"receipts"/("ty-clock-"+mode)
    order=ORDERS[mode]
    harness=fingerprint_sources()
    enrolled=subjects(root)
    proof=load(root/"receipts/ty-comparison/development-structure.json")
    need(proof["subjects"]==enrolled, "foreign physical structural run")
    if mode=="confirmation":
        pilot=load(root/"receipts/ty-clock-screen/result.json")
        need(pilot["complete"] and pilot["harness"]==harness and pilot["subjects"]==enrolled,
             "independent pilot validation missing")
    save(top/"registration.json",{"order":order,"assignment":ALLOCATION,"harness":harness,
         "primary":"repeat-1","secondary":["edit","repeat-2","edit+repeat-1"],
         "correctness":"clean whole Mach-O, full inventory, old/new e2e, real native providers",
         "work_eligibility":"compare complete unit roster and all e2e, ty_server, zmij dirty states; include incidental work",
         "argv":CMD,"subjects":enrolled,"design":DESIGN})
    pairs=[]
    for pos,roles in enumerate(order,1):
        pair={role:timed(root,top/f"pair-{pos:02}"/role,role) for role in roles}
        for role,arm in pair.items():
            visits=[arm[phase]["cargo"] for phase in ("edit","repeat-1")]
            arm["edit+repeat-1"]={"cargo":{k:sum(v[k] for v in visits) for k in ("ns","user","system","instructions") if all(k in v for v in visits)}}
        pairs.append(pair)
    endpoints=(*PHASES,"edit+repeat-1")
    result=summarize(pairs,order,endpoints=endpoints)
    counts={}
    calibration=load(root/"receipts/calibration/result.json")
    if calibration["tree_CPU_calibrated"]:
        for pair in pairs:
            for arm in pair.values():
                for name in endpoints:
                    clock=arm[name]["cargo"]
                    clock["cpu"]=clock["user"]+clock["system"]
        counts["tree_cpu_seconds"]=summarize(pairs,order,"cpu",endpoints)
    if calibration["retired_instruction_scope"]=="whole-tree-calibrated":
        counts["retired_instructions"]=summarize(pairs,order,"instructions",endpoints)
    first=result["repeat-1"]
    passed=mode=="confirmation" and first["median_CI_96.14pct"][0]>2 and first["one_sided_balanced_sharp_2x_p"]<=0.05
    if mode=="confirmation":
        # Post-clock, separately empty B using the same role and namespace again.
        trace=CensusTrace()
        try:
            trace.ready()
            from ty_links import collect
            work=root/"ty-focus-work"
            for role in "CP":
                sdk=select(root,role); env=env_for(work,sdk)
                fresh(work,root/"seed"); checkout(root/"ruff","new")
                product=collect(root,"focus",work,sdk,env,trace,top/"terminal-clean"/role,"new","clean")
                need(product==anchored(root,role,"edit")[0], "terminal independent clean executable drift")
                retire(work)
        finally:
            trace.close()
    save(top/"result.json",{"complete":True,"twofold_first_repeat":passed,"harness":harness,"subjects":enrolled,"elapsed":result,"counts":counts,"order":order,"counter_calibration":calibration["retired_instruction_scope"]})
    print(mode,first,flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=("structure","screen","confirmation"))
    parser.add_argument("root",type=Path)
    args=parser.parse_args(); root=args.root.resolve(strict=True)
    if args.mode=="structure":
        structural(root)
    else:
        run_stage(root,args.mode)
