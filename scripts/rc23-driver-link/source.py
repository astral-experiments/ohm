"""Apply the positive Rust packet on top of the authenticated four-checkout release."""
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
import gate as g

def blob(repo,commit,path):
    mode,kind,oid,name=g.text(repo,"ls-tree",commit,"--",path).split()
    assert mode=="100644" and kind=="blob" and name==path
    data=g.git(repo,"cat-file","blob",oid)
    return {"mode":mode,"oid":oid,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}

def apply(repo,role,raw,checkout=True):
    assert (g.text(repo,"rev-parse","HEAD"),g.text(repo,"rev-parse","HEAD^{tree}"))==(g.BASE,g.TREE)
    p=role["packet"]
    assert raw[:8]==b"PACK\x00\x00\x00\x02" and len(raw)==p["bytes"] and hashlib.sha256(raw).hexdigest()==p["sha256"]
    assert hashlib.sha1(raw[:-20]).digest()==raw[-20:] and 0<len(raw)<1<<20
    out=g.git(repo,"index-pack","--strict","--stdin",input=raw).decode().split()
    assert out==["pack",raw[-20:].hex()]
    idx=Path(g.text(repo,"rev-parse","--path-format=absolute","--git-path","objects/pack"))/("pack-"+out[1]+".idx")
    objects={a[0]:a[1] for line in g.text(repo,"verify-pack","-v",str(idx)).splitlines() if len(a:=line.split())>=5 and len(a[0])==40}
    pos=set(g.text(repo,"rev-list","--objects","--no-object-names",role["commit"],"^"+g.BASE).splitlines())
    assert set(objects)==pos==set(p["objects"]) and len(pos)==int.from_bytes(raw[8:12],"big")
    assert list(objects.values()).count("commit")==1 and objects[role["commit"]]=="commit"
    assert g.text(repo,"rev-parse",role["commit"]+"^",role["commit"]+"^{tree}").splitlines()==[g.BASE,role["tree"]]
    changed=g.text(repo,"diff-tree","--no-commit-id","--no-renames","-r","--name-only",g.BASE,role["commit"]).splitlines()
    assert changed==list(g.PATHS)
    for path in changed:
        assert blob(repo,g.BASE,path)==role["files"][path]["before"] and blob(repo,role["commit"],path)==role["files"][path]["after"]
    if checkout:
        g.git(repo,"checkout","--quiet","--detach","--no-recurse-submodules",role["commit"])
        assert all(g.sha(repo/path)==r["after"]["sha256"] for path,r in role["files"].items())
    return {"objects":sorted(pos),"pack":p,"paths":changed}

def verify_sources(official,manifest,rust):
    names=("cargo","clippy","rustfmt");tools=[rust/"src/tools"/n for n in names]
    subprocess.run([official/"scripts/verify-release-sources.sh",manifest,rust,*tools],check=True)
    for name,p in zip(names,tools):
        r=g.POLICY["sources"][name]
        assert g.text(p,"rev-parse","HEAD","HEAD^{tree}").splitlines()==[r["revision"],r["tree"]]

def main():
    w=g.checkout("build");registered,role=g.selected();arm=os.environ["BENCH_ARM"]
    official=w/"official-release";rust=w/"source/rust";manifest=official/"toolchains/1.99.0/23.json"
    orig=g.read(w/"cross-evidence/source.json")
    assert orig["source_trees"]==g.POLICY["sources"] and orig["workflow"]==os.environ["GITHUB_SHA"] and orig["manifest_sha256"]==g.sha(manifest)
    for f,pin in g.POLICY["release_files"].items():
        assert g.sha(official/f)==pin["sha256"] and g.text(official,"rev-parse","HEAD:"+f)==pin["oid"]
    verify_sources(official,manifest,rust)
    assert g.text(rust,"rev-parse","HEAD","HEAD^{tree}").splitlines()==[g.BASE,g.TREE]
    proof=apply(rust,role,(g.HERE/"source.pack").read_bytes()) if arm=="T" else None
    commit,tree=g.text(rust,"rev-parse","HEAD","HEAD^{tree}").splitlines()
    with tempfile.TemporaryDirectory(dir=w) as d:
        m=Path(d)/"1.99.0/23.json";m.parent.mkdir()
        r=g.read(manifest);r["sources"]["rust"]["revision"]=commit
        shutil.copyfile(official/"toolchains/manifest.schema.json",Path(d)/"manifest.schema.json")
        g.save(m,r);verify_sources(official,m,rust)
    unchanged=("src/tools/rustc-perf","src/tools/opt-dist","src/tools/opt-dist/component-pgo-v1","src/llvm-project","library","compiler/rustc_incremental/src/persist/file_format.rs","compiler/rustc_metadata/src/rmeta/mod.rs","compiler/rustc_codegen_ssa/src/back/link.rs")
    track={}
    for f in unchanged:
        track[f]=g.text(rust,"rev-parse",commit+":"+f)
        assert track[f]==g.text(rust,"rev-parse",g.BASE+":"+f)
    g.save(w/"trait-evidence/source.json",{"role":arm,"commit":commit,"tree":tree,"original":orig,"packet":proof,
        "baseline":g.BASE,"coordinator":os.environ["GITHUB_SHA"],"release":g.POLICY["official_release"],"release_files":g.POLICY["release_files"],"training":track,"command":g.POLICY["gnulinux_build_command"],"registration":g.sha(g.HERE/"registration.json")})
if __name__=="__main__": main()
