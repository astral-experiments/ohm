"""Count the first edited build and the immediately following unchanged build."""
from pathlib import Path
import sys
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "ohm-aarch64-linux")]
import qualify as q
import runtime as rt
import tree_ir
from study import change_source, load, need, save, sha, source_values
from storage import allocation

GOLDEN = load(HERE/"counter-golden.json")
OLD, NEW = [GOLDEN[k]["reader"] for k in ("old", "new")]


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
    save(folder/"allocated.json", allocation(rt.WORK))
    q.park(prior.name+"-actual-edit-and-repeat")
    return result
