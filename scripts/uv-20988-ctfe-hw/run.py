"""Two production compiler contractors, one real first-edit root check, two separate clocks."""
import gzip, json, os, re, shutil, subprocess, sys, time, traceback
from pathlib import Path
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parent))
import material as m
import deep, rawproof

def command(path,argv,mode,clock=None):
    path.mkdir(); mask=sorted(os.sched_getaffinity(0));boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    trial=argv if mode!="pmu" else [str(clock),str(path/"whole-clock.json"),*argv]
    with (path/"cargo.stdout").open("xb") as out,(path/"cargo.stderr").open("xb") as err:
        start=time.monotonic_ns()
        rc=subprocess.run(trial,cwd=m.SRC,env=m.ENV,stdout=out,stderr=err,timeout=1500)
        end=time.monotonic_ns()
    m.save(path/"ordinary.json",{"argv":argv,"invoked":trial,"mode":mode,"exit":rc.returncode,"start_ns":start,"end_ns":end,"ns":end-start,
                                "boot":boot,"cpus":mask,"env":m.ENV})
    m.guard(rc.returncode==0 and sorted(os.sched_getaffinity(0))==mask,"native command failed or affinity changed")
    return (path/"cargo.stdout").read_bytes(),(path/"cargo.stderr").read_bytes()

def final_sdk(role,installed,root,out):
    orig=m.read(out/"intake/role-material"/role/"sdk-inventory.json")
    expect={n:r["sha256"] for n,r in orig.items()};expect["bin/cargo"]=m.P["signed_cargo_sha256"]
    present={str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
    m.guard(present==set(expect) and all(not (root/n).is_symlink() and m.filesha(root/n)==v for n,v in expect.items()),"compiler/std SDK changed in use")
    return {"files":len(expect),"effective_inventory_sha256":m.digest(m.canon(expect)),"runtime":installed[role]["runtime"]}

def typed_events(so,se,kind,ref,o,api):
    rows,owners=o.native.events(so);args=sorted(o.native.commands(se.decode(),m.RUSTC));expected=ref[kind]
    artifacts=[r for r in rows if r["reason"]=="compiler-artifact"];scripts=[r for r in rows if r["reason"]=="build-script-executed"]
    shape=api.s.inputs(artifacts);sort=lambda v:sorted(v,key=m.canon)
    dirty=sort([[r["package_id"],r["target"]["name"],r["target"]["kind"],r["features"],r["filenames"]] for r in artifacts if not r["fresh"]])
    progress=sorted(x.decode() for x in re.findall(rb"^\s*(?:Checking|Compiling) ([\w-]+) v",se,re.M))
    actual={"roster":m.digest(m.canon(shape[0])),"all_artifact_rows":m.digest(m.canon(sort(artifacts))),
            "all_build_script_rows":m.digest(m.canon(sort(scripts))),"dirty":dirty,"progress":progress}
    observed={"rows":len(artifacts),"build_scripts":len(scripts),"workspace":len(shape[1]),"details":actual,
        "argv":args,"build_script_plaintext":owners,"diagnostics":[r for r in rows if r["reason"]=="compiler-message"]}
    m.guard(actual==expected and len(shape[1])==70 and len(artifacts)==641 and len(scripts)==51 and
            [r["success"] for r in rows if r["reason"]=="build-finished"]==[True] and
            not [r for r in rows if r["reason"]=="compiler-message"],("Cargo reference",kind))
    if kind=="edit":m.guard(args==ref["argv"],"edited full rustc arguments")
    else:
        m.guard(sorted(a[a.index("--crate-name")+1] for a in args)==["build_script_build","uv_python"],"unchanged prior compiler children")
    return shape,observed
def typed(path,kind,ref,o,api):
    so,se=command(path,[*m.ARGS,"--timings","--message-format=json-render-diagnostics","-vv"],"typed")
    shape,observed=typed_events(so,se,kind,ref,o,api);m.save(path/"observed.json",observed)
    for f in ("cargo.stdout","cargo.stderr"):o.native.gzip_file(path/f)
    return shape

def inventory(path,shape):
    answer={}
    for rel in sorted(shape[1]):
        p=m.TARGET/rel;m.guard(p.resolve(strict=True)==p and p.is_relative_to(m.TARGET) and 0<p.stat().st_size<40<<20,"unexpected Cargo-owned metadata")
        answer[rel]=[p.stat().st_size,m.filesha(p)]
    m.guard(len(answer)==70,"workspace product count");m.save(path/"workspace-products.json",answer);return answer

def capture(path,shape,o,api):
    o.product(path,shape,api);api.p.capture_plain(api.arm,path,shape,m.ENV)
    return api.p.plain(api.arm,path,shape)

def compared(a,b,shape,api,parser):
    x=api.p.plain(api.arm,a,shape);y=api.p.plain(api.arm,b,shape)
    m.guard(x["surfaces"]==y["surfaces"] and x["consumer"]==y["consumer"],"independent roots/dependencies/downstream consumers")
    m.guard(x["raws"].keys()==y["raws"].keys()==shape[1].keys(),"raw correspondence")
    result={}
    with ZipFile(a/"workspace-rmeta.zip") as ax,ZipFile(b/"workspace-rmeta.zip") as bx:
        m.guard(sorted(ax.namelist())==sorted(bx.namelist())==sorted(shape[1]),"unregistered raw member")
        for rel,info in sorted(shape[1].items()):
            xa,xb=ax.read(rel),bx.read(rel)
            m.guard([len(xa),m.digest(xa)]==x["raws"][rel] and [len(xb),m.digest(xb)]==y["raws"][rel],"raw metadata checksum")
            if xa==xb and info["name"]!="uv":continue
            l=deep.project(parser,xa,info["name"]);r=deep.project(parser,xb,info["name"])
            m.guard(l==r,("independent full definitions, expansions or allocations",rel))
            result[rel]={"raw_equal":xa==xb,"projection":l}
    m.guard(any(shape[1][rel]["name"]=="uv" for rel in result),"terminal decoder never ran")
    return {"all_70_roots_and_deps_equal":True,"actual_downstream":x["consumer"],"raw_drift":sorted(k for k in result if not result[k]["raw_equal"]),"deep":result}

def witness(path,state,o):
    path.mkdir();target=m.ROOT/"fixture";m.guard(not target.exists(),"fixture target reuse")
    ws=m.SRC/"crates/uv-workspace/src/workspace.rs";expected=m.CASE["fixture"][state]
    m.guard((b"fn exclude_package_with_normalized_glob_and_escaped_root(" in ws.read_bytes())==(state=="B"),"wrong upstream witness source")
    env=m.ENV|{"CARGO_TARGET_DIR":str(target),"CARGO_INCREMENTAL":"0","CARGO_PROFILE_TEST_DEBUG":"0","CARGO_PROFILE_DEV_DEBUG":"0","INSTA_UPDATE":"no"}
    argv=[m.ARGS[0],"test","--offline","--locked","-j4","-p","uv-workspace","--lib","workspace::tests::exclude_package","--","--test-threads=1"]
    with (path/"stdout").open("xb") as so,(path/"stderr").open("xb") as se:
        r=subprocess.run(argv,env=env,cwd=m.SRC,stdout=so,stderr=se,timeout=1800)
    raw=(path/"stdout").read_text();passed=sorted(re.findall(r"^test (workspace::tests::exclude_package\w*) \.\.\. ok$",raw,re.M))
    m.guard(r.returncode==0 and passed==expected and f"test result: ok. {len(expected)} passed; 0 failed;" in raw,"real upstream exclude_package fixture")
    m.save(path/"receipt.json",{"argv":argv,"exit":r.returncode,"passed":passed,"tree":m.history()[0],"workspace_rs_sha256":m.filesha(ws)})
    m.erase(target)

def qualify(role,bank,delta,path,o,api,parser,ref,observer):
    path.mkdir();m.reset(bank,"A",delta);command(path/"ordinary-A",m.ARGS,"cold-A")
    shape=m.shape();a=capture(path/"ordinary-A",shape,o,api)["raws"]
    measured=typed(path/"settled-A","background",ref,o,api);m.guard(measured==shape and rawproof.require(path/"ordinary-A",path/"settled-A",a,inventory(path/"settled-A",shape)),"observed A differs from ordinary A")
    witness(path/"fixture-A","A",o)
    seed=m.freeze();stamp=m.seed_state(seed,role);m.restore(seed,delta,role,stamp)
    command(path/"A-to-B",m.ARGS,"qualifying-edit");ordinary=capture(path/"A-to-B",shape,o,api)["raws"]
    m.restore(seed,delta,role,stamp);observed=typed(path/"preclock-edit","edit",ref,o,api)
    m.guard(observed==shape and rawproof.require(path/"A-to-B",path/"preclock-edit",ordinary,inventory(path/"preclock-edit",shape)),"unmeasured diagnostic changed outputs")
    m.restore(seed,delta,role,stamp);forwarded=path/"preclock-exec";observer.execute(forwarded,m.ARGS,m.ENV,m.SRC);observer.replay(forwarded)
    rawproof.require(path/"A-to-B",forwarded,ordinary,inventory(forwarded,shape));m.erase(seed)
    witness(path/"fixture-B","B",o)
    comparisons={}
    for i in (1,2):
        label=f"cold-B{i}";m.reset(bank,"B",delta);command(path/label,m.ARGS,"cold-B")
        physical=capture(path/label,shape,o,api)["raws"]
        variant=typed(path/(label+"-typed"),"background",ref,o,api)
        m.guard(shape==variant and rawproof.require(path/label,path/(label+"-typed"),physical,inventory(path/(label+"-typed"),shape)),"unchanged cold visit changed raw data or graph")
        comparisons[label]=compared(path/"A-to-B",path/label,shape,api,parser)
    comparisons["both-independent-cold"]=compared(path/"cold-B1",path/"cold-B2",shape,api,parser)
    m.save(path/"four-state.json",{"role":role,"A_tree":m.CASE["A_tree"],"B_tree":m.CASE["B_tree"],"comparisons":comparisons})
    return path/"cold-B1"

def trial(role,order,bank,delta,path,baseline,o,api,parser,trace,cal,meter,ref):
    path.mkdir();m.reset(bank,"A",delta);command(path/"cold-A",m.ARGS,"cold-A")
    shape=typed(path/"settled-A","background",ref,o,api);m.guard(shape==m.shape(),"actual A graph");seed=m.freeze()
    stamp=m.seed_state(seed,role);m.save(path/"A-snapshot.json",stamp)
    ready=cal["ready"];plain=Path(ready["plain"])
    m.guard(m.filesha(plain)==cal["plain_sha256"],"observer executable changed")
    mode_raw={};native=None
    for mode in [*order["modes"],"typed","scoped"]:
        m.restore(seed,delta,role,stamp);here=path/mode
        if mode=="typed":
            graph=typed(here,"edit",ref,o,api);m.guard(graph==shape,"edited graph changed")
            mode_raw[mode]=inventory(here,shape)
        elif mode=="scoped":
            trace.execute(here,m.ARGS,m.ENV,m.SRC);trace.replay(here)
            mode_raw[mode]=inventory(here,shape)
        else:
            command(here,m.ARGS,mode,plain);receipt=m.read(here/"ordinary.json")
            m.guard(receipt["boot"]==ready["boot"] and receipt["cpus"]==ready["affinity"],"host drift during scored visit")
            if mode=="pmu":
                clock=meter.clock(here/"whole-clock.json",0)
                m.guard(clock["running"]==clock["enabled"]>0 and clock["instructions"]>0,"invalid inherited event")
                mode_raw[mode]=inventory(here,shape)
            else:
                m.guard(mode=="native","unknown mode");native=here;mode_raw[mode]=capture(here,shape,o,api)["raws"]
        first=next(iter(mode_raw))
        if first==mode:rawproof.hold(here,mode_raw[mode])
        else:rawproof.require(path/first,here,mode_raw[first],mode_raw[mode])
        m.guard(m.history()==(m.CASE["B_tree"],delta),"observed visit modified source")
    m.guard(all(v==mode_raw["native"] for v in mode_raw.values()),"native/PMU/typed/scoped B same-seed raw mismatch")
    cold=compared(native,baseline,shape,api,parser)
    m.save(path/"accepted.json",{"role":role,"hold":order["hold"],"pair":order["pair"],"mode_order":order["modes"],
        "same_seed_raw_sha256":m.digest(m.canon(mode_raw["native"])),"A_snapshot":stamp["tree_sha256"],"modes":list(mode_raw),"A":m.CASE["A_tree"],"B":m.CASE["B_tree"],
        "independent_cold":cold,"genuine_children":len(ref["argv"]),"workspace":[] if not mode_raw else sorted(mode_raw["native"])})
    m.erase(seed,m.TARGET,m.SRC,m.CARGO_HOME,m.HOME)

def main():
    w,tmp=m.host();out=w/"trait-results";out.mkdir(exist_ok=True)
    if sys.argv[1:]==["calibrate"]:
        old,_=m.pmu(w,tmp);old.calibrate();return
    m.guard(sys.argv[1:]==["run"],"usage: run.py calibrate|run")
    o,api,parser,trace=m.observers(w,tmp);old,meter=m.pmu(w,tmp);ref=m.reference()
    cal=m.read(out/"calibration.json");ready=cal["ready"];guardhost=old.cpu_receipt(out)
    m.guard(ready["boot"]==guardhost["boot"] and ready["affinity"]==guardhost["cpus"] and cal["unmultiplexed_calibration_clocks"]==28,"fresh inherited counter calibration")
    trace.calibrate(out/"trace-calibration");trace.mutations(out/"trace-calibration")
    result=m.read(out/"intake.json");installed=result["installed"];m.guard(set(installed)==set(m.P["roles"]),"all compilers admitted")
    bank,delta=m.initial(w,tmp,out)
    for role,d in installed.items():
        src=tmp/"ctfe22-root-sdks"/role;m.guard(src.is_dir() and src.resolve()==src,"invalid installed SDK");shutil.move(src,bank/("sdk-"+role))
    m.choose("stock_ctfe318",bank,installed);m.provision(o,bank,out);baseline={}
    for role in m.P["roles"]:
        m.choose(role,bank,installed);baseline[role]=qualify(role,bank,delta,out/("qualification-"+role),o,api,parser,ref,trace)
    for order in m.P["orders"]:
        for role in order["roles"]:
            print("hold",order["hold"],"pair",order["pair"],role,flush=True)
            m.guard(shutil.disk_usage(m.ROOT).free>20<<30,"insufficient measured scratch")
            m.choose(role,bank,installed);path=out/f"hold{order['hold']}-pair{order['pair']:02d}-{role}"
            trial(role,order,bank,delta,path,baseline[role],o,api,parser,trace,cal,meter,ref)
    verified={}
    for role in m.P["roles"]:
        m.choose(role,bank,installed);verified[role]=final_sdk(role,installed,m.SDK,out)
    m.save(out/"final-sdk.json",verified)
    m.save(out/"panel-finished.json",{"observed_pairs":len(m.P["orders"]),"primary_unscored_until_independent_replay":True})
if __name__=="__main__":
    try:main()
    except Exception:
        w=Path(os.environ.get("GITHUB_WORKSPACE","."))/"trait-results"
        if w.is_dir() and not (w/"refusal.txt").exists():(w/"refusal.txt").write_text(traceback.format_exc())
        raise
