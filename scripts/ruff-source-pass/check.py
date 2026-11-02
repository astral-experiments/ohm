"""Verify ordinary signed Cargo, physical pass execution, fresh outputs and a real native test."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"ruff-workspace-remat"))
import source_pass as native


def run(cmd, cwd, env, code=0):
    p=subprocess.run([str(a) for a in cmd],cwd=cwd,env=env,capture_output=True,text=True,timeout=45)
    native.need(p.returncode==code,(cmd,p.returncode,p.stderr[-2300:]))
    return p


def check(root, manifest, rustup, proxies, host_control=False):
    native.need(not root.exists(), "requires a new dedicated fixture")
    root.mkdir()
    repo=root/"ruff"
    work=root/"work"
    work.mkdir()
    pkg=repo/"crates/ty_server"
    (pkg/"src").mkdir(parents=True)
    (pkg/"tests/e2e").mkdir(parents=True)
    (repo/"Cargo.toml").write_text('[workspace]\nmembers = ["crates/ty_server"]\nresolver = "2"\n[profile.dev]\nopt-level = 1\n')
    (pkg/"Cargo.toml").write_text('[package]\nname = "ty_server"\nversion = "0.0.0"\nedition = "2024"\n')
    (repo/"Cargo.lock").write_text('version = 4\n\n[[package]]\nname = "ty_server"\nversion = "0.0.0"\n')
    m=native.validate(manifest,host_control=host_control)
    sdk=Path(m["signed_rustc"]).parent.parent
    base={"PATH":str(proxies)+":/usr/bin:/bin","LC_ALL":"C","HOME":str(root),
          "LD_LIBRARY_PATH":str(sdk/"lib"),"RUSTUP_HOME":str(rustup),"RUSTUP_AUTO_INSTALL":"0",
          "CARGO_HOME":str(work/"cargo-home"),"CARGO_NET_OFFLINE":"true","RUSTC":str(sdk/"bin/rustc"),
          "CARGO_TARGET_DIR":str(work/"target"),"CARGO_BUILD_BUILD_DIR":str(work/"build")}
    cab=["cargo","+ohm","test","-p","ty_server","--test","e2e","--no-run","--locked","--offline","-j2","--message-format=json"]
    output={}
    for arm in ("unwrapped","signed","stock","strict"):
        observed={}
        for phase,v,name in (("old","17","old"),("new","29","fresh"),("unchanged","29","fresh"),
                             ("invalid","false","fresh"),("repair","29","fresh"),("inspect","31","last")):
            inspected=phase=="inspect"
            env=base if arm=="unwrapped" else native.select(m,arm,base,inspected)[0]
            for dest,body in ((pkg/"src/lib.rs","#[inline(never)] pub fn value() -> u32 { "+v+" }\n"),
                              (pkg/"tests/e2e/main.rs","#[test]\nfn "+name+"() { assert_eq!(ty_server::value(), "+
                               (v if v!="false" else "29")+"); }\n")):
                if not dest.exists() or dest.read_text()!=body:dest.write_text(body)
            mark=None if arm=="unwrapped" else native.snapshot(env)
            q=run(cab,repo,env,101 if phase=="invalid" else 0)
            rows=list(map(json.loads,q.stdout.splitlines()))
            native.need(rows[-1]=={"reason":"build-finished","success":phase!="invalid"},"missing Cargo terminal")
            products=[r for r in rows if r["reason"]=="compiler-artifact"]
            dirty=sorted(r["target"]["name"] for r in products if not r["fresh"])
            native.need(phase!="unchanged" or not dirty,("unexpected warm rebuild",arm,dirty))
            if phase=="invalid":
                native.need(any((r.get("message",{}).get("code") or {}).get("code")=="E0308" for r in rows),"missing E0308")
                h=None
            else:
                exe,=[Path(r["executable"]) for r in products if r.get("executable")]
                native.need("1 passed; 0 failed" in run([exe,"--exact",name],repo,env).stdout,"wrong compiled test")
                h=native.sha(exe)
            events=[] if mark is None else native.collect(env,mark,arm,inspected)
            if phase=="unchanged":
                native.need(not events,("a fresh unit actually invoked rustc",arm,events))
            if arm in ("stock","strict") and phase in ("old","new"):
                native.need({e["owner"] for e in events}=={"ty_server","e2e"},"native scope")
            if arm in ("stock","strict") and inspected:
                native.need(sum(e["counts"]["machines"] for e in events)>0,"missing real inspected machine function")
            guarded=sorted(str(p.relative_to(work)) for p in work.rglob("*.d") if b"ohm-untracked-relink-inputs" in p.read_bytes())
            if phase in ("old","new","unchanged"):
                native.need(not guarded,("unexpected untracked codegen marker",arm,phase))
            actual={"binary":h,"dirty":dirty,"depinfo":guarded,
                    "keys":sorted((r["package_id"],r["target"]["name"],r["filenames"]) for r in products)}
            if arm!="unwrapped":
                native.need(actual==output["unwrapped"][phase]["actual"],("different product from signed original",arm,phase))
            observed[phase]={"actual":actual,"native":events}
        output[arm]=observed
        for name in ("cargo-home","target","build"):
            dest=work/name
            if dest.is_dir():
                native.need(not dest.is_symlink() and dest.parent==work,"foreign fixture output")
                shutil.rmtree(dest)
    # These alternatives use no target standard library and exercise the actual signed target machine.
    (pkg/"src/lib.rs").write_text('''#![allow(internal_features)]
#![feature(no_core, lang_items)]
#![no_core]
#[lang="pointee_sized"] pub trait PointeeSized {}
#[lang="meta_sized"] pub trait MetaSized: PointeeSized {}
#[lang="sized"] pub trait Sized: MetaSized {}
#[lang="copy"] pub trait Copy: Sized {}
#[unsafe(no_mangle)] pub extern "C" fn ohm_identity(x: u64) -> u64 { x }
''')
    alternatives={}
    for arm in ("unwrapped","signed","stock","strict"):
        env=base if arm=="unwrapped" else native.select(m,arm,base,True)[0]
        values={}
        for target in ("aarch64-unknown-linux-gnu","wasm32-unknown-unknown"):
            mark=None if arm=="unwrapped" else native.snapshot(env)
            cli=["cargo","+ohm","build","-p","ty_server","--lib","--target",target,"--locked","--offline","--message-format=json"]
            q=run(cli,repo,env)
            rows=list(map(json.loads,q.stdout.splitlines()))
            filenames=[Path(f) for row in rows if row["reason"]=="compiler-artifact" and not row["fresh"] for f in row["filenames"] if f.endswith(".rlib")]
            archive,=filenames
            events=[] if mark is None else native.collect(env,mark,arm,True)
            if arm!="unwrapped":native.need(len(events)==1 and events[0]["owner"]=="ty_server","wrong target compiler scope")
            members=run(["ar","t",archive],repo,env).stdout.splitlines()
            native.need(len(members)==len(set(members)),"ambiguous archive members")
            hashes={member:hashlib.sha256(subprocess.check_output(["ar","p",archive,member],cwd=repo,env=env)).hexdigest() for member in members}
            # Independently empty rustc incremental roots choose different short temporary suffixes.
            objects={re.sub(r"\.[a-z0-9]{7}(?=\.rcgu\.o$)","",name):sha for name,sha in hashes.items() if name.endswith(".o")}
            native.need(objects and len(objects)==sum(n.endswith(".o") for n in hashes),("empty or ambiguous cross-target objects",target))
            values[target]={"archive":native.sha(archive),"members":hashes,"objects":objects,"native":events}
            if arm!="unwrapped":
                native.need(objects==alternatives["unwrapped"][target]["objects"],("changed native target objects",arm,target,objects,alternatives["unwrapped"][target]["objects"]))
        alternatives[arm]=values
        for name in ("cargo-home","target","build"):
            dest=work/name
            if dest.is_dir():
                native.need(not dest.is_symlink() and dest.parent==work,"foreign fixture output")
                shutil.rmtree(dest)
    output["cross-target"]=alternatives
    (root/"passed.json").write_text(json.dumps(output,sort_keys=True)+"\n")
    print("32 signed Cargo commands passed native, unchanged, invalid and cross-target controls",flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("work","manifest","rustup-home","proxies"):
        p.add_argument("--"+arg,type=Path,required=True)
    p.add_argument("--host-rebuild-control",action="store_true")
    a=p.parse_args()
    check(a.work.resolve(),a.manifest.resolve(strict=True),a.rustup_home.resolve(strict=True),a.proxies.resolve(strict=True),a.host_rebuild_control)
