"""Enroll the actual Linux compiler processes launched by unchanged, ordinary Cargo."""
from pathlib import Path
import json
import os
import re
import runpy
import subprocess
import native
import material
HERE=Path(__file__).resolve().parent
EVENTS=runpy.run_path(str(HERE/"thread-meter/exec_events.py"))
def command(verbose=False):return [str(native.CARGO),*native.CMD,*(["-vv"]if verbose else [])]
def enroll(where,state,verbose=False):
    where.mkdir();rustc=native.SDK/"bin/rustc"
    EVENTS["capture"](where,command(verbose),native.environment(),str(native.SRC),EVENTS["file_id"](rustc))
    return read_enrollment(where,state,verbose)
def read_enrollment(where,state,verbose=False):
    root_image=EVENTS["file_id"](native.CARGO);compiler_image=EVENTS["file_id"](native.SDK/"bin/rustc")
    data=native.read(where/"kernel-events.json");ev=EVENTS["decode"](data)
    assert ev["exits"][ev["root"]]==0
    r,=[r for r in ev["images"]if r["pid"]==ev["root"]];assert r["file"]==root_image and r["argv"]==command(verbose)
    known={"build_script_build","uv_python"} if state=="A" else {"build_script_build","uv_python","uv_cli"}
    matches={};others=[]
    for x in ev["images"]:
        if x["file"]!=compiler_image:continue
        args=x["argv"];assert args[0]==str(native.SDK/"bin/rustc")
        if "--crate-name"not in args:others.append(args);continue
        n=args[args.index("--crate-name")+1];assert n in known and n not in matches and ev["exits"][x["pid"]]==0
        assert "-C" in args and any("link" in a for a in args if a.startswith("--emit"))
        y=x["pid"];seen=set()
        while y!=ev["root"]:
            assert y not in seen;seen.add(y);y=ev["births"][y]
        matches[n]={"argv":args,"pid":x["pid"],"exe":x["exe"],"inode":x["file"],"exit":0}
    assert set(matches)==known,(known,matches.keys())
    out={"root":ev["root"],"targets":matches,"other_rustc_queries":sorted(others),"kernel_sha":native.sha(where/"kernel-events.json"),"cargo":r["argv"]}
    if verbose:
        reasons={};stderr=(where/"stderr").read_text()
        cargo_vars=re.findall(r"(?:^|[ `])CARGO=([^ \n]+) ",stderr,re.M)
        assert len(cargo_vars)>=len(known)and set(cargo_vars)=={str(native.CARGO)},cargo_vars
        out["resolved_cargo_assignments"]=cargo_vars
        for line in stderr.splitlines():
            m=re.fullmatch(r"\s*Dirty (uv-[a-z0-9-]+) v[^ ]+ \([^\n]+?\): (.*)",line)
            if m:assert m[1]not in reasons;reasons[m[1]]=m[2]
        assert reasons.get("uv-python")==material.CASE["stage1_six_dirty"]["uv-python"]
        if state=="A":assert reasons==material.CASE["stage1_six_dirty"],reasons
        else:assert "uv-cli" in reasons
        out["dirty"]=reasons
    native.save(where/"observed-rustcs.json",out);return out
def vectors(row):return {k:v["argv"] for k,v in sorted(row["targets"].items())}
def match(left,right):
    assert vectors(left)==vectors(right) and left["other_rustc_queries"]==right["other_rustc_queries"]
    return {"matched":sorted(left["targets"]),"complete_arguments":{k:len(v)for k,v in vectors(left).items()}}

