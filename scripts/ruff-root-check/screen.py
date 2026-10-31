"""Two independent roots measure the literal virtual-workspace check after native qualification."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import time
import traceback

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import graph
import boot_identity
sys.path.insert(0,str(HERE.parent/"ruff-integration-structure"))
import witness as q

IPMU=HERE.parent/"ruff-integration-pmu"
sys.path.insert(0,str(IPMU))
import trace_events as tr

w=tr.w
import native_roles as native
b,kit=w.b,w.kit
need,save=b.need,b.save
OUT,WORK,ROOT=b.OUT,b.WORK,b.ROOT
BRANCH="charlie/qa-ruff-root-check-f-screen-20261031"
ORDERS={"01":["Foff","Fon"],"02":["Fon","Foff"]}
COMMAND=graph.CARGO
EXPECTED=q.read_gz(HERE/"enrolled-graph.json.gz")
PREFLIGHT=json.loads((HERE/"preflight-rejection.json").read_bytes())
PREVIOUS_RUNNERS={p["runner"] for p in PREFLIGHT["positions"].values()}
CLEAN=ROOT/"root-check-reference-bodies"
KEPT=OUT/"complete-bodies"


def graph_check(arm,branch,env,where):
    w.checked_source("cold-"+branch,branch,where)
    raw=[]
    for name,cmd in [
        ("unit",COMMAND+["-Zunstable-options","--unit-graph"]),
        ("members",["cargo","+ohm","metadata","--locked","--offline","--no-deps","--format-version","1"])]:
        r=subprocess.run(cmd,env=env,cwd=kit.TREE,capture_output=True,timeout=150)
        q.write_gz(where/(name+".stdout.gz"),r.stdout);q.write_gz(where/(name+".stderr.gz"),r.stderr)
        need(r.returncode==0,("graph preflight",name,r.stderr[-500:]))
        raw.append(json.loads(r.stdout))
    found=graph.selection(*raw,kit.TREE)
    need(found==EXPECTED,("changed locked graph",arm,branch,graph.census(found)))
    save(where/"graph.json",graph.census(found))


def space():
    physical=shutil.disk_usage(OUT).free
    active=shutil.disk_usage(WORK).free
    available=int(next(l.split()[1] for l in Path("/proc/meminfo").read_text().splitlines() if l.startswith("MemAvailable:")))*1024
    need(physical>=6*2**30 and active>=3*2**30 and available>=5*2**30,("runtime reserve",physical,active,available))
    return {"durable_available":physical,"work_available":active,"memory_available":available}


def traced(where,env,arm,rc):
    def record(code,stdout,stderr,observer):
        for n,s in (("stdout",stdout),("stderr",stderr)):q.write_gz(where/("cargo."+n+".gz"),s)
        w.publish(where/"cargo.json.gz",dict(argv=COMMAND,observer_argv=observer,cwd=str(kit.TREE),env=env,
                  expected=rc,exit=code,stdin_sha256=w.digest(b""),stdout_sha256=w.digest(stdout),stderr_sha256=w.digest(stderr)))
    code,out,err,_=tr.capture(COMMAND,env,kit.TREE,where,record=record)
    need(code==rc,("real traced Cargo exit",code,rc,err[-1000:]))
    try:
        with (where/"exec.raw").open() as f:images=w.processes.execs(f)
        identities=native.capture(images,b.PROXIES/"rustup")
        w.publish(where/"exec-inodes.json.gz",identities)
        physical=w.processes.inventory(where/"exec.raw",arm)
        need(physical["cargos"][0]["argv"][1:]==COMMAND[2:],"real Cargo selector")
        w.publish(where/"native-execs.json.gz",physical)
    finally:w.processes.compact(where/"exec.raw",where/"exec.raw.gz")
    (where/"child.stderr").unlink()
    return [json.loads(line) for line in out.splitlines()],None,physical


def valid(messages,physical,arm,branch,env,where,ref):
    n=graph.typed_graph(messages,EXPECTED,kit.TREE)
    if ref is None:
        need(all(not x["fresh"] for x in messages if x["reason"]=="compiler-artifact"),"empty reused a unit")
        mapping=q.owner(physical,kit.TREE,WORK,arm)
    else:
        mapping=ref["owner"]
        if physical and any(r["crate"]=="ruff_dev" and r["mode"]=="full" for r in physical["rustcs"]):
            actual=q.owner(physical,kit.TREE,WORK,arm)
            need(all(actual[k]==mapping[k] for k in ("providers","search")),"different root compiler metadata inputs")
            mapping=actual
    files=q.files(messages,WORK)
    w.publish(where/"artifact-paths.json.gz",files.copy())
    providers=q.provider_files(mapping,messages,WORK)
    if physical and ref is None:
        for name in graph.PROVIDERS:
            r=subprocess.run(["rustc","+ohm","-Zls=root",mapping["providers"][name]],cwd=kit.TREE,env=env,capture_output=True,timeout=60)
            q.write_gz(where/(name+".metadata-listing.gz"),r.stdout)
            q.write_gz(where/(name+".metadata-listing-stderr.gz"),r.stderr)
            cert=q.listing(name,mapping["providers"][name],providers[name]["file"],r.stdout,r.stderr,r.returncode)
            save(where/(name+".metadata-command.json"),cert)
    for item in providers.values():q.keep(WORK/item["relative"],item["file"],KEPT)
    rel,cert,typeshed=q.typeshed(messages,WORK,kit.TREE,where)
    files[rel]=cert
    q.keep(WORK/rel,cert,KEPT)
    client=q.check_client(mapping,branch,env,kit.TREE,ROOT,where)
    scripts=sorted((r for r in messages if r["reason"]=="build-script-executed"),key=graph.encoded)
    # Preserve the genuine full JSON rows independently of the mode-keyed planning graph.
    from selection import roster
    typed,dirty=roster(messages,kit.TREE)
    diagnostics=q.diagnostics(messages)
    record={"owner":mapping,"files":files,"providers":providers,"typeshed":typeshed,"typeshed_file":rel,
            "client":client,"scripts":scripts,"typed":typed,"dirty":dirty,"diagnostics":diagnostics,"units":n}
    w.publish(where/"observed.json.gz",record)
    if ref is None:
        for i,(p,data) in enumerate(files.items()):
            if i%40==0:space()
            q.keep(WORK/p,data,CLEAN)
        q.write_gz(where/"differences.json.gz",graph.encoded({}))
        return record,True
    changed=q.matched_products(files,ref["files"],WORK,CLEAN,KEPT,where)
    fields=("providers","typeshed","typeshed_file","client","scripts","typed","diagnostics")
    wrong=[key for key in fields if record[key]!=ref[key]]
    save(where/"comparison.json",{"changed_files":len(changed),"different_fields":wrong,
                                  "equal_full_files":len(files.keys()&ref["files"].keys())-sum(p in files and p in ref["files"] for p in changed)})
    return record,not changed and not wrong


def visit(arm,phase,branch,env,where,lane,refs,invalid):
    where.mkdir()
    before=space()
    if phase=="repair":
        w.failed_session.before_repair(WORK,json.loads((where.parent/"invalid/working.json").read_bytes()),where/"failed-session-grace.json")
    w.checked_source(phase,branch,where)
    q.source_check(json.loads((where/"source.json").read_bytes()),phase=="invalid")
    rc=101 if phase=="invalid" else 0
    tick=time.monotonic_ns()
    if lane=="measured":
        msgs,ins,physical=w.invocation(where,env,lane,rc,arm)
    else:
        msgs,ins,physical=traced(where,env,arm,rc)
    after=time.monotonic_ns()
    need(msgs[-1]=={"reason":"build-finished","success":not rc},"wrong actual terminal message")
    clock=w.clock(where/"clock.json",rc) if lane=="measured" else None
    if clock:need(tick<=clock["start"]<clock["stop"]<=after and ins==clock["instructions"],"wrong hardware window")
    abandoned=w.failed_session.observed(WORK)
    usage=w.disk.allocated(WORK/"target",WORK/"build",where,failed_sessions=abandoned)
    if rc:
        save(where/"working.json",abandoned)
        diags=q.diagnostics(msgs);q.error_check(diags,kit.TREE)
        w.publish(where/"observed-errors.json.gz",diags)
        ok=(diags==invalid[arm]) if arm in invalid else True
        if arm not in invalid:invalid[arm]=diags
        record={"errors":graph.digest(diags)}
    else:
        need(not abandoned and not any(r["message"]["level"]=="error" for r in q.diagnostics(msgs)),"failed successful check")
        ref=refs.get((arm,branch))
        record,ok=valid(msgs,physical,arm,branch,env,where,ref)
        if ref is None:refs[arm,branch]=record
        record={"units":record["units"],"dirty":len(record["dirty"]),"files":len(record["files"]),
                "client":record["client"],"typed_sha256":graph.digest(record["typed"])}
    result={"arm":arm,"phase":phase,"branch":branch,"lane":lane,"exit":rc,"instructions":ins,"pass":ok,
            "allocated":usage["allocated"],"resources":before,"products":record,"before_cargo":tick,"after_cargo":after,
            "after_output_checks":time.monotonic_ns()}
    if physical:result["execs"]=native.counts(physical)
    save(where/"visit.json",result)
    print(arm,phase,lane,"validated" if ok else "output differs from empty",flush=True)
    return result


def main(position,source,calibrator,observers):
    head=os.environ["GITHUB_SHA"]
    need(os.environ["GITHUB_REPOSITORY"]==b.REPO and os.environ["GITHUB_REF"]=="refs/heads/"+BRANCH and
         os.environ["GITHUB_RUN_ATTEMPT"]=="1" and os.environ["REVIEWED_HEAD"]==head==b.git(HERE,"rev-parse","HEAD"),"wrong source admission")
    runner=os.environ["RUNNER_NAME"]
    need(runner and runner not in PREVIOUS_RUNNERS and int(os.environ["GITHUB_RUN_ID"])!=PREFLIGHT["run"],"previous rejected preflight worker")
    need(b.git(HERE,"rev-parse","HEAD^")==PREFLIGHT["head"] and
         b.git(HERE,"rev-parse","HEAD:scripts/ruff-integration-pmu","HEAD:scripts/branch-return-pmu","HEAD:scripts/ohm-packed-ruff").splitlines()==
         ["1c117c3853e7bf3906922f5aac040673bed0087a","8036cb549845a905ab83882f5b01766229e0e636","d9fd6c8e4152d468a3a40d600ee1c6ebda13e5f2"],"changed independent capture sources")
    need(shutil.disk_usage(OUT).free>=32*2**30 and shutil.disk_usage(WORK).free>=14*2**30 and
         space()["memory_available"]>=12*2**30 and (WORK/".owned-by-packed-study").read_text()==str(ROOT),"cold resources")
    order=ORDERS[position]
    for name in ("initial","graphs","empty","structure","measured"): (OUT/name).mkdir()
    KEPT.mkdir();CLEAN.mkdir()
    shutil.copyfile(HERE/"PLAN.md",OUT/"PLAN.md")
    shutil.copyfile(b.RUNTIME,OUT/"source-kit.json")
    subprocess.run([sys.executable,"-IB",HERE.parent/"branch-return-pmu/meter.py",calibrator,observers],check=True)
    meter=json.loads((OUT/"meter-ready.json").read_bytes())
    need(meter["boot"] not in boot_identity.prior(),"previous physical worker")
    os.sched_setaffinity(0,meter["affinity"])
    save(OUT/"enrollment.json",{"head":head,"run":int(os.environ["GITHUB_RUN_ID"]),"attempt":1,"position":position,"order":order,"boot":meter["boot"],"runner":runner,
         "argv":COMMAND,"selection":graph.census(EXPECTED),"plan":b.sha(HERE/"PLAN.md"),"source":b.spec(),"visible_work":str(WORK)})
    tr.calibrate(OUT/"initial/kernel-events")
    registry=b.acquire(source)
    env=b.activate(order[0],registry,OUT/"initial");b.fresh_outputs();b.prepare_inputs(kit,env)
    w.historical.calibration();w.CARGO=COMMAND
    refs,errors={},{}
    for arm in order:
        path=OUT/"graphs"/arm;path.mkdir();env=b.activate(arm,registry,path)
        for branch in "AB":
            d=path/branch;d.mkdir();graph_check(arm,branch,env,d)
        path=OUT/"empty"/arm;path.mkdir();env=b.activate(arm,registry,path)
        for branch in "AB":
            b.fresh_outputs()
            visit(arm,"cold-"+branch,branch,env,path/branch,"empty",refs,errors)
        # The canonical type error comes from an independent B checkout state with no measured history.
        visit(arm,"invalid","B",env,path/"invalid","empty-control",refs,errors)
        got=visit(arm,"repair","B",env,path/"repair","empty-control",refs,errors)
        need(got["pass"],"ordinary repaired independent B differs from own clean")
    need(errors["Foff"]==errors["Fon"],"different genuine source-error semantics")
    # Each order's first setting independently traces a complete native history. Both settings are required across the two hosts.
    physical_arm=order[0];path=OUT/"structure"/physical_arm;path.mkdir();env=b.activate(physical_arm,registry,path);b.fresh_outputs()
    structural=[visit(physical_arm,p,br,env,path/p,"structure",refs,errors) for p,br in w.PHASES]
    need(all(r["pass"] for r in structural),"structural native history differed from an own empty reference")
    save(OUT/"native-admission.json",{"arm":physical_arm,"rows":structural})
    all_rows={}
    for arm in order:
        path=OUT/"measured"/arm;path.mkdir();env=b.activate(arm,registry,path);b.fresh_outputs()
        all_rows[arm]=[visit(arm,p,br,env,path/p,"measured",refs,errors) for p,br in w.PHASES]
    need(all(r["pass"] for rows in all_rows.values() for r in rows),"measured visit differed from clean")
    b.verify_physical(b.SDK,registry["F"])
    q.verify_bodies(KEPT)
    save(OUT/"complete.json",{"head":head,"position":position,"boot":meter["boot"],"rows":all_rows,"qualified":True})


if __name__=="__main__":
    if sys.argv[1:]==["--print-command"]:
        print(json.dumps(COMMAND));sys.exit()
    try:main(sys.argv[1],*map(lambda x:Path(x).resolve(),sys.argv[2:]))
    except BaseException:
        (OUT/"rejected.txt").write_text(traceback.format_exc());raise
