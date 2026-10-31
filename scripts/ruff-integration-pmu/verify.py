"""Recompute one closed native worker and compare the two independently ordered boots."""
import argparse
from fractions import Fraction
import gzip
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
os.environ.setdefault("RUNNER_TEMP",tempfile.gettempdir())
import pilot
a,s,w=pilot.admission,pilot.s,pilot.w
need,b=a.need,pilot.b
ORDER=pilot.ORDERS
VISITS=a.VISITS


def read(f):
    return json.loads(gzip.decompress(f.read_bytes()) if f.suffix==".gz" else f.read_bytes())


def calibrate(logs,calibrator,observer):
    repo=Path(calibrator);obs=Path(observer)
    b.prepare_checkout(repo,b.CAL,"scripts/gnu-renderer-pfc-hardware")
    b.prepare_checkout(obs,b.OBS,"scripts/gnu-example-ceiling")
    path=repo/"scripts/gnu-renderer-pfc-hardware";sys.path.insert(0,str(path))
    try:
        spec=importlib.util.spec_from_file_location("f_integration_pmu_calibration",path/"calibration.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        need(module.replay(obs,logs),"failed original whole process/thread hardware calibration")
    finally:
        sys.path.remove(str(path))
    watcher=read(logs/"observer.json")
    abi=watcher["abi"]
    need(abi=={"type":"PERF_TYPE_HARDWARE","config":"PERF_COUNT_HW_INSTRUCTIONS","pid":"fork child blocked on its one-byte pipe before execvp cargo +ohm",
               "inherit":1,"disabled":1,"enable_on_exec":1,"exclude_kernel":1,"exclude_hv":1,"cpu":-1,"group_fd":-1,
               "read_format":["PERF_FORMAT_TOTAL_TIME_ENABLED","PERF_FORMAT_TOTAL_TIME_RUNNING"],"read_bytes":24},"wrong counter scope")
    for name,value in watcher["bins"].items(): need(b.sha(logs/"observers"/name)==value,"damaged calibrated counter ELF")
    for name,value in watcher["sources"].items():
        raw=subprocess.check_output(["git","-C",obs,"show",b.OBS+":"+name])
        need(a.hashlib.sha256(raw).hexdigest()==value,"observer source identity")
    raw=read(logs/"calibration/admitted.json")
    need(sum(len(r[0]) for r in raw["whole28"].values())==28 and set(raw["nested"])=={"plain","tree"},"missing control cases")
    host=read(logs/"host.json")
    keys={"vendor_id","cpu family","model","model name","stepping"}
    cpu={k.strip():v.strip() for line in host["cpuinfo"].splitlines() if ":" in line for k,v in [line.split(":",1)] if k.strip() in keys}
    return {"abi":abi,"cells":28,"cpu":cpu,"pmu":host["raw_system"]["/sys/devices/cpu/caps/pmu_name"],
            "boot":host["raw_system"]["/proc/sys/kernel/random/boot_id"],"observer":b.OBS,"calibrator":b.CAL}


def elf(logs,desc,cache):
    digest=desc["whole"]
    if digest not in cache:
        with tempfile.TemporaryFile() as f:
            subprocess.run(["zstd","-dq","--stdout",logs/"native-bodies"/(digest+".zst")],stdout=f,check=True)
            cache[digest]=s.native.elf(Path(f"/proc/self/fd/{f.fileno()}"))
    need(cache[digest]==desc,"complete native ELF or any section/load differed")


def native_verdict(d,cmd,branch,expected_names):
    cli=read(d/"native.json.gz")
    need(cli["source"]==s.kit.REVS[branch] and cli["typed"]==f"Expr={64 if branch=='A' else 56} valid=1 rejected","typed reader")
    for name in ("reader-run","layout-64","layout-56"):
        proof=read(d/(name+".json.gz"))
        out,err=[gzip.decompress((d/(name+"."+stream+".gz")).read_bytes()) for stream in ("stdout","stderr")]
        ok=(name=="reader-run" or name==("layout-64" if branch=="A" else "layout-56"))
        need(proof["exit"]==proof["expected"]==int(not ok) and s.suite.sha(out)==proof["stdout_sha256"] and
             s.suite.sha(err)==proof["stderr_sha256"],"typed consumer command or exit")
        if name=="reader-run":
            need(out==(cli["typed"]+"\n").encode() and not err,"wrong actual consumer behavior")
        if not ok:
            diagnostics=[json.loads(line) for line in err.splitlines()]
            need(any(m.get("level")=="error" and (m.get("code") or {}).get("code")=="E0308" for m in diagnostics),
                 "opposite representation was not rejected by the compiler")
    need(s.suite.inventory(gzip.decompress((d/"libtest-list.stdout.gz").read_bytes()))==expected_names,"wrong test inventory")
    for name in ("libtest-list","libtest-full","dev-rule",*s.suite.EXACT):
        proof=read(d/(name+".json"))
        need(proof["exit"]==0 and Path(proof["cwd"])==Path(cmd["cwd"])/"crates/ruff" and proof["insta_root"]==cmd["cwd"] and
             all(s.suite.sha(gzip.decompress((d/(name+"."+suffix+".gz")).read_bytes()))==proof[suffix] for suffix in ("stdout","stderr")),
             ("wrong off-clock executable, cwd or exit",name))
        if name=="libtest-full":
            s.suite.verdict(gzip.decompress((d/(name+".stdout.gz")).read_bytes()),expected_names)
        if name in s.suite.EXACT:
            s.suite.verdict(gzip.decompress((d/(name+".stdout.gz")).read_bytes()),[name],95)
            with gzip.open(d/(name+".exec.gz"),"rt") as f: events=w.processes.execs(f)
            record=read(d/"libtest.json")["children"][name]
            need(len(events)==2 and events[0][0]==record["harness_pid"] and
                 events[1]==(record["ruff_pid"],proof["cargo_bin"],record["argv"]) and events[0][0]!=events[1][0],"wrong physical argfile child")
    return {"cli":cli["cli"],"reader":cli["reader"],"harness":read(d/"harness-elf.json")}


def worker(logs,calibrator,observer):
    en=read(logs/"enrollment.json");end=read(logs/"complete.json");pos=en["position"]
    need(pos in ORDER and tuple(end["order"])==tuple(en["order"])==ORDER[pos] and en["head"]==end["head"] and end["qualified"] and
         en["attempt"]==1 and en["plan"]==b.sha(HERE/"PLAN.md")==b.sha(logs/"PLAN.md") and en["argv"]==s.CARGO and
         en["structural_proof"]==a.SHA,"different registration, order or literal selection")
    adj=read(logs/"structural-source.json");need(adj==read(HERE/"structure.json") and a.canonical_hash(adj)==en["structured"],"wrong physical antecedent")
    sdk=read(logs/"sdk/F.json")
    need(en["source"]==read(logs/"source-kit.json")==b.spec() and sdk["source_commit"]==b.HEADS["F"] and
         sdk["compiler_tree"]==b.COMPARE["F"] and len(sdk["files"])==81 and
         sdk["files"][sdk["driver"]][0]=="fe62e729ee976d9b808b4f94f0a9751c7f6d7b2201aecf3636e9eff8acb88273","wrong compiler kit or driver")
    tools={k:sdk["files"][k] for k in ("bin/cargo","bin/rustc","bin/rustdoc",sdk["driver"],b.WILD)}
    cal=calibrate(logs,calibrator,observer);ready=read(logs/"meter-ready.json")
    need(ready["boot"]==en["boot"]==end["boot"]==cal["boot"] and ready["boot"] not in {adj["boot"],*read(HERE/"excluded-boots.json")},"wrong boot or identity")
    refs,cache,observations={},{},{};last=0
    names=s.suite.inventory((pilot.SRC/"expected-tests.txt").read_bytes())
    for stage in ("clean","history"):
        for arm in ORDER[pos]:
            root=logs/stage/arm;role=read(root/"arm.json")
            need(role["role"]=="F" and role["arm"]==arm and role["source_manifest"]==en["source"]["manifest"] and role["files"]==tools and
                 role["files"]["bin/cargo"][0]==b.CARGO_ELF and role["files"][b.WILD][0]==b.WILD_ELF and
                 (role["env"].get("CARGO_ENCODED_RUSTFLAGS")=="-Zohm-branch-cache=yes")==arm.endswith("on"),"wrong compiler/Cargo/Wild or flags")
            it=[(k,k) for k in "AB"] if stage=="clean" else w.PHASES
            for phase,branch in it:
                d=root/phase;v=read(d/"visit.json");cmd=read(d/"cargo.json.gz");src=read(d/"source.json")
                need(cmd["argv"]==s.CARGO and cmd["env"]==role["env"] and src["commit"]==s.kit.REVS[branch] and src["tree"]==s.kit.TREES[branch] and
                     ((phase=="invalid" and cmd["exit"]==101) or (phase!="invalid" and cmd["exit"]==0)),"source, actual argv or Cargo exit")
                streams={k:gzip.decompress((d/("cargo."+k+".gz")).read_bytes()) for k in ("stdout","stderr")}
                need(all(s.suite.sha(value)==cmd[key+"_sha256"] for key,value in streams.items()),"changed raw Cargo")
                rows=list(map(json.loads,streams["stdout"].splitlines()))
                need(rows[-1]=={"reason":"build-finished","success":phase!="invalid"},"Cargo result")
                typed,dirty=s.selection.roster(rows,Path(cmd["cwd"]))
                if stage=="clean":
                    need(not (d/"clock.json").exists() and len(typed)==len(dirty)==390,"empty control or unwanted counter")
                    phys=read(d/"native-execs.json.gz")
                    with gzip.open(d/"exec.raw.gz","rt") as f: events={(p,e,tuple(x)) for p,e,x in w.processes.execs(f)}
                    for tr in [*phys["cargos"],*phys["rustcs"],*phys["wild_processes"],*phys["other_linkers"]]:
                        need((tr["pid"],tr["exe"],tuple(tr["argv"])) in events,"missing native executable in positive control")
                    originals=read(d/"physical-owners.json")["owners"]
                    for target in ("cli","harness"):
                        owner=originals[target];[r]=[i for i in phys["rustcs"] if i["pid"]==owner["pid"]];[link]=owner["linked_by"]
                        need(s.selection.selected_externs(r["argv"])==owner["externs"] and
                             any(l["pid"]==link["pid"] and l["output"]==link["path"] for l in phys["wild_processes"]),"wrong physical compiler, provider or stock Wild")
                else:
                    ctr=w.clock(d/"clock.json",cmd["exit"]);seg=read(d/"window.json")
                    need(not (d/"exec.raw.gz").exists() and not (d/"native-execs.json.gz").exists() and
                         cmd["observer_argv"]==[ready["plain"],str(Path(ready["plain"]).parents[1]/"history"/arm/phase/"clock.json"),*s.CARGO] and
                         last<=seg["before_cargo"]<=ctr["start"]<ctr["stop"]==seg["clock_stop"]<=seg["before_any_oracle"]<=seg["after_all_oracles"],
                         "overlap, wrapper, missing hardware event or separate oracle in clock window")
                    last=seg["after_all_oracles"]
                    need(v==end["histories"][arm][phase] and v["exit"]==cmd["exit"] and v["instructions"]==ctr["instructions"] and
                         v["allocated"]==read(d/"storage.json")["allocated"] and a.canonical_hash(typed)==v["typed_hash"] and
                         a.canonical_hash(dirty)==v["dirty_hash"],"raw hardware count, graph or allocation changed")
                    observations.setdefault(arm,{})[phase]=v|{"raw_clock":ctr}
                    if phase=="invalid":
                        need(any(r.get("reason")=="compiler-message" and r["target"]["name"]=="ruff_python_parser" and
                                 (r["message"].get("code") or {}).get("code")=="E0308" and "ohm_branch_switch_invalid" in str(r["message"]["spans"]) for r in rows),
                             "wrong error or compiler");continue
                    p=adj["structural"][arm+"/"+phase]
                    need((v["typed_hash"],v["dirty_hash"])==(p["typed_sha256"],p["dirty_sha256"]),"different actual Cargo work")
                imgs=native_verdict(d,cmd,branch,names)
                if stage=="clean": refs[arm,branch]=imgs
                else:need(imgs==refs[arm,branch],"code or data differ from own local independently empty reference")
                for desc in imgs.values():elf(logs,desc,cache)
    for branch in "AB":
        for name in ("cli","harness","reader"):
            need(all(refs["Foff",branch][name][k]==refs["Fon",branch][name][k] for k in ("executable","loads")),"cross-arm code area changed")
    return {"kind":"two-boot F whole-Cargo integration pilot","run":en["run"],"head":en["head"],"position":pos,
            "boot":en["boot"],"order":list(ORDER[pos]),"calibration":cal,"observations":observations,
            "unique_clean_elfs":sorted(cache),"structural":a.SHA,"host_filesystem":(logs/"filesystem.txt").read_text().strip()}


def pair(x,y):
    need(x["head"]==y["head"] and x["run"]==y["run"] and x["boot"]!=y["boot"] and
         (x["position"],y["position"])==("01","02") and all(tuple(i["order"])==ORDER[i["position"]] for i in (x,y)) and
         x["calibration"]["cpu"]==y["calibration"]["cpu"] and x["calibration"]["pmu"]==y["calibration"]["pmu"] and
         x["structural"]==y["structural"]==a.SHA,"positions not independent or unmatched hardware/source")
    by={}
    for h in (x,y):
        obs=h["observations"];need(set(obs)==set(a.ARMS) and all(set(t)==set(VISITS) for t in obs.values()),"missing mode or visit")
        need(all(type(o["instructions"]) is int and o["instructions"]>0 for phases in obs.values() for o in phases.values()),
             "counter not a positive integer")
        groups={v:(v,) for v in VISITS}|{"return_sum":("return-A","return-B"),"first_switch_and_return_A":("first-B","return-A"),
                "cold_through_return_B":VISITS[:4],"all_five_successful":VISITS[:5],"all_seven":VISITS}
        vals={k:Fraction(*(sum(obs[a][v]["instructions"] for v in vs) for a in ("Foff","Fon"))) for k,vs in groups.items()}
        by[h["position"]]={"off_over_on":{k:[f.numerator,f.denominator] for k,f in vals.items()},
                           "both_returns_above_two":all(vals[k]>2 for k in ("return-A","return-B","return_sum"))}
    return {"positions":by,"pilot_only":True,"qualifies_for_separate_confirmation":all(o["both_returns_above_two"] for o in by.values())}


def compare_other_boots(result, first, second, kc1, kc2):
    boots=set()
    for cohort,run,raw in (("c1",41219513694,kc1),("c2",41219530573,kc2)):
        receipt=raw["receipt"]
        need(receipt["spec"]["cohort"]==cohort and receipt["spec"]["run"]==run and
             receipt["spec"]["head"]=="1d446332e82ca0188f63c3fddc9689f1f131fd42" and
             set(receipt["positions"])=={f"{i:02d}" for i in range(1,13)},"wrong packed-confirmation boot set")
        for pos in receipt["positions"].values():
            k=pos["host"]["boot"]
            need(k not in boots and k not in (first["boot"],second["boot"]),"reused confirmation boot")
            boots.add(k)
    return result|{"disjoint_confirmed_packed_boots":len(boots)}


if __name__=="__main__":
    ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest="which",required=True)
    c=sub.add_parser("worker");c.add_argument("logs",type=Path);c.add_argument("calibrator",type=Path);c.add_argument("observer",type=Path)
    c=sub.add_parser("pair")
    for f in ("first","second","packed_c1","packed_c2"):c.add_argument(f,type=Path)
    args=ap.parse_args()
    if args.which=="worker":
        result=worker(args.logs,args.calibrator,args.observer)
    else:
        first,second=read(args.first),read(args.second)
        result=compare_other_boots(pair(first,second),first,second,read(args.packed_c1),read(args.packed_c2))
    print(json.dumps(result,sort_keys=True,separators=(",",":")))
