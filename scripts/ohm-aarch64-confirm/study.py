"""Three source-attested SDKs and one counterbalanced GNU AArch64 Ruff block per runner."""
import hashlib
import itertools
import json
import os
from pathlib import Path
import shutil
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
    key = lambda half,p:hashlib.sha256(f"GNU-compact-heldout-v1/{half}/{p}".encode()).digest()
    return {f"{i:02d}":p for i,p in enumerate([p for half in (1,2) for p in sorted(seq,key=lambda p:key(half,p))],1)}

def old(base):
    # Its working root and SDK restore are isolated in a separate process from the timed path.
    need((base/"key").read_text().strip()==ORIGINAL,"unregistered original capsule")
    select, _, _=compare.installable(base/"sdk.tar.zst",ORIGINAL,base/"native")
    select("P")

def setup(ancestor, inputs):
    kit.bind()
    current, pair, _ = compare.installable(inputs/"sdk.tar.zst",CURRENT,inputs/"native",expected_tree=kit.TREE)
    oldA, oldN = (load(ancestor/"receipts"/(k+"-sdk.json")) for k in "PC")
    need(oldN==pair["P"],"the shared physical N component is not identical across both transports")
    roles = {"A":oldA,"N":pair["P"],"M":pair["C"]}
    need({k:v["source"] for k,v in roles.items()}==SOURCE,"wrong three source revisions")
    name, = (n for n in oldA["files"] if n.startswith("lib/librustc_driver"))
    ref = dict(oldA["files"]); del ref[name]
    for k,v in roles.items():
        files = dict(v["files"])
        need(files.pop(name)[0]==DRIVER[k] and len(files)==118 and files==ref,"more than the one physical driver changed")
        save(rt.LOG/("subject-"+k+".json"),v)
    def select(k):
        diff = current("C" if k=="M" else "P")
        need(diff==[name],"additional compiler operand changed")
        if k=="A":
            src=ancestor/"donor-P"/name; dest=rt.SDK/name; tmp=dest.with_name(dest.name+".reinstall")
            need(not tmp.exists() and sha(src)==DRIVER[k],"wrong ancestor driver")
            shutil.copyfile(src,tmp)
            tmp.chmod(oldA["files"][name][2])
            os.replace(tmp,dest)
        need([sha(rt.SDK/name),(rt.SDK/name).stat().st_size,(rt.SDK/name).stat().st_mode&0o777]==roles[k]["files"][name],"wrong active driver")
        return diff
    return select

def physical_jobs(prior, phase):
    j=load(prior/phase/"native.json")
    # Also bound all successful execve events on independent readback, including the Rustup hop.
    need(not j["link_tools"] and not j["compiler_probes"] and len(j["cargo"])==1,"unregistered process")
    return {r["crate"] for r in j["rustcs"]}

def block(number, ancestor, inputs):
    order=schedule()[number]
    need(load(HERE/"schedule.json")==schedule(),"changed blocked order")
    select=setup(ancestor,inputs)
    rt.select=select
    rt.select("A")
    q.counter=tree_ir.measure
    tree_ir.calibrate()
    q.prepare_graph()
    save(rt.LOG/"heldout-registration.json", {"block":number,"order":order,"source":SOURCE,"drivers":DRIVER,"schedule":sha(HERE/"schedule.json"),
        "original":ORIGINAL,"current":CURRENT,"cpu":Path("/proc/cpuinfo").read_text().split("model name",1)[-1].splitlines()[0],
        "boot_digest":sha(Path("/proc/sys/kernel/random/boot_id")),"signed_tools":rt.TOOLS,"cross_gcc":physical(Path(q.CROSS)),
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
        for phase in ("edit","unchanged-1","unchanged-2"):
            want = WANT[role] | ({"ruff_python_ast"} if phase=="edit" else set())
            need(physical_jobs(prior,phase)==want,"different physical native work")
            need(all(markers[phase][c]==[c in WANT[role],c not in WANT[role]] for c in residual.NAMES),"different warning provenance")
        now=load(prior/"counter/verified.json")
        summary[role]={"first-real-edit":cycle["first-real-edit"],"immediate-repeat":cycle["immediate-repeat"],"settled":now["Ir"],
                       "native_terminal":sha(prior/"complete.json"),"cycle_terminal":sha(rt.LOG/(name+"-edit-cycle")/"complete.json")}
    save(rt.LOG/"terminal.json",{"block":number,"order":order,"values":summary,"sources":SOURCE,
                                "first_edit_gate":"one real edit, same unmodified Cargo configuration, complete userspace Cargo and compiler guests","heldout":True})

if __name__=="__main__":
    if sys.argv[1]=="schedule": print(json.dumps(schedule(),sort_keys=True,indent=2))
    elif sys.argv[1]=="old": old(Path(sys.argv[2]))
    else: block(sys.argv[1],Path(sys.argv[2]),Path(sys.argv[3]))
