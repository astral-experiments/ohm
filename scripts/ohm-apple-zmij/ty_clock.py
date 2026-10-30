"""Observe real ty_server builds separately from the counters and the paired whole-Cargo clocks."""
import argparse
import ctypes
import gzip
import hashlib
import itertools
import json
import os
from pathlib import Path
import shutil
import zipfile

from cohort import fingerprint_sources, summarize
from measure import capture, fresh, retire, select
from study import CHILD, PARENT, ZMIJ_LIB, check_host, compress_bytes, digest, env_for, load, need, save, sdk_id, sha
from ty_compare import run_pair_focus
from ty_disk import snapshot
from ty_links import A, B, E2E, CensusTrace, actual_tests, checkout

MECHANISM_SHA="795507e5d0bf58e49b4cbb4050fa65e1c62097ec69502b8e7655f9686b427121"
CMD=["cargo","+ohm","test","-p","ty_server","--test","e2e","--no-run","--locked","--offline","-j4","--message-format=json"]
PHASES=("edit","repeat-1","repeat-2")
SUBJECTS={"e2e","ty_server","zmij"}
ALLOCATION=int(digest(("ty_server e2e/native v1/"+MECHANISM_SHA).encode()), 16) % 924
P_FIRST=set(list(itertools.combinations(range(12),6))[ALLOCATION])
ORDERS={"screen":["PC","CP"],"confirmation":["PC" if x in P_FIRST else "CP" for x in range(12)]}


def enroll(original, out):
    need(sha(original)==MECHANISM_SHA, "wrong focused artifact")
    with zipfile.ZipFile(original) as z:
        need(not z.testzip() and len(z.namelist())==len(set(z.namelist())), "damaged prior native receipts")
        for role in "PC":
            base="ty-comparison/"+role+"/focus/"
            clean={s:json.loads(z.read(base+"empty-"+s+"/clean/verified.json"))["e2e"] for s in ("old","new")}
            for step in ("edit","repeat-1","repeat-2","invalid","repair"):
                where=base+"visit/"+step+"/"
                row=json.loads(z.read(where+"verified.json"))
                native=gzip.decompress(z.read(where+"exec.json.gz"))
                stream=gzip.decompress(z.read(where+"stdout.gz"))
                need(digest(native)==row["streams"]["native_events"] and digest(stream)==row["streams"]["stdout"],"changed physical or Cargo stream")
                raw=json.loads(native); cargo=list(map(json.loads,stream.splitlines()))
                ok=step!="invalid"
                need(cargo[-1]=={"reason":"build-finished","success":ok} and row["exit"]==(0 if ok else 101),"unverified verdict")
                rustcs=[e["argv"][e["argv"].index("--crate-name")+1] for e in raw if e["path"].endswith("/native/bin/rustc") and "--crate-name" in e["argv"]]
                links=[e for e in raw if e["path"].endswith("/XcodeDefault.xctoolchain/usr/bin/ld")]
                if step.startswith("repeat"):
                    need(sorted(rustcs)==(["e2e","zmij"] if role=="P" else []) and len(links)==int(role=="P"),"prior focused subject not qualified")
                elif ok:
                    need("e2e" in rustcs and "ty_server" in rustcs and len(links)==1,"missing actual edit and repair link")
                else:
                    need(not links and b"E0425" in stream,"previous invalid edit passed")
                if ok:
                    need(row["e2e"]==clean["new"],"prior executable drifted from clean")
                    if links:
                        output,=[v for a,v in zip(links[0]["argv"],links[0]["argv"][1:]) if a=="-o"]
                        need(row["binary_roster"][output]["sha"]==clean["new"]["raw"],"wrong linker output")
        save(out,{"artifact":"12978505922","zip":MECHANISM_SHA,"compilers":[PARENT,CHILD],"ruff":[A,B]})


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
    disk=snapshot(work,out/"steady-disk")
    need(identity==sdk_id(sdk,env),"subject compiler changed")
    retire(work)
    print("verified",role,out.parent.name,"first unchanged ns",rows["repeat-1"]["cargo"]["ns"],"bytes",disk["all"]["allocated_bytes"],flush=True)
    return rows


def run_stage(root, mode):
    top=root/"receipts"/("ty-clock-"+mode)
    order=ORDERS[mode]
    harness=fingerprint_sources()
    need(load(root/"receipts/ty-clock-enroll.json")["zip"]==MECHANISM_SHA,"wrong prior experiment")
    if mode=="confirmation":
        pilot=load(root/"receipts/ty-clock-screen/result.json")
        need(pilot["passed"] and pilot["harness"]==harness,"independent pilot gate")
    save(top/"registration.json",{"order":order,"assignment":ALLOCATION,"harness":harness,"primary":PHASES[1],
         "secondary":[PHASES[0],PHASES[2]],"correctness":"all raw Mach-O files, complete inventory, actual old/new test, stable exact driver; two native controls",
         "work_eligibility":"fixed complete unit graph and dirty states for e2e, ty_server, zmij; retain and charge unrelated compiler work in either arm",
         "argv":CMD,"sources":[PARENT,CHILD,A,B],"unscored_prior":MECHANISM_SHA,
         "disk":"Both isolated roots after the last clock; hardlinks charged once, APFS extents across different inodes can be shared."})
    if mode=="screen":
        trace=CensusTrace()
        try:
            trace.ready()
            run_pair_focus(root,trace)
        finally:
            trace.close()
    pairs=[]
    for pos,roles in enumerate(order,1):
        pair={role:timed(root,top/f"pair-{pos:02}"/role,role) for role in roles}
        pairs.append(pair)
    result=summarize(pairs,order)
    first=result["repeat-1"]
    passed=(min(first["ratios_P_over_C"])>2 if mode=="screen" else
            first["median_CI_96.14pct"][0]>2 and first["one_sided_balanced_sharp_2x_p"]<=0.05)
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
    save(top/"result.json",{"passed":passed,"harness":harness,"elapsed":result,"order":order,"source":[PARENT,CHILD]})
    print(mode,first,flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=("enroll","screen","confirmation"))
    parser.add_argument("root",type=Path)
    args=parser.parse_args(); root=args.root.resolve(strict=True)
    if args.mode=="enroll":
        enroll(root/"mechanism-ty.zip",root/"receipts/ty-clock-enroll.json")
    else:
        run_stage(root,args.mode)
