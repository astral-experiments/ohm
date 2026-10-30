"""Trace the original developer-mode Apple 83-program enrollment on the two published SDKs."""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent/"ohm-apple-zmij")]
from packages import RELEASES,need
from study import check_host,env_for,load,physical,save,sha,sdk_id
from prepare import prepare_ruff
from ty_links import A,B,CensusTrace,TREES,enrolled
from ty_compare import run_pair_workspace
from dyld import check as dyld_check

SUBJECTS={"P":"20","C":"21"}
RUST={"20":"7e71d3150938ff8ed82aca03416439d7e5b87ef3","21":"c79998a5cd143c445a4b2528f20953b176a65c5d"}
VISITS=(("cold","old"),("unchanged-old","old"),("edit","new"),("repeat-1","new"),("repeat-2","new"),
        ("invalid","bad"),("repair","new"))
PROVIDER="ec3618020c043badf854255ef0374597fac067e4b9c497d28e469e63674165bd"

def tools(root,role):
    sdk=root/("sdk-"+role)
    result={}
    paths={k:sdk/"bin"/k for k in ("cargo","rustc")}
    for k in ("ld","clang"):
        paths[k]=Path(subprocess.check_output(["/usr/bin/xcrun","--find",k],text=True).strip())
    for name,p in paths.items():
        p=p.resolve(strict=True)
        r=subprocess.run(["/usr/bin/codesign","-d","--verbose=5",p],capture_output=True,check=True)
        raw=r.stdout+r.stderr; cd=re.findall(rb"(?m)^CDHash=([0-9a-fA-F]{40})$",raw)
        need(len(cd)==1,"missing actual "+name+" signing identity")
        result[name]={"physical":str(p),"sha256":sha(p),"cdhash":cd[0].decode().lower(),"codesign":raw.decode()}
    return result

def run(root):
    root=root.resolve(strict=True); receipts=root/"receipts"
    save(receipts/"host-storage.json",check_host(root,65))
    needed={"P":root/"sdk-20","C":root/"sdk-21"}
    (root/"signed").symlink_to(needed["P"],target_is_directory=True)
    prepare_ruff(root,A,B,enrolled)
    save(receipts/"packaged-workspace.json",{"protocol":"previous Apple workspace enrollment 83a420aa3a65343960d998f4f3b8421c95b7f790",
          "source":[A,B],"trees":TREES,"subjects":SUBJECTS,"rust":RUST,"provider_sha256":PROVIDER,"visits":VISITS,
          "wall_metric":False})
    for sym,role in SUBJECTS.items():
        sdk=needed[sym];registration=load(receipts/role/"custody.json")
        need(registration["source"]["release_id"]==RELEASES[role][0] and
             registration["provenance"]["sources"]["rust"]["revision"]==RUST[role],"wrong actual released compiler")
        env=env_for(root/("enroll-sdk-"+role),sdk)
        identity=sdk_id(sdk,env)
        need(RUST[role] in identity["rustc_version"] and registration["provenance"]["sources"]["cargo"]["revision"] in identity["cargo_version"],
             "different physical rustc/Cargo")
        save(receipts/role/"physical-tools.json",tools(root,role));save(receipts/role/"native-sdk.json",identity)
        dyld_check(root,role,sdk,receipts/role/"dyld",paths=[])
    trace=CensusTrace()
    try:
        trace.ready()
        safe=run_pair_workspace(root,trace,release_roles=needed,visits=VISITS)
    finally:
        trace.close()
    save(receipts/"workspace-collection.json",{"all_same_role_programs_admitted":safe,
         "whole_image_decision":"each installation and each release must agree with its own empty reference",
         "cross_release_clean_images":"diagnostic only: the two source and entire PGO toolchains differ"})

if __name__=="__main__":
    p=Path(sys.argv[1]);root=p.resolve(strict=True)
    try:run(root)
    except Exception as exc:
        import traceback
        save(root/"receipts"/"workspace-failure.json",{"type":type(exc).__name__,"message":str(exc),"traceback":traceback.format_exc()})
        raise
