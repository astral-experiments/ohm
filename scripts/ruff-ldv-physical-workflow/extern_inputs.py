"""Capture the real named registry inputs and their producers on independent, uncounted Ruff builds."""
import ast
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import runtime
import shards
from runtime import need,put,sha,support

WATCH={"option":{"indexmap","pep440_rs","serde","toml"},
       "e2e":{"insta","lsp_server","serde","serde_json","thiserror"}}


def cached(store,path):
    st=runtime.stat_id(path)
    need(0<st[2]<=128<<20 and shutil.disk_usage(store).free>15*(1<<30)+st[2],"capture would exceed the original disk reserve")
    h=sha(path)
    known=store/h
    if not known.exists():
        need(sum(p.stat().st_size for p in store.iterdir())<640<<20,"separate input-capture budget exceeded")
        with path.open("rb") as src,known.open("xb") as dst,gzip.GzipFile(filename="",fileobj=dst,mode="wb",compresslevel=3,mtime=0) as gz:
            shutil.copyfileobj(src,gz,1<<20)
    need(st==runtime.stat_id(path),"input changed while copying")
    return {"sha":h,"size":st[2],"stat":st}


def opts(xs,name):
    return [value for i,value in enumerate(xs) if i and xs[i-1]==name]


def exec_environment(trace,process):
    matches=[]
    for line in trace.open():
        if not line.startswith("execve") or not line.rstrip().endswith("= 0"):
            continue
        m=support.EXEC.fullmatch(line.rstrip())
        if m:
            prog,argv,arr=(ast.literal_eval(v) for v in m.groups())
            if prog==process["exec"] and argv==process["argv"]:
                matches.append(dict(v.split("=",1) for v in arr))
    need(len(matches)==1,"different actual producer exec")
    return matches[0]


def path_key(path,env):
    return shards.map_path(str(path),shards.layout(env),set())


def ordinary_source(argv):
    return [Path(a) for a in argv if a.endswith(".rs") and Path(a).is_file()]


def capture(kit,loc,env,all_rusts,namespace,suite,role,phase):
    store=kit.evidence/"extern-inputs"
    store.mkdir(exist_ok=True)
    named={}
    for path in namespace["shared_owner_extern_paths"]:
        f=Path(path)
        # Cargo's keyed artifact directory retains the precise package under out/../../.
        if f.parents[2].name.replace("-","_") in WATCH[suite]:
            named[path_key(f,env)]={"path":str(f),"body":cached(store,f)}
    wanted=5 if suite=="option" else 10
    need(len(named)==wanted,("different genuine named extern input roster",suite,len(named),wanted))
    result={"role":role,"phase":phase,"named":named,"producers":{}}
    if phase=="new":
        put(loc/"extern-audit.json",result)
        return
    # Path bytes and producer ancestry are taken while the genuinely empty installation still exists.
    for row in named.values():
        f=Path(row["path"])
        package=f.parents[2].name.replace("-","_")
        producers=[r for r in all_rusts if r["kind"]=="full" and r["name"]==package and
                   opts(r["argv"],"--out-dir")==[str(f.parent)]]
        need(len(producers)==1,("no unique actually executing compiler for named output",str(f),package))
        r=producers[0]
        row["producer"]=r["pid"]
        if f.suffix==".rmeta":
            code=["rustc","+ohm","-Zls=all",f]
            v=subprocess.run(code,env=kit.base,capture_output=True,timeout=120,check=True)
            need(b"Crate info:" in v.stdout and b"Public hash:" in v.stdout and len(v.stdout)<48<<20,"invalid source-matched metadata listing")
            listing=loc/("metadata-"+package+".txt")
            listing.write_bytes(v.stdout)
            row["decoded"]={"member":listing.name,"sha":sha(listing),"bytes":len(v.stdout)}
        if str(r["pid"]) in result["producers"]:
            continue
        inputs={}
        for a in opts(r["argv"],"--extern"):
            name,sep,value=a.partition("=")
            if not sep:
                continue
            ext=Path(value)
            need(ext.is_absolute() and ext.is_file() and any(ext.is_relative_to(Path(env[k])) for k in
                 ("CARGO_BUILD_BUILD_DIR","CARGO_TARGET_DIR")),"unexpected direct producer dependency")
            inputs[a]=cached(store,ext)
        environ=exec_environment(loc/"trace"/f"exec.{r['pid']}",r)
        src=ordinary_source(r["argv"]);need(len(src)==1 and src[0].is_relative_to(Path(env["CARGO_HOME"])/"registry/src"),
                                               "registry compiler source is not the locked package")
        generated={}
        out=environ.get("OUT_DIR")
        if out:
            od=Path(out)
            need(od.is_dir() and any(od.is_relative_to(Path(env[k])) for k in
                 ("CARGO_BUILD_BUILD_DIR","CARGO_TARGET_DIR")),"unexpected generated-source directory")
            for p in sorted(od.rglob("*")):
                if p.is_file() and not p.is_symlink():
                    need(p.resolve().is_relative_to(od.resolve()),"generated source escaped OUT_DIR")
                    if p.stat().st_size:
                        generated[p.relative_to(od).as_posix()]=cached(store,p)
                    else:
                        generated[p.relative_to(od).as_posix()]={"sha":hashlib.sha256(b"").hexdigest(),"size":0}
            need(len(generated)<256,"unexpected generated output roster")
        # Only declared source and artifact directories are eligible for capture; no unrelated environment values are copied.
        depfiles={}
        for p in sorted(f.parent.glob("*.d")):
            if p.is_file() and p.stat().st_size:
                depfiles[p.name]=cached(store,p)
        result["producers"][str(r["pid"])]={"name":r["name"],"actual_exec":r["exec"],"argv":r["argv"],
             "source":[str(src[0]),cached(store,src[0])],"manifest":environ.get("CARGO_MANIFEST_DIR"),"extern":inputs,
             "out_dir":out,"generated":generated,"dep_info":depfiles}
    put(loc/"extern-audit.json",result)
