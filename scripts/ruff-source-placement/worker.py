"""Measure the unchanged real Cargo workflows using trace/census observers outside the measured process."""
from contextlib import nullcontext
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from common import WORKFLOW, enrollment, need, save, sha
import receiver
import placement_peak
import storage
import tracking
sys.path.insert(0,str(WORKFLOW))
import acquire
from acquire import census, guards, micro, pilot, replay, runtime, shards, study, support, transport

REG=None


def setup(root,out,inputs):
    guards.admit(guards.resources(root,out),entry=True,bootstrap=True)
    cpus={}
    for cpu in sorted(os.sched_getaffinity(0)):
        topo=Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
        cpus.setdefault(tuple(int((topo/n).read_text()) for n in ("physical_package_id","core_id")),cpu)
    need(len(cpus)>=4,"short physical CPU set")
    selected=list(cpus.values())[:4]
    os.sched_setaffinity(0,selected)
    tools=root/"tools";tools.mkdir()
    small=HERE.parent/"ruff-workspace-link-census/wild-diagnostic"
    for name,src,flags in (("count","count.c",[]),("toy","calibrate.c",["-pthread"])):
        subprocess.run(["/usr/bin/cc","-O2","-Wall",small/src,*flags,"-o",tools/name],check=True)
    subprocess.run(["/usr/bin/cc","-Wall","-Wextra","-Werror","-O2",HERE/"rss.c","-o",tools/"rss"],check=True)
    support.calibrate(tools,out/"calibration")
    placement_peak.calibrate(tools/"rss",out/"calibration/peak-rss")
    kit=runtime.Runtime(root.parent,inputs,out,tools)
    micro.proxy_calibration(kit,kit.base,root,out/"calibration/cargo-dispatch")
    return selected,kit


def projections(kit,phase,where,work,stage,which,suite):
    disk=storage.census(work,where,kit.evidence/"workproduct-indices")
    save(where/"storage.json",disk)
    if kit.active=="P":
        need(disk["optional_tail_bytes"]==0,"placement storage leaked into #337")
    if stage=="admit":
        observed=tracking.read(where,kit.sdk)
        save(where/"source-selection.json",observed)
        vals=observed["renames"]
        if kit.active=="P" or which in ("old","clean-new") or (which=="unchanged" and suite=="option"):
            need(not vals,("unexpected placement hit",kit.active,suite,which,vals[:2]))
        if kit.active=="C" and suite=="option" and which=="new":
            need(any(r["owner"]=="ruff_workspace" for r in vals) and disk["optional_tail_bytes"]>0,
                 "no genuinely edited Ruff native object admitted")
    return disk


def collect(stage,slot,sources):
    reg=enrollment()
    need(stage in ("admit","score") and slot in (1,2),"unscheduled visit")
    protocol=json.loads((HERE/"protocol.json").read_bytes())
    if stage=="admit":
        order=["P","C"] if slot==1 else ["C","P"]
        suites=["option" if slot==1 else "e2e"]
    else:
        row=protocol["assignments"][slot-1];order=row["roles"];suites=row["suites"]
    inputs=Path(os.environ["RUNNER_TEMP"])/"placement-qualified-sdks"
    run_dir,evidence,_=census.paths()
    run_dir.mkdir();evidence.mkdir();out=evidence/"physical";out.mkdir()
    root=run_dir/"actual-ruff";root.mkdir()
    for n in ("native-bodies","owner-archives","workproduct-indices"): (out/n).mkdir()
    shutil.copyfile(inputs/"source-qualification.json",out/"source-qualification.json")
    shutil.copyfile(inputs/"docs-qualification.json",out/"docs-qualification.json")
    for role in ("P","C"):
        shutil.copyfile(inputs/"capsule"/(role+".json"),out/(role+"-source-kit.json"))
    cpus,kit=setup(root,out,inputs)
    seal=json.loads((out/"source-qualification.json").read_bytes())["seal"]
    boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    need(boot!=seal["boot"],"factory boot reused as measurement")
    entry={"stage":stage,"slot":slot,"run":int(os.environ["GITHUB_RUN_ID"]),"qa":os.environ["GITHUB_SHA"],
           "boot":boot,"cpus":cpus,"order":order,"suites":suites,"factory":receiver.FACTORY,"source":reg["roles"],
           "registration":sha(HERE/"protocol.json"),"counter_sha":sha(kit.tools/"count"),"kit":seal["sha256"]}
    if stage=="score":
        gate=json.loads((inputs/"native-gate.json").read_bytes())
        need(gate["qa"]==entry["qa"] and len(set(gate["boots"].values()))==2 and boot not in gate["boots"].values()
             and gate["kit"]==entry["kit"] and gate["source"]==reg["roles"],"different native acceptance")
        save(out/"previous-gate.json",gate)
    save(out/"entry.json",entry)
    previous=acquire.phase
    def recorded(kit,where,work,repo,env,which,suite,graph,cmd,extras,gold,score,opens,admit):
        # Only the acquisition controller is extended. The command started below is the inherited ordinary real Cargo.
        context=tracking.add_file_calls(guards,where) if stage=="admit" else nullcontext()
        owners=({"ruff_workspace"} if suite=="option" else {"ty_server","e2e"}) if stage=="admit" and which in ("old","new","clean-new") else ()
        with placement_peak.observe(guards,where,kit,owners=owners),context:
            actual=previous(kit,where,work,repo,env,which,suite,graph,cmd,extras,gold,score,opens,stage=="admit")
        projections(kit,actual,where,work,stage,which,suite)
        return actual
    reports={}
    with patch.object(acquire,"phase",recorded):
        for suite in suites:
            reports[suite]=acquire.suite_run(kit,root,sources[suite],suite,stage,order)
    if stage=="admit" and suites==["option"]:
        import durable, check_handoff
        durable.exercise(kit,root,sources["option"])
        check_handoff.exercise(kit,root,sources["option"])
    kit.finish()
    save(out/"complete.json",{"entry":sha(out/"entry.json"),"suites":reports,"physical":sha(out/"physical-roles.json"),
         "kit":entry["kit"],"source":reg["roles"],"scope":"complete source-matched ordinary Cargo + child processes; prospective two-pair screen"})
    print("All source placement gates passed",stage,slot,flush=True)


if __name__=="__main__":
    collect(sys.argv[1],int(sys.argv[2]),dict(zip(("option","e2e"),map(lambda s:Path(s).resolve(strict=True),sys.argv[3:]),strict=True)))
