"""Collect complete ordinary Ruff example builds with independent packaged SDKs and real Xcode tools."""
from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from examples_exec import ExecTrace
from examples_reader import (CMD, FOCAL, LOCK, NAMES, PHASES, RUFF, TREE, checked_example_artifacts,
                             events_census, source_variant, verify)
from fixture import allocated_sections, compressed, digest, enroll_sdk, environment
from packages import need, save, sha
from readback import Corpus


def environment_for(root, role):
    env=environment(root,role)
    base=root/("ordinary-"+role)
    env["CARGO_TARGET_DIR"]=str(base/"target")
    env["CARGO_BUILD_BUILD_DIR"]=str(base/"shared")
    return env


def cmd(argv,**kwargs):
    return subprocess.check_output(argv,**kwargs)


def prepare_ruff(root):
    repo=root/"ruff"
    subprocess.run(["git","init","-q",repo],check=True)
    def git(*args): return cmd(["git","-C",repo,*args],text=True).strip()
    git("fetch","-q","--no-tags","--depth=1","https://github.com/astral-sh/ruff.git",RUFF)
    git("switch","-q","--detach","FETCH_HEAD")
    src=root/"receipts"
    head,tree,lock=git("rev-parse","HEAD"),git("rev-parse","HEAD^{tree}"),sha(repo/"Cargo.lock")
    need((head,tree,lock)==(RUFF,TREE,LOCK),"public Ruff checkout is not the preregistered tree")
    files=sorted(p.stem for p in (repo/FOCAL).parent.glob("*.rs"))
    need(files==list(NAMES),"unexpected source fixture inventory")
    old=(repo/FOCAL).read_bytes()
    source_variant(old,"old")
    compressed(src/"source-old.gz",old)
    env=environment_for(root,"20")
    env.pop("CARGO_NET_OFFLINE")
    subprocess.run(["cargo","+ohm","fetch","--locked","--target","aarch64-apple-darwin"],
                   cwd=repo,env=env,check=True,timeout=900)
    packages={r["name"]+"-"+r["version"]+".crate":r["checksum"]
              for r in tomllib.loads((repo/"Cargo.lock").read_text())["package"] if "checksum" in r}
    archives=sorted((Path(env["CARGO_HOME"])/"registry").glob("cache/*/*.crate"))
    need(len(archives)>20 and all(sha(p)==packages.get(p.name) for p in archives),
         "downloaded registry input does not match Ruff Cargo.lock")
    save(src/"ruff.json",{"head":head,"tree":tree,"cargo_lock":lock,"examples":files,
                          "registry_checksums":len(archives)})
    return repo


def tool_facts(root,role):
    def xcrun(tool): return Path(cmd(["/usr/bin/xcrun","--find",tool],text=True).strip())
    paths={k:root/("sdk-"+role)/"bin"/k for k in ("rustc","cargo")}
    paths.update({k:xcrun(k) for k in ("ld","clang")})
    facts={}
    for name,literal in paths.items():
        p=literal.resolve(strict=True)
        signed=subprocess.run(["/usr/bin/codesign","-d","--verbose=5",p],capture_output=True,check=True)
        output=(signed.stdout+signed.stderr).decode()
        hashes=re.findall(r"^CDHash=([a-fA-F0-9]{40})$",output,re.M)
        need(len(hashes)==1,"could not enroll a single native signing identity "+name)
        facts[name]={"literal":str(literal),"physical":str(p),"sha256":sha(p),"cdhash":hashes[0].lower(),
                     "codesign":output}
    return facts


def cache_census(stores,roots,receipts):
    observed={}
    for name in NAMES:
        root=Path(roots[name]).resolve(strict=True)
        need(root.is_relative_to(stores.resolve(strict=True)),"incremental directory escaped enrolled stores")
        crates=[root] if root.name.startswith(name+"-") else sorted(root.glob(name+"-*"))
        files=[]
        for crate in crates:
            for s in sorted(crate.glob("s-*")):
                if not s.is_dir() or s.is_symlink() or s.name.endswith("-working"): continue
                for fname in ("dep-graph.bin","work-products.bin"):
                    p=s/fname
                    if p.is_file() and not p.is_symlink():
                        data=p.read_bytes(); h=digest(data)
                        compressed(receipts/"cache"/(h+".gz"),data)
                        files.append([str(p),len(data),h])
        need(files,"no real finalized incremental session for "+name+" under "+str(root))
        observed[name]=files
    return observed


def phase(root,repo,role,tag,state,old,env,stores,tools,trace,roots):
    src=root/"receipts"
    out=src/role/"examples"/tag
    out.mkdir(parents=True)
    expect=source_variant(old,state)
    p=repo/FOCAL
    if p.read_bytes()!=expect: p.write_bytes(expect)
    need(p.read_bytes()==expect,"incomplete source placement")
    compressed(out/"source.gz",expect)
    if tag in ("cold","clean-old","clean-new"):
        need(not stores.exists() and shutil.disk_usage(root).free>5*2**30,"nonempty registry or low space")
        for name in ("target","shared"): (stores/name).mkdir(parents=True)
        pre=[len(list((stores/k).iterdir())) for k in ("target","shared")]
    else:
        pre=None
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        code,rows=trace.command(CMD,cwd=repo,env=env,out=stdout,err=stderr,timeout=900)
        stdout.seek(0); stderr.seek(0)
        log=stdout.read()
        compressed(out/"cargo.stdout.gz",log); compressed(out/"cargo.stderr.gz",stderr.read())
    compressed(out/"kernel.json.gz",json.dumps(rows,separators=(",",":")).encode())
    save(out/"invocation.json",{"argv":CMD,"exit":code,"initial_counts":pre,"state":state})
    counts=events_census(rows,tools)
    returned=checked_example_artifacts(log,code==0)
    need((code==0)==(state!="invalid"),"unexpected real Cargo status")
    for unit in counts["rustcs"]:
        if unit["example"] and unit["mode"]=="full": roots[unit["crate"]]=unit["incremental"][0]
    programs={}
    owned={}
    for ld in counts["true_xcode_ld"]:
        if ld["example"]:
            need(ld["crate"] not in owned,"more than one real ld for one example")
            owned[ld["crate"]]=Path(ld["output"])
    if code==0:
        cache=cache_census(stores,roots,src)
        runenv={k:v for k,v in env.items() if k in ("HOME","PATH","LANG","LC_ALL","TZ","TMPDIR")}
        runenv.update(NO_COLOR="1",CLICOLOR="0")
        for n,r in sorted(returned.items()):
            path=Path(r["executable"])
            need(path.is_absolute() and path.is_file() and path.resolve().is_relative_to(stores.resolve()),
                 "returned artifact outside enrolled stores")
            original=path.read_bytes()
            h=digest(original)
            compressed(src/"binaries"/(h+".gz"),original)
            result=subprocess.run([str(path)],env=runenv,cwd=repo,stdin=subprocess.DEVNULL,capture_output=True,timeout=20)
            ld=owned.get(n)
            corroboration=None
            if ld is not None:
                need(ld.is_file() and ld.resolve().is_relative_to(stores.resolve()) and sha(ld)==h,
                     "typed return differs from genuine ld-produced file for "+n)
                corroboration={"path":str(ld),"sha256":sha(ld),"same_inode":ld.samefile(path)}
            programs[n]={"path":str(path),"raw":h,"sections":allocated_sections(original),
                         "exit":result.returncode,"stdout":compressed(out/(n+".stdout.gz"),result.stdout),
                         "stderr":compressed(out/(n+".stderr.gz"),result.stderr),"kernel_output":corroboration}
    else:
        cache={}
    save(out/"observed.json",{"argv":CMD,"exit":code,"initial_counts":pre,"counts":counts,
                              "native_programs":programs,"cache":cache})
    print(role,tag,"real rustcs",counts["all_typed_rustcs"],"true ld",len(counts["true_xcode_ld"]),
          "examples",sorted(owned),flush=True)


def run(root):
    root=root.resolve()
    repo=prepare_ruff(root)
    old=(repo/FOCAL).read_bytes()
    r=root/"receipts"
    trace=ExecTrace()
    try:
        trace.ready()
        for role in ("20","21"):
            env=environment_for(root,role)
            enroll_sdk(root,role,env)
            tools=tool_facts(root,role)
            save(r/role/"examples-tools.json",tools)
            stores=root/("ordinary-"+role)
            roots={}
            try:
                for tag,state in PHASES:
                    if tag in ("clean-old","clean-new"):
                        retained=root/(role+"-before-"+tag)
                        need(stores.is_dir() and not stores.is_symlink() and not retained.exists(),
                             "foreign owned storage transition")
                        stores.rename(retained); roots={}
                    phase(root,repo,role,tag,state,old,env,stores,tools,trace,roots)
            finally:
                if (repo/FOCAL).read_bytes()!=old: (repo/FOCAL).write_bytes(old)
            need(not cmd(["git","diff","--name-only"],cwd=repo),"unrepaired public source fixture")
    finally:
        trace.close()
    result=verify(Corpus(r))
    save(r/"independent.json",result)


if __name__=="__main__":
    if sys.argv[1]=="read":
        c=Corpus(Path(sys.argv[2]))
        result=verify(c)
        need(result==c.json("independent.json"),"external archive readback disagrees")
        print(json.dumps(result,sort_keys=True))
    else:
        root=Path(sys.argv[1])
        try:
            run(root)
        except Exception as e:
            save(root/"receipts"/"examples-failure.json",{"type":type(e).__name__,"message":str(e)})
            raise
