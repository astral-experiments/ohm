"""Observe real ty_server builds separately from the counters and the paired whole-Cargo clocks."""
import argparse
import gzip
import itertools
import json
import os
from pathlib import Path

from cohort import fingerprint_sources, summarize
from cgu_inputs import same_product, witness
from measure import capture, fresh, retire, select
from study import CHILD, PARENT, ZMIJ_LIB, check_host, compress_bytes, digest, env_for, load, need, save, sdk_id, sha
from dyld import check as check_dyld
from local_dev import verify_saved
from receipt_cargo import CANDIDATE
from ty_disk import snapshot
from ty_links import A, B, E2E, CensusTrace, actual_tests, checkout, run_focus

DESIGN="ty_server e2e ordinary developer / Cargo 293 / independent private endpoints admission v2"
CMD=["cargo","+ohm","test","-p","ty_server","--test","e2e","--no-run","--locked","--offline","-j4","--message-format=json"]
PHASES=("edit","repeat-1","repeat-2")
SUBJECTS={"e2e","ty_server","zmij"}
ALLOCATION=int(digest((" ".join((DESIGN,PARENT,CHILD,CANDIDATE,A,B))).encode()), 16) % 924
P_FIRST=set(list(itertools.combinations(range(12),6))[ALLOCATION])
ORDERS={"screen":["PC","CP"],"confirmation":["PC" if x in P_FIRST else "CP" for x in range(12)]}


def subjects(root):
    provider = root/"receipts/provider-matrix/terminal.json"
    gate = load(provider)
    need(gate["passed"] and gate["commands"]==392 and not any(gate["wrong_or_image_mismatch"].values()),
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
        cross = {}
        for state in ("old","new"):
            products = {role:load(top/role/"focus"/("empty-"+state)/"clean/cgu-proof.json") for role in "PC"}
            need(all("linker_argv" in v for v in products.values()), "clean input lacks kernel linker evidence")
            cross[state] = {kind: products["P"][kind]==products["C"][kind] for kind in ("cross_path_image","modules","debug_paths")}
            save(top/("clean-cross-"+state+".json"),cross[state])
            need(all(cross[state].values()), "independent compiler roles disagree after authenticated canonicalization")
        save(top/"development-structure.json",{"subjects":enrolled,"counts":counts,"cross":cross})
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


def anchored(root, role, step):
    base=root/"receipts/ty-comparison"/role/"focus"
    phase="old" if step=="cold" else "new"
    trusted=load(base/("empty-"+phase)/"clean/verified.json")
    warm=base/"visit"/step
    with gzip.open(warm/"stdout.gz","rb") as f:
        _,signature=parse(f.read(),root/"ruff")
    return trusted["e2e"],signature


def timed(root, out, role):
    from cgu_inputs import stash
    from two_commands import combined

    repo = root/"ruff"
    work = root/"ty-focus-work"
    sdk = select(root, role)
    env = env_for(work, sdk)
    need(all(k not in env for k in ("CI","TF_BUILD","RUSTFLAGS","CARGO_ENCODED_RUSTFLAGS","CARGO_INCREMENTAL")),
         "a CI or compiler override is present")
    before = sdk_id(sdk, env)
    prior = root/"receipts/ty-comparison"/role/"focus"
    ref = load(prior/"empty-new/clean/cgu-proof.json")
    emitters = load(prior/"visit/edit/development-emitters.json")
    rows = {}
    # Each endpoint owns its installation, including the two consecutive Cargos.
    for point in ("repeat-1", "edit", "repeat-2", "edit+repeat-1"):
        check_host(root,24)
        fresh(work,root/"seed")
        target = out/point
        def validate(label, sample):
            code, data, stderr, events, metric = sample
            need(code == 0 and events is None, f"{label}: Cargo failed: {stderr[-500:]!r}")
            exe, signature = parse(data,repo)
            expected, reference = anchored(root,role,label)
            focus=lambda sig:[name for name in sig["dirty"] if name in SUBJECTS]
            need(signature["units"] == reference["units"] and focus(signature) == focus(reference),
                 "resolved graph or focused dirtiness changed")
            save(target/label/"signature.json", {"observed":signature,"reference":reference})
            return exe, signature, expected
        checkout(repo,"old")
        validate("cold", capture(CMD,repo,env,target/"cold"))
        checkout(repo,"new")
        if point == "edit+repeat-1":
            stream, clock = combined(CMD,repo,env,target)
            validate("edit",stream[0])
            step = "repeat-1"
            exe, sig, expected = validate(step, stream[1])
        else:
            for step in PHASES:
                measured = step == point
                sample = capture(CMD,repo,env,target/step,clock=measured)
                exe, sig, expected = validate(step, sample)
                if measured:
                    clock = sample[4]
                    break
        actual = actual_tests(exe,repo,env,"new",target/step)
        original = exe.read_bytes()
        physical = Path(ref["output"])
        need(physical.is_file() and (physical.samefile(exe) or sha(physical)==digest(original)),
             "promoted executable does not match the enrolled linker output")
        owned = witness(root,target/step,original,str(physical))
        chunks = [stash(root,"ty-image-chunks",original[i:i+2**20]) for i in range(0,len(original),2**20)]
        save(target/"image.json", {"sha256":digest(original),"size":len(original),"ordered_MiB_chunks":chunks})
        need(same_product(actual,expected,owned,ref), "returned e2e program or physical modules differ from independent clean")
        verify_saved(work,emitters,target)
        disk = snapshot(work,target/"steady-disk")
        need(before==sdk_id(sdk,env), "compiler or Cargo identity changed")
        rows[point]={"phase":step,"cargo":clock,"product":actual,"canonical":owned["same_path_image"],
                     "expected":expected,"raw_matches":actual==expected,"disk":disk["all"]["allocated_bytes"]}
        save(target/"point.json",rows[point])
        retire(work)
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
         "correctness":"same complete signed Mach-O after Xcode- and recipe-bound exclusive N_OSO salts, exact CGUs, full test inventory and original/repaired native inputs",
         "work_eligibility":"compare complete unit roster and all e2e, ty_server, zmij dirty states; include incidental work",
         "argv":CMD,"subjects":enrolled,"design":DESIGN})
    pairs=[]
    for pos,roles in enumerate(order,1):
        pair={role:timed(root,top/f"pair-{pos:02}"/role,role) for role in roles}
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
                where=top/"terminal-clean"/role
                product=collect(root,"focus",work,sdk,env,trace,where,"new","clean",{})
                ref=root/"receipts/ty-comparison"/role/"focus/empty-new/clean/cgu-proof.json"
                need(same_product(product,anchored(root,role,"edit")[0],load(where/"cgu-proof.json"),load(ref)),
                     "terminal independent clean executable or CGU drift")
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
