"""Run the shipped Linux compiler recipe on authenticated source trees and retain a QA SDK."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess as sp
import sys
import tarfile

kit=Path(__file__).resolve().parent
spec=json.loads((kit/"registration.json").read_bytes())
workspace=Path(os.environ["GITHUB_WORKSPACE"])
shipping=workspace/"shipping"
src=workspace/"source/rust"
root=Path(os.environ["RUNNER_TEMP"])/"release-compiler-price"
manifest=shipping/"toolchains/1.99.0/24.json"
host="x86_64-unknown-linux-gnu"
role=os.environ["RELEASE_COMPILER_ARM"]
assert role in spec["enabled_roles"]
proof=root/"proof"
def sha(p):
    with p.open("rb")as f:return hashlib.file_digest(f,"sha256").hexdigest()
def git(path,*args):
    return sp.check_output(["git","-C",path,*args],text=True).strip()
def put(name,value):
    (proof/name).write_text(json.dumps(value,indent=2,sort_keys=True)+"\n")
def source():
    proof.mkdir(parents=True)
    assert git(shipping,"rev-parse","HEAD")==spec["release"]
    assert sha(manifest)==spec["manifest"] and sha(shipping/"release/bootstrap.toml")==spec["bootstrap_config"]
    assert sha(shipping/"scripts/build-optimized-dist.sh")==spec["build_script"]
    pins={k:v["revision"] for k,v in json.loads(manifest.read_bytes())["sources"].items()}
    nested={k:src/"src/tools"/k for k in ("cargo","clippy","rustfmt")}
    assert {k:git(v,"rev-parse","HEAD")for k,v in nested.items()}=={k:pins[k] for k in nested}
    assert git(src,"rev-parse","HEAD")==pins["rust"]==spec["parent"] and git(src,"rev-parse","HEAD^{tree}")==spec["parent_tree"]
    args=["bash",shipping/"scripts/verify-release-sources.sh",manifest,src,*nested.values()]
    with (proof/"shipped-source-verifier.log").open("wb")as out:sp.run(args,stdout=out,stderr=sp.STDOUT,check=True)
    if role=="candidate":
        bundle=kit/"candidate.bundle"
        assert sha(bundle)==spec["bundle"] and git(src,"bundle","list-heads",bundle).split()==[spec["candidate"],spec["ref"]]
        git(src,"bundle","verify",bundle)
        git(src,"fetch","--no-tags","--no-recurse-submodules",bundle,spec["ref"])
        assert git(src,"rev-parse","FETCH_HEAD^{tree}")==spec["candidate_tree"]
        assert git(src,"rev-list","--reverse",spec["parent"]+"..FETCH_HEAD").splitlines()==spec["commits"]
        assert git(src,"rev-parse",spec["commits"][0]+"^")==spec["parent"]
        assert git(src,"diff","--name-only",spec["parent"],"FETCH_HEAD").splitlines()==spec["paths"]
        git(src,"checkout","--quiet","--no-recurse-submodules","--detach","FETCH_HEAD")
    assert not git(src,"diff","--name-only","HEAD","--","compiler","library","src/bootstrap")
    assert git(src,"rev-parse","HEAD")==spec[role] and git(src,"rev-parse","HEAD^{tree}")==spec[role+"_tree"]
    assert all(git(v,"rev-parse","HEAD")==pins[k] for k,v in nested.items())
    put("source.json",dict(role=role,source=spec[role],tree=spec[role+"_tree"],factory=os.environ["GITHUB_SHA"],
        run=os.environ["GITHUB_RUN_ID"],published_source=pins,verified_release_coordinator=spec["release"]))
def collect():
    binding=json.loads((proof/"source.json").read_bytes())
    assert binding["source"]==spec[role]==git(src,"rev-parse","HEAD")
    assert (src/"src/version").read_text().strip()=="1.99.0"
    build=src/"build"
    config=build/"ohm-release-bootstrap.toml"
    assert 'lto = "thin"' in config.read_text() and 'codegen-units = 1' in config.read_text()
    shutil.copy2(config,proof/"bootstrap.toml")
    profiles={n:build/"opt-artifacts"/(n+"-pgo.profdata") for n in ("rustc","rustdoc","clippy","rustfmt")}
    assert all(f.is_file() and not f.is_symlink() and f.stat().st_size>0 for f in profiles.values())
    put("training.json",dict(script=spec["build_script"],config=sha(config),profiles={n:[sha(f),f.stat().st_size]for n,f in profiles.items()}))
    name="rust-1.99.0-dev-"+host
    dist=build/"dist"/(name+".tar.gz")
    unpack=root/"unpacked"
    sdk=root/"sdk"
    with tarfile.open(dist,"r:gz")as t:t.extractall(unpack,filter="data")
    sp.run([unpack/name/"install.sh","--prefix="+str(sdk),"--disable-ldconfig","--components=rustc,rust-std-"+host+",cargo"],check=True)
    driver,=(sdk/"lib").glob("librustc_driver-*.so")
    sections=sp.check_output(["readelf","-SW",driver],text=True)
    assert ".note.bolt_info" in sections
    (proof/"driver-sections.txt").write_text(sections)
    own_cargo=sha(sdk/"bin/cargo")
    signed=root/"ohm-1.99.0-24-x86_64-unknown-linux-gnu.tar.gz"
    assert sha(signed)==spec["signed"]
    with tarfile.open(signed,"r:gz")as t:
        for key,r in spec["members"].items():
            dest=sdk/key;fn=t.getmember(r["source"])
            assert fn.isfile() and fn.size==r["bytes"]
            if key!="bin/cargo":assert sha(dest)==r["sha256"]
            with t.extractfile(fn)as f,dest.open("wb")as out:shutil.copyfileobj(f,out)
            dest.chmod(0o755);assert sha(dest)==r["sha256"]
    alias=root/"rustup/toolchains/ohm";alias.parent.mkdir(parents=True);alias.symlink_to(sdk,target_is_directory=True)
    e={k:os.environ[k]for k in ("PATH","HOME","USER","LANG","TZ")if k in os.environ};e["RUSTUP_HOME"]=str(alias.parent.parent)
    versions={n:sp.check_output([n,"+ohm","-vV"],env=e,text=True)for n in ("cargo","rustc")}
    assert binding["source"] in versions["rustc"] and binding["published_source"]["cargo"] in versions["cargo"]
    put("sdk.json",dict(role=role,versions=versions,driver=sha(driver),rustc=sha(sdk/"bin/rustc"),release_cargo=sha(sdk/"bin/cargo"),
        independently_trained_cargo=own_cargo,source_distribution=sha(dist),wild=sha(sdk/"lib/rustlib"/host/"bin/wild-ld/ld.bfd")))
    fixture=root/"native";fixture.mkdir()
    text='#[derive(Clone,Debug,PartialEq)] struct Row(u32); fn entry()->Row { Row(42) } fn main(){ println!("{:?}",entry().clone()); }\n'
    dest=fixture/"test.rs";exe=fixture/"example";dest.write_text(text)
    call=["rustc","+ohm","--edition=2024",dest,"-o",exe]
    sp.run(call,env=e,check=True)
    assert sp.check_output([exe],env=e)==b"Row(42)\n"
    dest.write_text(text.replace("Row(42)",'Row("bad")'))
    bad=[sp.run([*call,"--error-format=json"],capture_output=True,env=e)for _ in range(2)]
    assert all(r.returncode!=0 and b"E0308" in r.stderr for r in bad) and bad[0].stderr==bad[1].stderr
    put("native.json",dict(baseline="Row(42)",rejected_twice="E0308",diagnostic=hashlib.sha256(bad[0].stderr).hexdigest()))
    sp.run(["tar","--zstd","-cf",root/"sdk.tar.zst","-C",sdk,"bin","lib"],check=True)
    (proof/"sdk-sha256").write_text(sha(root/"sdk.tar.zst")+"\n")
if __name__=="__main__":{"source":source,"collect":collect}[sys.argv[1]]()
