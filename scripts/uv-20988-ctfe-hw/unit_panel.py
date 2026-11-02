"""Count exact, same-seed kernel-enrolled compiler images during ordinary uv #20988 root checks."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from fractions import Fraction
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
import compiler_observer as native
import material as m
import receipt
import run
import score

P=m.read(m.HERE/"thread-protocol.json")
METER=m.HERE/"thread-meter"
DRIVER=m.load("per_compiler_pmu",METER/"per_rustc.py")
EMPTY_ENV={"PATH":"/usr/bin:/bin","LC_ALL":"C"}
PRIMARY=tuple(P["primary"])

def host():
    return {"boot":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),"cpus":sorted(os.sched_getaffinity(0))}

def source():
    assert all(m.filesha(METER/name)==sha for name,sha in P["meter_files"].items())

def cal_raw(dest):
    rec=m.read(dest/"calibration.json")
    assert rec["reexec_rejected"] is True
    rows=rec["known_two_instruction_loop"]
    assert set(rows)=={"serial","threads","fork"}
    n,many=3_000_000,14_000_000
    for mode,factor in (("serial",1),("threads",3),("fork",0)):
        vals=[]
        for x in (n,many):
            p=dest/f"{mode}-{x}";rep=m.read(p/"per-rustc.json")
            req=m.read(dest/f"{mode}-{x}.json")
            assert set(rep["targets"])=={"probe"} and req["command"]==req["selectors"]["probe"]
            row=rep["targets"]["probe"]
            assert all(row[k]==v for k,v in DRIVER.read_counter(bytes.fromhex(row["raw_hex"])).items())
            events=m.read(p/"kernel-events.json");tree=DRIVER.EVENTS["decode"](events)
            assert row["pid"]==tree["root"]==rep["root"] and tree["exits"][row["pid"]]==0
            assert len([e for e in tree["images"]if e["pid"]==row["pid"] and e["argv"]==req["command"]])==1
            forks=[e[1]>>16 for e in events["events"] if isinstance(e[1],int) and os.WIFSTOPPED(e[1]) and e[0]==events["root"]]
            assert mode!="threads" or forks.count(3)==3
            assert mode!="fork" or forks.count(1)+forks.count(2)==1
            assert (p/"stdout").read_bytes()==f"completed {mode} {x}\n".encode()
            vals.append(row["instructions"])
        want=2*factor*(many-n);delta=vals[1]-vals[0]
        assert abs(delta-want)<=100_000 and rows[mode]=={"counts":vals,"measured_delta":delta,"expected_delta":want}
    assert b"measured process executed a second image" in (dest/f"reexec-{n}.stderr").read_bytes()
    assert not (dest/f"reexec-{n}/per-rustc.json").exists()
    return rows

def calibrate():
    source()
    w,tmp=m.host();out=w/"trait-results";p=out/"per-rustc-calibration";p.mkdir()
    old,_=m.pmu(w,tmp);selected=old.cpu_receipt(out);base=m.read(out/"calibration.json")["ready"]
    assert (selected["boot"],selected["cpus"])==(base["boot"],base["affinity"])
    assert host()=={"boot":selected["boot"],"cpus":selected["cpus"]}
    kit=tmp/"production-rustc-meter";kit.mkdir()
    cc=["/usr/bin/cc","-O2","-Wall","-Wextra","-Werror"]
    lib,load=kit/"libohm_pmu.so",kit/"workload"
    subprocess.run([*cc,"-fPIC","-shared",METER/"pmu.c","-o",lib],check=True)
    subprocess.run([*cc,"-pthread",METER/"workload.c","-o",load],check=True)
    subprocess.run([sys.executable,"-ISB",METER/"per_rustc.py","calibrate",p,lib,load],check=True,timeout=240)
    cal_raw(p)
    binaries=p/"native-artifacts";binaries.mkdir()
    for f in (lib,load):shutil.copyfile(f,binaries/f.name)
    m.save(p/"source.json",{"host":host(),"tool":P["meter_commit"],"library":m.filesha(lib),"fixture":m.filesha(load),
           "cc":subprocess.check_output([cc[0],"--version"],text=True).splitlines()[0]})

def selectors(rows):
    lookup={}
    for row in rows:
        argv=row["argv"]
        assert argv[0]==str(m.RUSTC) and all(argv.count(k)==1 for k in ("--crate-name","--crate-type","--out-dir"))
        label="-".join(argv[argv.index(k)+1]for k in ("--crate-name","--crate-type"))
        assert re.fullmatch(r"[a-z_0-9]+-(lib|bin)",label) and label not in lookup
        lookup[label]=argv
    assert sorted(lookup)==P["labels"] and sorted(lookup.values())==m.reference()["argv"]
    chosen={k:lookup[k] for k in PRIMARY}
    for label,argv in chosen.items():
        policy=P["primary_enrollment"][label]
        assert [v for v in argv if v.endswith("/src/lib.rs")]==[policy["source"]]
        assert sorted(v for i,v in enumerate(argv[1:],1) if argv[i-1]=="--cfg" and v.startswith("feature="))==policy["features"]
    return chosen

def check_meter(path,chosen,meta):
    request=m.read(path/"request.json")
    assert request=={"command":m.ARGS,"environment":m.ENV,"cwd":str(m.SRC),"compiler_path":str(m.RUSTC),"selectors":chosen}
    raw=m.read(path/"per-rustc.json");tree=DRIVER.EVENTS["decode"](m.read(path/"kernel-events.json"))
    events=tree["images"];root=events[0];reports=raw["targets"]
    assert raw["scope"]=="retired userspace instructions in the selected process and its threads"
    assert raw["root"]==tree["root"]==root["pid"] and tree["exits"][root["pid"]]==0
    assert root["argv"]==m.ARGS and root["exe"]==m.ARGS[0] and root["file"]==meta["cargo_file"]
    images=[i for i in events if i["file"]==meta["compiler_file"] or Path(i["exe"]).name=="rustc" or (i.get("argv") and Path(i["argv"][0]).name=="rustc")]
    assert len(images)==len({i["pid"]for i in images})==18 and len(reports)==len(PRIMARY)==2
    assert all(i["file"]==meta["compiler_file"] and i["exe"]==str(m.RUSTC) and tree["exits"][i["pid"]]==0 for i in images)
    assert selectors(images)==chosen and set(reports)==set(chosen)
    assert len({r["event_id"]for r in reports.values()})==len(PRIMARY)
    pid_by_argv={tuple(i["argv"]):i["pid"]for i in images}
    for label,row in reports.items():
        assert row["exe"]==str(m.RUSTC) and row["file"]==meta["compiler_file"] and row["argv"]==chosen[label]
        assert row["pid"]==pid_by_argv[tuple(chosen[label])]
        assert all(row[k]==v for k,v in DRIVER.read_counter(bytes.fromhex(row["raw_hex"])).items())
    assert not (path/"stdout").read_bytes() and native.messages((path/"stderr").read_bytes())==native.messages((path.parent/"native/cargo.stderr").read_bytes())
    return {label:row["instructions"]for label,row in reports.items()}

def measured(path,chosen):
    w,tmp=m.host();proof=w/"trait-results/per-rustc-calibration/source.json"
    lib=tmp/"production-rustc-meter/libohm_pmu.so";cred=m.read(proof)
    assert cred["host"]==host() and cred["library"]==m.filesha(lib) and cred["tool"]==P["meter_commit"]
    role,runtime=native.inputs(path)
    assert all(m.filesha(m.SDK/k)==v for k,v in runtime.items())
    meta={"role":role,"runtime":runtime,"host":host(),"library":cred["library"],
          "cargo_file":DRIVER.EVENTS["file_id"](Path(m.ARGS[0])),"compiler_file":DRIVER.EVENTS["file_id"](m.RUSTC)}
    request={"command":m.ARGS,"cwd":str(m.SRC),"environment":m.ENV,"compiler_path":str(m.RUSTC),"selectors":chosen}
    req=path.parent/"kernel-request.json";m.save(req,request);path.mkdir()
    meta["start_ns"]=time.monotonic_ns()
    subprocess.run([sys.executable,"-ISB",METER/"per_rustc.py","capture",req,path,lib],env=EMPTY_ENV,check=True,timeout=1800)
    meta["stop_ns"]=time.monotonic_ns()
    m.save(path/"request.json",request);m.save(path/"source.json",meta)
    assert host()==meta["host"] and runtime==native.inputs(path)[1] and all(m.filesha(m.SDK/k)==v for k,v in runtime.items())
    return check_meter(path,chosen,meta)

def trial(role,order,bank,delta,path,baseline,o,api,parser,trace,cal,meter,ref):
    path.mkdir();m.reset(bank,"A",delta);run.command(path/"cold-A",m.ARGS,"cold-A")
    shape=run.typed(path/"settled-A","background",ref,o,api);assert shape==m.shape()
    seed=m.freeze();stamp=m.seed_state(seed,role);m.save(path/"A-snapshot.json",stamp)
    def visit(name):
        m.restore(seed,delta,role,stamp)
        return path/name
    native_b=visit("native");run.command(native_b,m.ARGS,"unscored-native")
    ordinary=run.capture(native_b,shape,o,api)["raws"]
    typed=visit("typed");assert run.typed(typed,"edit",ref,o,api)==shape
    run.rawproof.require(native_b,typed,ordinary,run.inventory(typed,shape))
    scoped=visit("scoped");trace.execute(scoped,m.ARGS,m.ENV,m.SRC);roster=trace.replay(scoped)
    run.rawproof.require(native_b,scoped,ordinary,run.inventory(scoped,shape))
    chosen=selectors(roster["compilations"])
    counted=visit("counted");values=measured(counted,chosen)
    run.rawproof.require(native_b,counted,ordinary,run.inventory(counted,shape))
    assert m.history()==(m.CASE["B_tree"],delta)
    cold=run.compared(native_b,baseline,shape,api,parser)
    m.save(path/"accepted.json",{"role":role,"hold":order["hold"],"pair":order["pair"],"A":m.CASE["A_tree"],"B":m.CASE["B_tree"],
        "A_snapshot":stamp["tree_sha256"],"same_seed_raw_sha256":m.digest(m.canon(ordinary)),
        "enrolled_argv_sha256":m.digest(m.canon(chosen)),"independent_cold":cold,"instructions":values})
    m.erase(seed,m.TARGET,m.SRC,m.CARGO_HOME,m.HOME)

def verify_arm(path,role,ref,o,api,parser,trace,shape,journal):
    q=path.parent/("qualification-"+role);record=m.read(path/"accepted.json")
    journal(path/"settled-A","background",ref,o,api);journal(path/"typed","edit",ref,o,api)
    chosen=selectors(trace.replay(path/"scoped")["compilations"]);counted=path/"counted"
    assert chosen==m.read(path/"kernel-request.json")["selectors"]
    meta=m.read(counted/"source.json");cred=m.read(path.parent/"per-rustc-calibration/source.json")
    assert meta["role"]==role and meta["runtime"]==native.inputs(counted)[1]
    assert meta["host"]==cred["host"] and meta["library"]==cred["library"]
    for name in ("native","typed"):
        visit=m.read(path/name/"ordinary.json")
        assert visit["env"]==m.ENV and visit["exit"]==0 and (visit["boot"],visit["cpus"])==(meta["host"]["boot"],meta["host"]["cpus"])
        assert 0<visit["start_ns"]<visit["end_ns"]<meta["start_ns"]<meta["stop_ns"]
    assert m.read(path/"native/ordinary.json")["argv"]==m.read(path/"native/ordinary.json")["invoked"]==m.ARGS
    scoped_meta=m.read(path/"scoped/launch.json")
    assert all(meta[k]==scoped_meta[k]for k in ("cargo_file","compiler_file","runtime"))
    vals=check_meter(counted,chosen,meta)
    direct=score.raw(path/"native");assert all(m.read(path/mode/"workspace-products.json")==direct for mode in ("typed","scoped","counted"))
    stamp=m.read(path/"A-snapshot.json")
    assert record["same_seed_raw_sha256"]==m.digest(m.canon(direct)) and stamp["tree_sha256"]==record["A_snapshot"]
    assert stamp["regular_bytes"]>0 and len(stamp["actual_incremental_headers"])>=4 and all(h[1]==m.P["roles"][role]["epoch"] for h in stamp["actual_incremental_headers"])
    assert (record["A"],record["B"],record["role"])==(m.CASE["A_tree"],m.CASE["B_tree"],role)
    assert record["enrolled_argv_sha256"]==m.digest(m.canon(chosen)) and vals==record["instructions"]
    assert receipt.matches(run.compared(path/"native",q/"cold-B1",shape,api,parser),record["independent_cold"])
    return vals

def report(out):
    source();assert not (out/"refusal.txt").exists()
    cal_raw(out/"per-rustc-calibration");creds=m.read(out/"per-rustc-calibration/source.json");hostrec=m.read(out/"host.json")
    assert creds["tool"]==P["meter_commit"] and creds["host"]=={k:hostrec[k]for k in ("boot","cpus")}
    binary=out/"per-rustc-calibration/native-artifacts"
    assert m.filesha(binary/"libohm_pmu.so")==creds["library"] and m.filesha(binary/"workload")==creds["fixture"]
    sdk=m.read(out/"intake.json");assert sdk["signed_cargo_sha256"]==m.P["signed_cargo_sha256"] and sdk["sdk_lock_sha256"]==P["sdk_lock"]
    assert m.filesha(out/"intake/sdk-lock.json")==P["sdk_lock"]
    assert sdk["build_run"]==P["sdk_builder"] and sdk["build_head"]==P["sdk_build_head"]
    score.qualifications(out,m.shape()[1])
    pairs=[];seeds=set();last=0
    assert P["order"]==m.P["orders"] and list(score.ROLES)==P["role_order"]
    for order in m.P["orders"]:
        vals={}
        for role in order["roles"]:
            path=out/f"hold{order['hold']}-pair{order['pair']:02d}-{role}"
            row=m.read(path/"accepted.json");meta=m.read(path/"counted/source.json")
            assert (row["hold"],row["pair"],row["role"])==(order["hold"],order["pair"],role)
            assert set(row["instructions"])==set(PRIMARY) and row["A_snapshot"] not in seeds
            assert all(type(n) is int and n>0 for n in row["instructions"].values())
            assert last<meta["start_ns"]<meta["stop_ns"]
            seeds.add(row["A_snapshot"]);last=meta["stop_ns"]
            vals[role]=row["instructions"]
        pairs.append({"design":order,"values":vals})
    assert len(pairs)==8 and len(seeds)==len(list(out.glob("hold*-pair*-*/accepted.json")))==16
    assert tuple(PRIMARY)==("uv-lib","uv_resolver-lib")
    return {"scope":"selected native production rustc image plus its own threads during ordinary uv #20988 root cargo check",
            "metric":"retired userspace hardware instructions","primary":list(PRIMARY),"statistics":summarize(pairs),
            "pairs":pairs,"features":P["primary_enrollment"],"protocol":m.filesha(m.HERE/"thread-protocol.json"),
            "SDK_lock":P["sdk_lock"],"boot_affinity":creds["host"],"whole_command_study":P["whole_command_study"],
            "source":m.CASE,"ordinary_wall_scored":False,"family_size":2}

def summarize(pairs):
    from math import comb
    roles=score.ROLES;designs=[p["design"] for p in pairs]
    assert len(pairs)==8 and designs==m.P["orders"] and len(roles)==2
    assert [d["roles"][0]==roles[1] for d in designs]==[False,True,False,True,True,False,True,False]
    threshold=Fraction(5,4);res={}
    for name in PRIMARY:
        ratios=[Fraction(p["values"][roles[0]][name],p["values"][roles[1]][name]) for p in pairs]
        wins=sum(x>threshold for x in ratios)
        raw_p=Fraction(sum(comb(8,k) for k in range(wins,9)),256)
        family_p=min(Fraction(1),2*raw_p)
        def grouped(by):
            groups={k:[x for d,x in zip(designs,ratios,strict=True) if by(d)==k] for k in {by(d) for d in designs}}
            assert sorted(len(g) for g in groups.values())==[4,4]
            return {str(k):score.num(score.median(xs)) for k,xs in sorted(groups.items())}
        holds=grouped(lambda d:d["hold"]);orders=grouped(lambda d:d["roles"][0])
        res[name]={"ratios":[score.num(v) for v in ratios],"paired_median":score.num(score.median(ratios)),
                   "paired_percent_fewer":float(100*(1-1/score.median(ratios))),
                   "arm_medians":{role:score.num(score.median([p["values"][role][name] for p in pairs])) for role in roles},
                   "hold_medians":holds,"first_role_medians":orders,"above_20pct_fewer":wins,
                   "ties_at_20pct":sum(x==threshold for x in ratios),"sign_tail_at_20pct":score.num(raw_p),
                   "bonferroni_p":score.num(family_p),"simultaneous_lower_ratio":score.num(min(ratios)),
                   "familywise_minimum_lower_bound_coverage":float(1-Fraction(2,256)),
                   "qualified_20pct":wins==8 and family_p<Fraction(1,20) and all(Fraction(x["fraction"])>threshold for x in [*holds.values(),*orders.values()])}
    return res

if __name__=="__main__":
    try:
        source()
        if sys.argv[1:]==["calibrate"]:calibrate()
        else:
            assert sys.argv[1:]==["run"]
            run.trial=trial
            run.main()
    except Exception:
        out=Path(os.environ.get("GITHUB_WORKSPACE","."))/"trait-results"
        if out.is_dir() and not (out/"refusal.txt").exists():
            (out/"refusal.txt").write_text(traceback.format_exc())
        raise
