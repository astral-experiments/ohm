"""Two whole-Cargo hardware histories per fresh boot. Validate real programs after the clock closes."""
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

HERE=Path(__file__).resolve().parent
SRC=HERE.parent/"ruff-integration-structure"
sys.path[:0]=[str(HERE),str(SRC)]
import admission
import run as s

b,w,kit,native=s.b,s.historical,s.kit,s.native
need,save=s.b.need,s.b.save
OUT,ROOT,WORK=b.OUT,b.ROOT,b.WORK
BRANCH="charlie/qa-ruff-integration-ordinary-pmu-20261031"
ORDERS={"01":("Foff","Fon"),"02":("Fon","Foff")}


def enter(position,source,calibrator,observers):
    head=os.environ["GITHUB_SHA"]
    need(os.environ["GITHUB_REPOSITORY"]==b.REPO and os.environ["GITHUB_REF"]=="refs/heads/"+BRANCH and
         os.environ["GITHUB_RUN_ATTEMPT"]=="1" and os.environ["REVIEWED_HEAD"]==head==b.git(HERE,"rev-parse","HEAD") and
         position in ORDERS,"wrong review head, branch, slot or repeat")
    need(b.git(HERE,"rev-parse","HEAD:scripts/ruff-integration-structure","HEAD:scripts/branch-return-pmu",
               "HEAD:scripts/ohm-packed-ruff").splitlines()==["6f7323ccd20b1b495bb3c3161296d82c8a9a8981",*s.BASE_TREES],
         "structural oracle, recorder or native controls changed")
    need(ROOT.resolve()==ROOT and (WORK/".owned-by-packed-study").read_text()==str(ROOT) and
         shutil.disk_usage(OUT).free>=32*2**30 and shutil.disk_usage(WORK).free>=14*2**30,"runner floor")
    structural=admission.qualify()
    need(structural["source"]==b.HEADS["F"] and structural["cargo"]==b.CARGO and structural["wild"]==b.WILD_ELF and
         structural["argv"]==s.CARGO,"different SDK or workload in physical antecedent")
    for p in ("clean","history","initial"):
        (OUT/p).mkdir()
    save(OUT/"structural-source.json",structural)
    shutil.copy2(HERE/"PLAN.md",OUT/"PLAN.md");shutil.copy2(b.RUNTIME,OUT/"source-kit.json")
    subprocess.run([sys.executable,"-IB",HERE.parent/"branch-return-pmu/meter.py",calibrator,observers],check=True)
    ready=json.loads((OUT/"meter-ready.json").read_bytes())
    os.sched_setaffinity(0,ready["affinity"])
    need(ready["boot"] not in {structural["boot"],*json.loads((HERE/"excluded-boots.json").read_bytes())} and
         sorted(os.sched_getaffinity(0))==ready["affinity"],"non-independent boot or wrong affinity")
    prefix=s.suite.permission_prefix(OUT/"initial")
    save(OUT/"enrollment.json",dict(head=head,attempt=1,run=int(os.environ["GITHUB_RUN_ID"]),position=position,
         order=ORDERS[position],boot=ready["boot"],plan=b.sha(HERE/"PLAN.md"),argv=s.CARGO,
         arm_option="-Zohm-branch-cache=yes",source=b.spec(),structural_proof=admission.SHA,
         structured=admission.canonical_hash(structural),suite_prefix=prefix))
    registry=b.acquire(source)
    env=b.activate(ORDERS[position][0],registry,OUT/"initial")
    b.fresh_outputs();b.prepare_inputs(kit,env);w.historical.calibration()
    w.CARGO=list(s.CARGO)
    return registry,prefix,structural["structural"]


def visit(arm,phase,branch,env,where,refs,physical,antecedent,prefix):
    where.mkdir()
    need(shutil.disk_usage(WORK).free>3*2**30 and shutil.disk_usage(OUT).free>5*2**30,"working set or evidence floor")
    if phase=="repair":
        w.failed_session.before_repair(WORK,json.loads((where.parent/"invalid/working.json").read_bytes()),where/"failed-session-grace.json")
    w.checked_source(phase,branch,where)
    start=time.monotonic_ns()
    rc=101 if phase=="invalid" else 0
    messages,instructions,trace=w.invocation(where,env,"measured",rc,arm)
    post_clock=time.monotonic_ns()
    clock=w.clock(where/"clock.json",rc)
    need(trace is None and instructions==clock["instructions"] and start<=clock["start"]<clock["stop"]<=post_clock,
         "not one closed, untraced whole-Cargo counter")
    after=lambda: time.monotonic_ns()
    rows,dirty=s.selection.roster(messages,kit.TREE)
    w.publish(where/"roster.json.gz",dict(units=rows,dirty=dirty))
    pending=w.failed_session.observed(WORK)
    usage=w.disk.allocated(WORK/"target",WORK/"build",where,failed_sessions=pending)
    item=dict(arm=arm,phase=phase,branch=branch,exit=rc,instructions=instructions,allocated=usage["allocated"],
              typed=len(rows),dirty=len(dirty),typed_hash=admission.canonical_hash(rows),dirty_hash=admission.canonical_hash(dirty))
    if rc:
        save(where/"working.json",pending)
        item["error"]="E0308/ohm_branch_switch_invalid"
    else:
        need(not pending,"working session after successful Cargo")
        ref=refs[arm,branch]
        need(rows==ref["typed"] and item["typed_hash"]==antecedent["typed_sha256"] and
             item["dirty_hash"]==antecedent["dirty_sha256"] and
             w.historical.stable_sdk.output_directory(messages,"tikv-jemalloc-sys")==ref["native_dir"],
             ("typed graph, providers or dirty units diverged from native antecedent",phase,arm,item["dirty_hash"]))
        paths=s.selection.selected_paths(messages,kit.TREE,WORK)
        # No rustc or linker tracer enters the window. The owning actual command from this same
        # boot/role/branch's empty preparation selected both extern files at these exact paths.
        chosen,providers=s.selection.reader_stream(messages,physical[arm,branch],b.sha)
        save(where/"actual-reader-files.json",providers)
        prod,files=native.observed(chosen,branch,kit.REVS[branch],env,ROOT,kit.TREE,WORK,where)
        files["harness"]=paths["harness"]; images={k:prod[k] for k in ("cli","reader")}
        images["harness"]=native.elf(paths["harness"]);save(where/"harness-elf.json",images["harness"])
        for member,path in files.items():
            native.same_file(path,images[member],ref["images"][member],w.BODIES,where)
        suite=s.suite.exercise(paths["harness"],paths["cli"],kit.TREE,env,where,prefix,w.processes)
        behavior={k:v for k,v in prod.items() if k not in ("cli","reader")}|{"suite":suite}
        need(not kit.git("status","--porcelain") and behavior==ref["behavior"] and suite["inventory"]==antecedent["test_inventory"] and
             prod["typed"]==antecedent["typed_layout"],"clean, physical libtest/CLI or typed reader differs after measured Cargo")
        item.update(elf={name:images[name]["whole"] for name in images},passed=96,typed_layout=prod["typed"])
    save(where/"visit.json",item)
    save(where/"window.json",dict(before_cargo=start,clock_stop=clock["stop"],before_any_oracle=post_clock,after_all_oracles=after()))
    print(arm,phase,"native gates complete",flush=True)
    return item


def main(position,source,calibrator,observers):
    registry,prefix,antecedent=enter(position,source,calibrator,observers)
    refs,identities,records={},{},{}
    for arm in ORDERS[position]:
        root=OUT/"clean"/arm;root.mkdir();env=b.activate(arm,registry,root)
        for branch in ("A","B"):
            s.refuse_existing_work()
            v=root/branch
            s.receipt(arm,"cold-"+branch,branch,env,v,refs,{},True,prefix)
            identities[arm,branch]=json.loads((v/"physical-owners.json").read_bytes())["owners"]
    for branch in ("A","B"):
        left,right=(refs[a,branch] for a in s.ARMS)
        need(left["typed"]==right["typed"] and left["behavior"]==right["behavior"],"different clean compile graph or verdict")
        for name in ("cli","harness","reader"):
            need(all(left["images"][name][k]==right["images"][name][k] for k in ("executable","loads")),"cross-arm code changed")
    for arm in ORDERS[position]:
        root=OUT/"history"/arm;root.mkdir();env=b.activate(arm,registry,root)
        s.refuse_existing_work()
        records[arm]={}
        for phase,branch in w.PHASES:
            records[arm][phase]=visit(arm,phase,branch,env,root/phase,refs,identities,antecedent[arm+"/"+phase],prefix)
    b.verify_physical(b.SDK,registry["F"])
    save(OUT/"complete.json",dict(qualified=True,position=position,head=os.environ["GITHUB_SHA"],
              boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),order=ORDERS[position],histories=records))


if __name__=="__main__":
    if sys.argv[1:]==["--print-command"]:
        print(json.dumps(s.CARGO));sys.exit(0)
    try:main(sys.argv[1],*map(lambda v:Path(v).resolve(),sys.argv[2:]))
    except BaseException:
        (OUT/"rejected.txt").write_text(traceback.format_exc());raise
