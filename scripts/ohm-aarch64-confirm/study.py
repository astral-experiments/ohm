"""Three source-attested SDKs and one counterbalanced GNU AArch64 Ruff block per runner."""
import hashlib
import itertools
import json
import os
from pathlib import Path
import runpy
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ohm-aarch64-compact"))
# The original scripts import their own study.py by module name. This adapter is run as a main
# program; keep its directory out of the unqualified import search.
sys.path[:] = [p for p in sys.path if p != str(HERE)]
import ruff
from ruff import compare, kit, q, residual, rt, tree_ir
from study import load, need, physical, save, sha

SOURCE = {"A":"444c0273a2e2bc0b161e988d43c882349bc2d7a6", "N":kit.BEFORE, "M":kit.AFTER}
DRIVER = {"A":"a1f1eb603214c354827aa24c7176aaa4c349b2cc741526e6e2e87af46105929b",
          "N":kit.OLD_IR, "M":"2a232a6c250f30b7c8214be0bbba21ef125f514da3dfd720291c377909d14545"}
ORIGINAL = "d4a58ad69b0b2427f0fa1c4f3a9945783d7f2a9e3a4de9525d97f69db4f2a79b"
CURRENT = "7e591c1d2340f06a72c56893dde67bb52dab9a6ac9715efece486714af8f343f"
WANT = {"A":{"zmij","compact_str","ruff_python_ast"}, "N":{"compact_str","ruff_python_ast"}, "M":set()}

def schedule():
    seq = list(map("".join,itertools.permutations("ANM")))
    key = lambda half,p:hashlib.sha256(f"GNU-compact-heldout-parked-v2/{half}/{p}".encode()).digest()
    return {f"{i:02d}":p for i,p in enumerate([p for half in (1,2) for p in sorted(seq,key=lambda p:key(half,p))],1)}

def old(base):
    # Its working root and SDK restore are isolated in a separate process from the timed path.
    need((base/"key").read_text().strip()==ORIGINAL,"unregistered original capsule")
    select, _, _=compare.installable(base/"sdk.tar.zst",ORIGINAL,base/"native")
    select("P")

def setup(ancestor, inputs, alternate=None):
    kit.bind()
    _, pair, _ = compare.installable(inputs/"sdk.tar.zst",CURRENT,inputs/"native",expected_tree=kit.TREE)
    oldA, oldN = (load(ancestor/"receipts"/(k+"-sdk.json")) for k in "PC")
    need(oldN==pair["P"],"the shared physical N component is not identical across both transports")
    roles = {"A":oldA,"N":pair["P"],"M":pair["C"]}
    need({k:v["source"] for k,v in roles.items()}==SOURCE,"wrong three source revisions")
    name, = (n for n in oldA["files"] if n.startswith("lib/librustc_driver"))
    ref = dict(oldA["files"]); del ref[name]
    overrides={}
    if alternate is not None:
        alternate_path,product=alternate
        need(sha(alternate_path)==product["cargo_sha256"] and product["git"]=="735e1528ed741015c57676dccf05dbdc0ff7bed1","unregistered replacement Cargo")
        original=roles["A"]["files"]["bin/cargo"]
        need(original[0]==rt.TOOLS["bin/cargo"] and product["mode"]==original[2],"incorrect signed Cargo predecessor or executable mode")
        for k,v in roles.items():
            need(v["files"]["bin/cargo"]==original,"asymmetrical signed Cargo source")
            v["files"]["bin/cargo"]=[product["cargo_sha256"],product["raw_bytes"],product["mode"]]
        ref["bin/cargo"]=roles["A"]["files"]["bin/cargo"]
        overrides={"bin/cargo":alternate_path}
        save(rt.LOG/"cargo-substitution.json",{"immutable_source":product["git"],"from":original,"to":ref["bin/cargo"],"version":product["version"],"product":sha(alternate_path.parent/"product.json")})
    for k,v in roles.items():
        files = dict(v["files"])
        need(files.pop(name)[0]==DRIVER[k] and len(files)==118 and files==ref,"more than the one physical driver changed")
        save(rt.LOG/("subject-"+k+".json"),v)
    origins={"A":ancestor/"donor-P","N":rt.ROOT/"donor-P","M":rt.ROOT/"donor-C"}
    cls=runpy.run_path(str(HERE/"parked.py"))["Parked"]
    storage=cls(rt.ROOT/"fixed-role-parking",rt.SDK,{k:v["files"] for k,v in roles.items()},origins,name,overrides=overrides)
    save(rt.LOG/"all-named-start-identities.json",storage.initial)
    history=[]
    def select(k):
        event=storage.select(k)
        rec=rt.LOG/"physical-selections"/(f"{len(history):02d}-"+k+".json")
        sealed=save(rec,event); history.append({k:v for k,v in event.items() if k!="files"} | {"snapshot":rec.relative_to(rt.LOG).as_posix(),"sha256":sealed})
        return [name]
    return select, history


def physical_jobs(prior, phase):
    j=load(prior/phase/"native.json")
    # Also bound all successful execve events on independent readback, including the Rustup hop.
    need(not j["link_tools"] and not j["compiler_probes"] and len(j["cargo"])==1,"unregistered process")
    return {r["crate"] for r in j["rustcs"]}

def block(number, ancestor, inputs, enrolled=None):
    order_file=HERE/"schedule.json" if enrolled is None else rt.LOG/"schedule.json"
    order_map=schedule() if enrolled is None else enrolled["order_map"]
    order=order_map.get(number)
    need(load(order_file)==order_map,"changed blocked order")
    select,history=setup(ancestor,inputs,None if enrolled is None else enrolled["cargo"])
    rt.select=select
    rt.select("A")
    q.prepare_graph()
    transitions=runpy.run_path(str(HERE/"transitions.py"))
    weights=transitions["check"](rt,q,select,sha,history)
    save(rt.LOG/"all-nine-actual-transitions.json",weights)
    if number=="qualify":
        return
    q.counter=tree_ir.measure
    tree_ir.calibrate()
    save(rt.LOG/"heldout-registration.json", {"block":number,"order":order,"source":SOURCE,"drivers":DRIVER,"schedule":sha(order_file),
        "original":ORIGINAL,"current":CURRENT,"cpu":Path("/proc/cpuinfo").read_text().split("model name",1)[-1].splitlines()[0],
        "boot_digest":sha(Path("/proc/sys/kernel/random/boot_id")),"signed_tools":rt.TOOLS,
        "actual_cargo":sha(rt.SDK/"bin/cargo"),"additional_qualification":None if enrolled is None else enrolled["registration"],"cross_gcc":physical(Path(q.CROSS)),
        "qemu":physical(Path(q.QEMU[0])),"counter":physical(Path(tree_ir.VG)),"counter_source":sha(Path(tree_ir.__file__)),
        "installer":sha(rt.SDK/"bin/rustc"),"host":rt.HOST,"target":rt.TARGET,"lock":q.LOCK,"QA":os.environ["GITHUB_SHA"]})
    summary={}; common=None
    for role in order:
        name="block-"+number+"-"+role;prior=rt.LOG/name
        result=ruff.native_visits(prior,role)
        need(result["measured"] is not None,"unscored failed counter")
        cycle=ruff.counted_cycle(prior,role,result)
        reference=(result["old"],result["cold"])
        if common is None:common=reference
        need(reference==common,"different independent old or edited native output")
        markers=load(prior/"native-markers.json")
        native_edited=load(prior/"edit/native.json")
        actual_ast,=[r["argv"] for r in native_edited["rustcs"] if r["crate"]=="ruff_python_ast"]
        need("/"+weights["namespaces"][role]+"/" in actual_ast[actual_ast.index("--out-dir")+1],"working Cargo namespace differs from the prior true transition")
        for phase in ("edit","unchanged-1","unchanged-2"):
            want = WANT[role] | ({"ruff_python_ast"} if phase=="edit" else set())
            need(physical_jobs(prior,phase)==want,"different physical native work")
            need(all(markers[phase][c]==[c in WANT[role],c not in WANT[role]] for c in residual.NAMES),"different warning provenance")
        now=load(prior/"counter/verified.json")
        summary[role]={"first-real-edit":cycle["first-real-edit"],"immediate-repeat":cycle["immediate-repeat"],"settled":now["Ir"],
                       "native_terminal":sha(prior/"complete.json"),"cycle_terminal":sha(rt.LOG/(name+"-edit-cycle")/"complete.json")}
    selections=save(rt.LOG/"physical-selections.json",history)
    save(rt.LOG/"terminal.json",{"all_selections":selections,"block":number,"order":order,"values":summary,"sources":SOURCE,
                                "first_edit_gate":"one real edit, same unmodified Cargo configuration, complete userspace Cargo and compiler guests","heldout":True})

if __name__=="__main__":
    if sys.argv[1]=="schedule": print(json.dumps(schedule(),sort_keys=True,indent=2))
    elif sys.argv[1]=="old": old(Path(sys.argv[2]))
    else: block(sys.argv[1],Path(sys.argv[2]),Path(sys.argv[3]))
