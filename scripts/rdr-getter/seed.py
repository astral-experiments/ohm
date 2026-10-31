"""Acquire exactly the locked Ruff source and checked registry inputs before any measurement."""
import os
from pathlib import Path
import shutil
import subprocess
import tomllib

from subjects import need,sha,put

PIN="93526150df078af7dd8fc4226cdcc469539d2001"
EDIT="64737b2a5c437934d0cebb88d1ea39addb34708a"
PARENT="ee278f44e0beeaed5798413c345b755322b4f80a"
LOCK="c9e345325bec5ff08dbbe3916edd39ad0c3d1c7797a8c241ae32f62754e764bf"
PATCH="bd5a3eacc9ee3959cd4df545dac8e0392adcfd89c8df00c229d6487b8cfe2831"
FILE="crates/ruff_notebook/src/notebook.rs"

def git(repo,*args):
    return subprocess.check_output(["git","-C",repo,*map(str,args)],env={**os.environ,"GIT_OPTIONAL_LOCKS":"0","GIT_TERMINAL_PROMPT":"0"})

def prepare(root,out,sdk,adapter):
    store=root/"seeds";store.mkdir()
    raw=store/"ruff.git";subprocess.run(["git","init","--bare","-q",raw],check=True)
    git(raw,"fetch","--quiet","--depth=2","--no-tags","--no-recurse-submodules","https://github.com/astral-sh/ruff.git",PIN,EDIT)
    need(git(raw,"rev-parse",EDIT+"^").decode().strip()==PARENT,"historical change parent")
    for n in (PIN,EDIT):git(raw,"update-ref","refs/heads/frozen-"+n,n)
    repo=store/"fetch";subprocess.run(["git","clone","--quiet","--shared","--no-checkout",raw,repo],check=True)
    git(repo,"checkout","--detach","--quiet",PIN)
    patch=git(repo,"diff","--binary","--full-index",PARENT,EDIT)
    import hashlib
    need(hashlib.sha256(patch).hexdigest()==PATCH and git(repo,"diff","--name-only",PARENT,EDIT).decode().splitlines()==[FILE],"patch identity")
    (out/"getter.patch").write_bytes(patch)
    need(sha(repo/"Cargo.lock")==LOCK and b"pub fn metadata(" not in (repo/FILE).read_bytes(),"wrong starting Ruff")
    git(repo,"apply","--reverse","--check",out/"getter.patch")
    proxies=Path(shutil.which("rustup")).resolve().parent
    env=adapter.environment(store/"seed-slot",sdk,proxies);env.pop("CARGO_NET_OFFLINE",None)
    subprocess.run(["cargo","+ohm","fetch","--locked"],cwd=repo,env=env,check=True,stdout=subprocess.DEVNULL)
    need(sha(repo/"Cargo.lock")==LOCK and not Path(env["CARGO_TARGET_DIR"]).exists(),"registry acquisition changed source or compiled")
    names={p["name"]+"-"+p["version"]+".crate":p["checksum"] for p in tomllib.loads((repo/"Cargo.lock").read_text())["package"] if "checksum" in p}
    registry=Path(env["CARGO_HOME"])/"registry"
    cache, = (registry/"cache").iterdir()
    need(len(names)==498 and all(sha(cache/n)==v for n,v in names.items()),"incomplete locked archive set")
    for dep in tomllib.loads((repo/"Cargo.lock").read_text())["package"]:
        if "checksum" not in dep: continue
        n=dep["name"];prefix=str(len(n)) if len(n)<3 else ("3/"+n[0] if len(n)==3 else n[:2]+"/"+n[2:4])
        need((registry/"index"/cache.name/".cache"/prefix/n).is_file(),"missing sparse index "+n)
    put(out/"ruff-seed.json",{"ruff":PIN,"tree":git(repo,"rev-parse","HEAD^{tree}").decode().strip(),"edit":EDIT,"parent":PARENT,"original_file":sha(repo/FILE),"patch":PATCH,"lock":LOCK,"registry":names,"proxy":[str(proxies),sha(proxies/"rustup")]})
    return raw,registry,proxies
