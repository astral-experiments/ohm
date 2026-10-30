"""Compare real workspace links on the same #293 Cargo after the libm math marker change."""
import argparse
from pathlib import Path
import tomllib

from dyld import check as check_dyld
from measure import select
from prepare import prepare_ruff
from receipt_cargo import CANDIDATE
from study import CHILD,PARENT,load,need,save,sha
from ty_compare import run_pair_workspace
from ty_links import A,B,CensusTrace,enrolled

LIBM = "b6d2cec3eae94f9f509c767b45932f1ada8350c4bdb85af2fcab4a3c14807981"
ENDS = ("edit","repeat-1","repeat-2","repair")

def seed(root):
    prepare_ruff(root,A,B,enrolled)
    pkgs=tomllib.loads((root/"ruff/Cargo.lock").read_text())["package"]
    locked,=[x for x in pkgs if x["name"]=="libm" and x["version"]=="0.2.16"]
    package,=(root/"seed/registry/cache").glob("*/libm-0.2.16.crate")
    need(sha(package)==locked["checksum"]==LIBM,"different libm registry artifact")
    save(root/"receipts/libm-registration.json",{"rust":[PARENT,CHILD],"cargo":CANDIDATE,"ruff":[A,B],"libm":LIBM,
        "goal":"count which of the 83 tests truly relink on the edit, repeats and repair; both roles use fixed Cargo",
        "timed":False})

def run(root):
    registration=load(root/"receipts/libm-registration.json")
    need(registration["rust"]==[PARENT,CHILD] and registration["cargo"]==load(root/"receipts/fixed-cargo-293.json")["commit"],"wrong pin")
    native=root/"receipts/provider-matrix"
    need(load(native/"terminal.json")["passed"] and load(native/"terminal.json")["commands"]==392,"failed direct/transitive native ownership")
    for r in "PC":
        check_dyld(root,r,select(root,r),root/"receipts/workspace-dyld"/r)
        for place in ("direct","library"):
            v=load(native/f"{r}-{place}-unwatched-default/lower/warm/verified.json")
            need(any(m["hard"] for m in v["marker"].values())==(r=="P") and any(m["recheck"] for m in v["marker"].values())==(r=="C"),
                 "math assembly did not select the expected marker in provider case")
    trace=CensusTrace()
    try:
        trace.ready();run_pair_workspace(root,trace)
    finally:trace.close()
    top=root/"receipts/ty-comparison/workspace"
    summaries=load(top/"paired-physical.json")
    outcome={}
    for phase in ENDS:
        details={}
        for r in "PC":
            row=load(top/r/"visit"/phase/"verified.json")
            units=row["libm"]
            need(units and all(u["hard"]==(r=="P") and u["recheck"]==(r=="C") for u in units),"libm markers differ")
            summary=summaries[r][phase]
            need(summary["test_count"]==83 and not summary["mismatches_to_clean_B"],"wrong clean workspace outputs")
            details[r]={**summary,"libm_compiled":row["native"]["full"].count("libm"),"native_drivers":len(row["native"]["cargo_link_driver"])}
        logical=lambda r:{(pkg,name,tuple(kind)) for pkg,name,kind in details[r]["linked_tests"]}
        outcome[phase]={"roles":details,"saved":sorted(logical("P")-logical("C")),"added":sorted(logical("C")-logical("P"))}
    save(root/"receipts/libm-workspace.json",outcome)
    for phase,info in outcome.items():
        print(phase,{r:[len(v["physical_rustcs"]),len(v["link_only"]),v["all_linkers"],len(v["linked_tests"])] for r,v in info['roles'].items()},flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("mode",choices=("seed","run"));p.add_argument("root",type=Path)
    a=p.parse_args();(seed if a.mode=="seed" else run)(a.root.resolve(strict=True))
