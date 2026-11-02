"""Two qualified source compilers, ordinary Ruff Cargo histories and immutable native controls."""
from collections import Counter
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import runtime
from runtime import census,guards,need,put,sha,support,transport
import micro
import pilot
from support import e2e,replay,study

PLAN=json.loads((transport.STAGE/"confirmation.json").read_bytes())


def source_entry(source,suite):
    need(sha(transport.STAGE/"confirmation.json")==transport.CONFIRM and
         os.environ["GITHUB_RUN_ATTEMPT"]=="1" and os.environ["GITHUB_REPOSITORY"]==transport.REPO and
         os.environ["GITHUB_REF"]=="refs/heads/"+transport.BRANCH and
         census.git(HERE,"rev-parse","HEAD")==os.environ["GITHUB_SHA"]==os.environ["REVIEWED_HEAD"],"wrong registration checkout")
    baseline=json.loads((HERE/"worker.json").read_bytes())
    for n,oid in baseline["original_trees"].items():
        need(census.git(HERE,"rev-parse","HEAD:scripts/"+n)==oid,("unverified measurement source",n))
    selected=pilot.source_plan(source,suite)
    branch=PLAN["suites"][suite]
    need(selected["command"]==branch["cargo"] and [selected["old"],selected["new"]]==
         [branch["source"]["OLD"],branch["source"]["NEW"]],"different historical Ruff task")
    return selected


def phase(kit,loc,work,repo,env,which,suite,graph,cmd,extras,gold,score,opens):
    rusts,actual,roster,probes,pmsha,dso=runtime.visit(kit,loc,work,repo,env,cmd,101 if which=="invalid" else 0,
        score=score,cold=which in ("old","clean-new"),observe=opens)
    rows=replay.cargo_rows((loc/"outer.stdout").read_bytes())
    result=pilot.phase_checks(suite,rows,graph,work,repo,env,which,loc,extras,kit.evidence/"native-bodies",gold)
    if suite=="option" and which!="invalid":
        arc=study.artifact(study.results(rows,True),study.OWNER)
        actual_archive=support.physical.keep(arc,kit.evidence/"owner-archives",b"!<arch>\n")
        need(actual_archive["sha256"]==result["owner_archive"]["sha256"],"different real owner archive")
    genuine=[r for r in rusts if r["kind"] in ("full","link-only") and r["name"] in graph[1]]
    if which=="new":
        expected=[["full","ruff_workspace",1]] if suite=="option" else [["full","e2e",1],["full","ty_server",1]]
        need(actual["rustc"]==expected and actual["linkers"]==([] if suite=="option" else [["signed-Wild","e2e",1]]) and
             {r["name"] for r in genuine}==set(graph[1]),("different physical edited ownership",suite,actual))
        for r in genuine:
            a=r["argv"]
            cg={arg if arg!="-C" else "-C"+a[i+1] for i,arg in enumerate(a) if arg.startswith("-C")}
            need("-Copt-level=1" in cg and "-Cdebuginfo=line-tables-only" in cg and "-Clto=off" in cg and
                 any("/build/debug/build/registries/v2-" in arg for arg in a) and
                 not any(v in arg for arg in a for v in ("llvm-plugins","llvm-args","-Cpasses=")),("altered real ordinary owner",r["name"]))
        if opens:
            need(set(dso)=={r["pid"] for r in genuine},"actual libraries not reopened for each real owner")
    if which=="unchanged":
        e={"rustc":[["link-only","e2e",1]],"linkers":[["signed-Wild","e2e",1]]} if suite=="e2e" else {"rustc":[],"linkers":[]}
        need(actual==e,("different physical unchanged mechanism",suite,actual))
    result.update({"root_argv":sorted([r["name"],r["argv"]] for r in genuine),"roster":roster,"raw_roster":actual,
        "physical_autocfg":probes,"counter_member_sha":pmsha,"kernel_sha256":sha(loc/"kernel.json"),
        "linker_argv_sha256":sha(loc/"linker-argv.json"),"source_libraries_sha":sha(loc/"actual-libraries.json")})
    put(loc/"result.json",result)
    return result


def exact(x,y,keys,when):
    for k in keys:
        need(x.get(k)==y.get(k),("actual P/C or own independent-clean mismatch",when,k))


def suite_run(kit,root,source,suite,stage,role_order):
    state=source_entry(source,suite)
    cmd=state["command"]
    folder=root/("workflow-"+suite)
    folder.mkdir()
    dest=kit.evidence/suite
    dest.mkdir()
    donor=folder/"registry-donor"
    donor.mkdir()
    deps={r["name"]+"-"+r["version"]+".crate":r["checksum"] for r in tomllib.loads((source/"Cargo.lock").read_text())["package"] if "checksum" in r}
    subprocess.run(["cargo","+ohm","fetch","--locked"],env={**kit.base,"CARGO_HOME":str(donor)},cwd=source,check=True)
    need(pilot.registry(donor)==deps and deps["autocfg-1.5.0.crate"]==json.loads((HERE/"worker.json").read_bytes())["autocfg"],"wrong locked registry")
    put(dest/"registry.json",deps)
    gold=study.source_pair(source) if suite=="option" else None
    blobs=e2e.enroll(replay,source,deps) if suite=="e2e" else None
    work,repo,extras=folder/"work",folder/"ruff",folder/"consumer"
    work.mkdir(); extras.mkdir()
    pilot.new_tree(source,repo,state["old"])
    if suite=="option":
        shutil.copyfile(HERE.parent/"ruff-workspace-option-edit/client.rs",extras/"option-client.rs")
        (extras/"bad-option-client.rs").write_bytes(study.BAD_CLIENT)
    base={**kit.base,"CARGO_HOME":str(work/"cargo-home"),"CARGO_TARGET_DIR":str(work/"target"),"CARGO_BUILD_BUILD_DIR":str(work/"build")}
    def source_state(which,write):
        if suite=="e2e":
            return e2e.source_state(replay,repo,blobs,which,write=write)
        fn=study.write_source if write else study.source_state
        return fn(repo,state["old"] if which=="old" else state["new"],which=="invalid")
    graph=None
    all_rows={}
    peer_keys=["dirty","inventory","root_argv","roster","verdict","elf","error"]
    for role in role_order:
        kit.select(role)
        observed={}
        all_rows[role]=observed
        cases=(("edit",("old","new","unchanged","invalid","repair")),
               ("clean",("clean-new","negative","restored-new") if suite=="e2e" else ("clean-new",)))
        for kind,phases in cases:
            case=dest/(role+"-"+kind)
            case.mkdir()
            guards.admit(guards.resources(work,dest),entry=True)
            source_state(phases[0],True)
            with replay.empty_roots(work,case):
                home=work/"cargo-home"
                (home/"registry").mkdir()
                for n in ("index","cache"):
                    subprocess.run(["cp","-a","--reflink=auto",donor/"registry"/n,home/"registry"/n],check=True)
                subprocess.run(["cargo","+ohm","fetch","--locked","--offline"],env=base,cwd=repo,check=True)
                need(pilot.registry(home)==deps,"changed registry inputs")
                now=pilot.unit_graph(cmd,base,repo,case,suite)
                need(graph is None or graph==now,"changed literal ordinary development unit graph")
                graph=now
                for which in phases:
                    before=source_state(which,True)
                    loc=case/which
                    actual=phase(kit,loc,work,repo,base,which,suite,graph,cmd,extras,gold,
                        stage=="score" and kind=="edit" and which in ("old","new","unchanged"),stage=="admit" and which=="new")
                    need(before==source_state(which,False),"real source mutation during visit")
                    put(loc/"source.json",before)
                    observed[which]=actual
                    if role!=role_order[0]:
                        exact(all_rows[role_order[0]][which],actual,peer_keys,[suite,role,which])
        for returned in ("new","unchanged","repair",*(("restored-new",) if suite=="e2e" else ())):
            exact(observed["clean-new"],observed[returned],["inventory","elf","verdict"],[role,suite,returned,"independent-empty"])
        need(observed["old"]["elf"]!=observed["new"]["elf"] and observed["invalid"]["error"]=="E0308","genuine edit or error absent")
        if suite=="e2e":
            need(observed["old"]["verdict"]["count"]==151 and observed["new"]["verdict"]["count"]==152 and
                 isinstance(observed["negative"]["verdict"]["negative_left"],str) and
                 observed["negative"]["verdict"]["negative_left"]!=e2e.WARNING,"genuine test inventory or contrary runtime missing")
    need(pilot.registry(donor)==deps,"original donor changed")
    put(dest/"acquired.json",all_rows)
    return {"phases":sum(map(len,all_rows.values())),"graph":graph[2],"registry":sha(dest/"registry.json"),
            "acquired":sha(dest/"acquired.json"),"command":cmd,"source":[state["old"],state["new"]]}


def run(stage,slot,sources):
    run_dir,evidence,_=census.paths()
    need(stage in ("admit","score") and slot in (range(1,7) if stage=="score" else (1,2)),"unscheduled slot")
    assignment=PLAN["assignments"][slot-1] if stage=="score" else {
        "slot":slot,"compilers":["P","C"] if slot==1 else ["C","P"],"suites":["option" if slot==1 else "e2e"]}
    for suite in assignment["suites"]:
        source_entry(sources[suite],suite)
    run_dir.mkdir()
    evidence.mkdir()
    out=evidence/"physical"
    out.mkdir()
    root=run_dir/"actual-ruff"
    root.mkdir()
    inputs=Path(os.environ["RUNNER_TEMP"])/"ldv-qualified-sdks"
    shutil.copytree(inputs/"source-receipts",out/"source-receipts")
    shutil.copyfile(inputs/"source-qualification.json",out/"source-qualification.json")
    guards.admit(guards.resources(root,out),entry=True,bootstrap=True)
    cpus={}
    for cpu in sorted(os.sched_getaffinity(0)):
        topo=Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
        cpus.setdefault(tuple(int((topo/name).read_text()) for name in ("physical_package_id","core_id")),cpu)
    need(len(cpus)>=4,"fewer than four real CPUs")
    physical_cpus=list(cpus.values())[:4]
    os.sched_setaffinity(0,physical_cpus)
    tools=root/"tools"; tools.mkdir()
    small=HERE.parent/"ruff-workspace-link-census/wild-diagnostic"
    for name,src,opt in (("count","count.c",[]),("toy","calibrate.c",["-pthread"])):
        subprocess.run(["/usr/bin/cc","-O2","-Wall",small/src,*opt,"-o",tools/name],check=True)
    support.calibrate(tools,out/"calibration")
    kit=runtime.Runtime(run_dir,inputs,out,tools)
    micro.proxy_calibration(kit,kit.base,root,out/"calibration/cargo-dispatch")
    if stage=="score":
        prior=Path(os.environ["RUNNER_TEMP"])/"physical-native-admission.json"
        gate=json.loads(prior.read_bytes())
        need(gate["sha"]==os.environ["GITHUB_SHA"] and gate["run"]==int(os.environ["ADMISSION_RUN"]) and
             gate["factory"]==transport.BUILD and set(gate["boots"])=={"option","e2e"},"different native gate")
        shutil.copyfile(prior,out/"previous-admission.json")
    for kind in ("native-bodies","owner-archives"):
        (out/kind).mkdir()
    boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    entry={"qa":os.environ["GITHUB_SHA"],"run":int(os.environ["GITHUB_RUN_ID"]),"boot":boot,"cpus":physical_cpus,"stage":stage,
           "assignment":assignment,"confirmation":transport.CONFIRM,"factory":transport.BUILD,"roles":transport.capsule.REG["roles"],
           "counter_sha":sha(tools/"count"),"source_qualification":sha(out/"source-qualification.json")}
    put(out/"entry.json",entry)
    if stage=="score":
        need(boot not in (v["boot"] for v in gate["boots"].values()),"native admission boot reused for scoring")
    receipts={}
    for suite in assignment["suites"]:
        receipts[suite]=suite_run(kit,root,sources[suite],suite,stage,assignment["compilers"])
    kit.finish()
    put(out/"complete.json",{"entry":sha(out/"entry.json"),"suites":receipts,"physical":sha(out/"physical-roles.json"),
                             "scope":"actual source-built whole-Cargo; all phase counts remain in raw hardware files"})
    print("All physical gates finished.",stage,slot,sorted(receipts),flush=True)


if __name__=="__main__":
    sources={k:Path(v).resolve(strict=True) for k,v in zip(("option","e2e"),sys.argv[3:5],strict=True)}
    run(sys.argv[1],int(sys.argv[2]),sources)
