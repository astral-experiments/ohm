"""Build the released Cargo source and the input-tracking pilot with the same signed compiler."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

here=Path(__file__).resolve().parent
work=Path(os.environ["GITHUB_WORKSPACE"])
root=Path(os.environ["RUNNER_TEMP"])/"insta-input-pair"
root.mkdir()
src=work/"cargo-src"
reg=json.loads((here/"registration.json").read_bytes())
manifest=json.loads((here/"release-compiler.json").read_bytes())
pair=root/"pair"
pair.mkdir()
def git(*args):
    return subprocess.check_output(["git",*args],cwd=src,text=True).strip()
def sha(path):
    with path.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()

assert git("rev-parse","HEAD")==reg["parent"] and git("rev-parse","HEAD^{tree}")==reg["parent_tree"]
assert subprocess.check_output(["git","rev-parse","HEAD"],cwd=work/"source/rust",text=True).strip()==reg["rust"]
assert reg["release_sha256"]==manifest["tar_sha256"] and len(manifest["members"])==79
gh={"PATH":os.environ["PATH"],"HOME":os.environ["HOME"],"GH_TOKEN":os.environ.pop("OHM_SDK_READ_TOKEN")}
endpoint="repos/astral-experiments/ohm/releases/assets/707031606"
entry=json.loads(subprocess.check_output(["gh","api",endpoint],env=gh))
assert entry["digest"]=="sha256:"+reg["release_sha256"] and entry["size"]==360088078
archive=root/"sdk.tar.gz"
with archive.open("xb") as f:
    subprocess.run(["gh","api","-H","Accept: application/octet-stream",endpoint],env=gh,stdout=f,check=True)
assert sha(archive)==reg["release_sha256"]
sdk=root/"sdk"
lookup={v["source"]:(k,v) for k,v in manifest["members"].items()}
found=set()
with tarfile.open(archive,"r|gz") as tar:
    for m in tar:
        if m.name not in lookup:continue
        name,row=lookup[m.name]
        assert m.isfile() and name not in found and m.size==row["bytes"] and ".." not in Path(name).parts and not Path(name).is_absolute()
        path=sdk/name
        path.parent.mkdir(parents=True,exist_ok=True)
        with tar.extractfile(m) as f,path.open("xb") as dest: shutil.copyfileobj(f,dest)
        assert sha(path)==row["sha256"]
        path.chmod(0o755 if m.mode&0o111 else 0o644)
        found.add(name)
assert found==set(manifest["members"])
alias=root/"bootstrap/toolchains/ohm"
alias.parent.mkdir(parents=True)
alias.symlink_to(sdk)
e={k:os.environ[k] for k in ("PATH","HOME","USER","LANG","TMPDIR") if k in os.environ}
e.update(RUSTUP_HOME=str(alias.parent.parent),RUSTUP_TOOLCHAIN="ohm",CARGO_HOME=str(root/"registry"),
         CARGO_BUILD_BUILD_DIR=str(root/"compiler-build-dir"),CARGO_INCREMENTAL="false",CARGO_PROFILE_RELEASE_DEBUG="0")
for cmd,expected in (("cargo",reg["parent"]),("rustc",reg["rust"])):
    assert expected in subprocess.check_output([cmd,"+ohm","-vV"],cwd=src,env=e,text=True)
bundle=here/"compiler.bundle"
assert sha(bundle)==reg["bundle"] and git("bundle","list-heads",str(bundle)).split()==[reg["candidate"],reg["ref"]]
git("bundle","verify",str(bundle))
git("fetch","--no-tags","--no-recurse-submodules",str(bundle),reg["ref"])
assert git("rev-parse","FETCH_HEAD^")==reg["parent"] and git("rev-parse","FETCH_HEAD^{tree}")==reg["candidate_tree"]
assert git("diff","--name-only",reg["parent"],reg["candidate"]).splitlines()==["src/compiler/mod.rs"]
subprocess.run(["cargo","+ohm","-Zohm-defaults=no","fetch","--locked"],cwd=src,env=e,check=True)
cs={}
for name in ("parent","candidate"):
    git("checkout","--quiet","--detach",reg[name])
    assert git("rev-parse","HEAD")==reg[name] and git("rev-parse","HEAD^{tree}")==reg[name+"_tree"]
    build=root/(name+"-target")
    use=dict(e,CARGO_TARGET_DIR=str(build),CARGO_NET_OFFLINE="true")
    cmd=["cargo","+ohm","-Zohm-defaults=no","build","--release","--locked","--offline","-p","cargo","--bin","cargo",
         "--features","all-static,ohm-defaults","-j6"]
    subprocess.run(cmd,cwd=src,env=use,check=True)
    out=pair/name/"cargo"
    out.parent.mkdir()
    shutil.copy2(build/"release/cargo",out)
    version=subprocess.check_output([out,"-vV"],env=use,text=True)
    assert reg[name] in version
    cs[name]={"sha256":sha(out),"bytes":out.stat().st_size,"source":reg[name],"tree":reg[name+"_tree"],"version":version}
assert cs["parent"]["sha256"]!=cs["candidate"]["sha256"]
proof={"cargo":cs,"sdk_sha256":reg["release_sha256"],"bootstrap_cargo":sha(sdk/"bin/cargo"),
       "rustc":reg["rust"],"command":cmd,"qa":os.environ["GITHUB_SHA"],"run":os.environ["GITHUB_RUN_ID"]}
(pair/"build.json").write_text(json.dumps(proof,indent=2)+"\n")
