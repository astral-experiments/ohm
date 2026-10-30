"""Two independently mirrored, genuinely edited Ruff whole-Cargo instruction and native controls."""
import gzip
import json
from pathlib import Path
import sys
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit
import compare
import residual
from compare import q, rt, tree_ir
from study import change_source, digest, load, need, save, sha, source_values

OLD = "1a8df04825085b4b606db458fecf9ec24f2b651414eea444670226a5dfbf72f9"
NEW = "7d4d2fd48f2ef717f19b11cf5e4f21bcea69d16d55e631301b8266d74cf8abd8"
INVENTORY = "fe68c95a764685c7677db770a5e302996d8a18b95ed8ccf7d054a320c979b6ac"
ROSTER = ("mirror1-P","mirror1-C","mirror2-C","mirror2-P")
FOCUS = {"compact_str","ruff_python_ast"}


def native_visits(root, role):
    run, rows, markers = q.visit, {}, {}
    def capture(base, label, state, env, searches):
        v = run(base, label, state, env, searches)
        folder = base / label
        if state == "invalid":
            return v
        native = load(folder / "native.json")
        rows.update({a["crate"]: a for a in native["rustcs"] if a["crate"] in residual.NAMES})
        need(set(rows) == set(residual.NAMES), "could not bind each independent marker to the actual cargo compiler")
        facts = residual.unit_files(rows, folder)
        markers[label] = {n: [r["hard"],r["recheck"]] for n,r in facts.items()}
        need(len(v["typed"]) == 39 and digest(json.dumps(v["typed"],sort_keys=True,separators=(",",":")).encode()) == INVENTORY,
             "not the closed original Ruff artifact inventory")
        need(v["reader"] == (OLD if state == "old" else NEW), "complete original reader changed on exact historical state")
        return v
    q.visit = capture
    try:
        result = q.trial(root.name, role)
    finally:
        q.visit = run
    save(root / "native-markers.json", markers)
    save(root / "complete.json", result)
    return result


def entry(trace):
    with tempfile.TemporaryDirectory(dir=rt.ROOT) as tmp:
        base = Path(tmp)
        with tarfile.open(trace) as t:
            for part in t:
                if part.isfile():
                    name = Path(part.name)
                    need(name.parent == Path("exec") and name.name.startswith("proc."), "invalid acquired kernel trace")
                    (base / name.name).write_bytes(t.extractfile(part).read())
        cargos = [(pid, argv, env) for pid,p,argv,env in tree_ir.rows(base) if p.samefile(rt.SDK/"bin/cargo")]
    need(len(cargos)==1 and cargos[0][2]["RUSTUP_TOOLCHAIN"]=="ohm","no signed cargo environment")
    return cargos[0]


def physical_expected(prior, phase):
    row = load(prior/phase/"native.json")
    need(not row["link_tools"] and not row["compiler_probes"], "unexpected native-only action in registered AArch64 rlib workload")
    rs = row["rustcs"]
    need(all(r["terminal"]==[0] and not r["link_only"] for r in rs) and len(rs)==len({r["crate"] for r in rs}),
         "cannot decompose the actual compiler process roster")
    return {"cargo":row["cargo"][0]["argv"]} | {r["crate"]:r["argv"] for r in rs}


def counted_cycle(prior, role, common):
    rt.select(role)
    folder = rt.LOG / (prior.name+"-edit-cycle")
    folder.mkdir()
    env, values, searches = rt.environment(), source_values(rt.RUFF), []
    change_source(rt.RUFF,values,"old")
    q.acquire(folder, rt.ROOT/"seed")
    initial = q.visit(folder,"old-empty","old",env,searches)
    need(q.semantic(initial) == common["old"] and initial["reader"] == OLD,"fresh independent old training mismatch")
    pid,argv,cargo_env=entry(prior/"counter/trace.tar.gz")
    need(argv == physical_expected(prior,"edit")["cargo"] and cargo_env["CARGO_TARGET_DIR"]==str(rt.WORK/"target") and
         cargo_env["CARGO_BUILD_BUILD_DIR"]==str(rt.WORK/"shared"),"different signed application entry or canonical directories")
    save(folder/"entry.json",{"pid_from_unscored_native_prior":pid,"actual_argv":argv,"physical_sdk_cargo":sha(rt.SDK/"bin/cargo"),
                              "native_cargo_raw":sha(prior/"counter/trace.tar.gz"),"env_keys":sorted(cargo_env)})
    change_source(rt.RUFF,values,"new")
    result, records = {}, {}
    for name,phase in (("first-real-edit","edit"),("immediate-repeat","unchanged-1")):
        expect=physical_expected(prior,phase)
        proc,counts=tree_ir.count(folder/name,argv,cargo_env,expect,rt.RUFF)
        rows,ids,dirty,_=q.typed(proc.stdout,True)
        existing=load(prior/phase/"verified.json")
        need(ids==existing["typed"] and dirty==existing["dirty"],"instrumentation changed physical workload or dirtiness")
        root,=[r for r in rows if r["target"]["name"]=="ruff_python_ast"]
        rlib,=[Path(p) for p in root["filenames"] if p.endswith(".rlib")]
        b=rlib.read_bytes()
        proof=q.archive(b)
        need(q.custody(b,".rlib")==proof["raw"] and [[n,s,k] for n,_,s,k in proof["objects"]]==common["cold"]["native"],
             "counted visit no longer produced the complete reference set of AArch64 object bytes")
        facts={"processes":counts,"Ir":sum(r["Ir"] for r in counts.values()),"archive":proof,"typed":ids,"dirty":dirty,
               "prior_raw_native":sha(prior/phase/"native.json"),"physical_jobserver":sha(folder/name/"command/physical-jobserver.json")}
        records[name]=save(folder/name/"verified.json",facts)
        result[name]=facts["Ir"]
    outcome=q.visit(folder,"post-settled","new",env,searches)
    need(q.semantic(outcome)==common["cold"] and outcome["reader"]==NEW,"actual consumer inconsistent with independent empty")
    save(folder/"complete.json",{"source":common["role"],"total":sum(result.values()),"individual":result,"records":records,
                               "training":sha(folder/"old-empty/verified.json"),"post":sha(folder/"post-settled/verified.json")})
    q.park(prior.name+"-actual-edit-and-repeat")
    return result


def main():
    arc,key,native=sys.argv[1:];native=Path(native)
    kit.bind()
    select,roles,_=compare.installable(Path(arc),key,native,expected_tree=kit.TREE)
    need(roles["P"]["source"]==kit.BEFORE and roles["C"]["source"]==kit.AFTER,"wrong exact compiler sources")
    for cfg, shape in (("compact_input","move "),("compact_copy","copy "),("compact_constant","const ")):
        for arm in ("base","extended"):
            p=native/("direct-"+arm)
            allowed=arm=="extended" and cfg!="compact_constant"
            need(load(p/"complete.json")["actual"][cfg][:2]==[not allowed,allowed], "incorrect checked-in native admission")
            mir=(p/("mir-"+cfg)/"actual.mir").read_text()
            need(any('asm!("/* {0} */", in(reg) '+shape in line for line in mir.splitlines()),"unbound actual operand kind")
    need((native/"x86-host-run-make-pass").read_text().strip()==kit.AFTER,"missing both host test cases")
    driver,=select("P")
    need(driver.startswith("lib/librustc_driver-") and roles["P"]["files"][driver][0]==kit.OLD_IR,"prior qualification compiler changed")
    bind={"source":[kit.BEFORE,kit.AFTER],"driver":{k:v["files"][driver][0] for k,v in roles.items()},
          "installer":key,"real_rustc_and_cargo":{k:sha(rt.SDK/"bin"/k) for k in ("rustc","cargo")},
          "native":{n:sha(native/n) for n in ("imported-original.json","sdk-custody.json","x86-host-run-make-pass","direct-base/complete.json","direct-extended/complete.json","native-P/native-provider/complete.json","native-C/native-provider/complete.json")}}
    save(rt.LOG/"subjects.json",bind)
    rt.select=select
    q.counter=tree_ir.measure
    tree_ir.calibrate()
    q.prepare_graph()
    results={}
    for lab in ROSTER:
        role=lab[-1]
        prior=rt.LOG/lab
        trial=native_visits(prior,role)
        need(trial["measured"] is not None,"retained unscored primary after instrument admission failure")
        cycle=counted_cycle(prior,role,trial)
        settle=load(prior/"counter/verified.json")
        results[lab]={"role":role,"old":trial["old"],"new":trial["cold"],"visits":trial["stages"],
                      "markers":load(prior/"native-markers.json"),"settled_Ir":settle["Ir"],"complete_native":sha(prior/"complete.json"),
                      "edit_cycle":cycle,"ordinary_counts":sha(prior/"counter/verified.json"),
                      "cycle_native":sha(rt.LOG/(lab+"-edit-cycle")/"complete.json")}
    ref=results[ROSTER[0]]
    for r in results.values():
        need(r["old"]==ref["old"] and r["new"]==ref["new"],"cross-compiler native outputs differ")
    table={}
    for pair in ("mirror1","mirror2"):
        a,b=(results[pair+"-"+n] for n in "PC")
        pairrow={}
        for phase in ("edit","unchanged-1","unchanged-2"):
            before,after=a["visits"][phase],b["visits"][phase]
            pairrow[phase]=[before["rustcs"],after["rustcs"]]
        pairrow["native_gate"]=all(set(a["visits"][k]["rustcs"])==FOCUS and not b["visits"][k]["rustcs"]
            and all(a["markers"][k][u]==[True,False] and b["markers"][k][u]==[False,True] for u in FOCUS)
            for k in ("unchanged-1","unchanged-2")) and set(b["visits"]["edit"]["rustcs"])=={"ruff_python_ast"}
        pairrow["settled_ratio"]=a["settled_Ir"]/b["settled_Ir"]
        pairrow["actual_edit_ratio"]=a["edit_cycle"]["first-real-edit"]/b["edit_cycle"]["first-real-edit"]
        pairrow["edit_and_next_ratio"]=sum(a["edit_cycle"].values())/sum(b["edit_cycle"].values())
        table[pair]=pairrow
    save(rt.LOG/"terminal.json",{"observations":results,"both_mirrors":table,
         "settled_meets_two":all(r["native_gate"] and r["settled_ratio"]>2 for r in table.values()),
         "two_command_cycle_meets_two":all(r["native_gate"] and r["edit_and_next_ratio"]>2 for r in table.values()),
         "scope":"Whole physical signed Cargo and all userspace child rustc instructions; four independent native-plus-counter histories plus four independently trained first-edit/repeat histories. Excludes external proof and Rustup prefix; no elapsed-time claim."})
if __name__=='__main__':
    main()
