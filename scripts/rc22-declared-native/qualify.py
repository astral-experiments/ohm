"""Compare real rustc invocations for the same unchanged ty check on Linux."""
import gzip
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time

root = Path(os.environ["RUNNER_TEMP"]) / "rc22-qualify-native-link"
root.mkdir()
reports = root / "reports"
reports.mkdir()
def sha(p):
    with Path(p).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()
def run(argv, cwd=None, env=None):
    return subprocess.check_output(argv, cwd=cwd, env=env, text=True).strip()
def save(name, value):
    (reports / name).write_text(json.dumps(value, indent=2)+"\n")
base = "b499ff7f4c28c2d889ca0ed9037dfbec6ca8fa9f"
new = "ed0ae15d22da9a0af9afb3d0fdeb4ceb8a71b770"
cargo_src = Path("cargo-source").resolve()

seed = Path("cargo-seed/scripts").resolve()
spec = importlib.util.spec_from_file_location("cargo_source_seed", seed/"cargo-diagnostic-fix/materialize.py")
materialize = importlib.util.module_from_spec(spec)
spec.loader.exec_module(materialize)
origin = materialize.tree(cargo_src,seed/"ohm-apple-zmij/cargo293/source.pack")
assert origin["mode_path_sha256_inventory"] == "da5d8cde02be6fcd82b87b490b937224dcd46f8e72841343d9fe00ce16d253d1"
overlay=Path("intake/scripts/rc22-native/source/cargo.pack")
fresh=Path("qualification/scripts/rc22-cargo-ty-stack.pack")
overlay_manifest=json.loads(overlay.with_name("cargo.json").read_bytes())
assert origin["commit"]==overlay_manifest["base"] and sha(overlay)==overlay_manifest["sha256"]
assert sha(fresh)=="bb8b016abe957304312fca60a098d896e99cd65f49a69a9fba9ba854f20f079f"
fix=Path("qualification/scripts/rc22-declared-native/fix.pack").resolve()
assert sha(fix)=="e19fc4bf4105f295fa037c52a249bc4e047d5593e239081539879ac1c3ee94db"
for pack in [overlay,fresh,fix]:
    with pack.open("rb") as f:
        subprocess.run(["git","index-pack","--strict","--stdin"],cwd=cargo_src,stdin=f,check=True)
assert run(["git","rev-parse",base+"^{tree}"],cargo_src)=="a2c9a62722e1ef849cb68874e79617c92d165a8b"
assert run(["git","rev-parse",new+"^{tree}"],cargo_src)=="b4981dc120409cf8eec4321e355071f8abd17a64"
assert run(["git","rev-parse",new+"^"],cargo_src)==base
save("source.json",dict(seed=origin["commit"],stock_overlay=sha(overlay),integration_overlay=sha(fresh),base=base,patch=new))
sdk = root / "sdk"
archive, = Path("release").resolve().glob("*.tar.gz")
assert sha(archive) == "0b424df45b3bb9ccea5d1eda44f2481cb17a44f31ec6290e82d3db073489fe8a"
with tarfile.open(archive) as t:
    t.extractall(root/"extract", filter="data")
install, = (root / "extract").glob("*/install.sh")
with (reports / "sdk-install.log").open("xb") as f:
    subprocess.run(["sh", install, "--prefix="+str(sdk), "--disable-ldconfig"], stdout=f, stderr=subprocess.STDOUT, check=True)
cargo = sdk / "bin/cargo"
rustc = sdk / "bin/rustc"
version = run([rustc,"-vV"])
assert "commit-hash: 1bc7b35699479d5899a2935d79392b7bdaf7497d" in version and "host: x86_64-unknown-linux-gnu" in version
env = {k:v for k,v in os.environ.items() if not k.startswith(("CARGO_", "OHM_", "RUST", "LLVM_"))}
env.update(PATH=str(sdk/"bin")+os.pathsep+env["PATH"], CARGO_HOME=str(root/"registry"), RUSTC=str(rustc), RUSTDOC=str(sdk/"bin/rustdoc"))
build_settings = dict(env, CARGO_PROFILE_DEV_DEBUG="0", CARGO_INCREMENTAL="0", CFG_RELEASE="1.99.0-dev", CFG_RELEASE_CHANNEL="dev")
scripts=Path("qualification/scripts/rc22-declared-native").resolve()
subprocess.run(["git","checkout","--detach",new],cwd=cargo_src,check=True)
build=root/"bootstrap"
build_env=dict(build_settings,CARGO_TARGET_DIR=str(build))
argv=[str(cargo),"-Zohm-defaults=no","build","--locked","-p","cargo","--bin","cargo","--features","all-static,ohm-defaults","-j8"]
with (reports/"cargo-build.log").open("wb") as log: subprocess.run(argv,cwd=cargo_src,env=build_env,stdout=log,stderr=subprocess.STDOUT,check=True)
binary=build/"debug/cargo"
version=run([binary,"-vV"],env=env)
assert "commit-hash: "+new in version
save("cargo-provenance.json",dict(commit=new,tree=run(["git","rev-parse","HEAD^{tree}"],cargo_src),sha256=sha(binary),version=version,command=argv))
def exercise(cmd,cwd=root):
    p=subprocess.run(cmd,cwd=cwd,env=os.environ)
    return p.returncode
kit=root/"physical-kit"
(kit/"bin").mkdir(parents=True)
for item in sdk.iterdir():
    if item.name != "bin":(kit/item.name).symlink_to(item,target_is_directory=item.is_dir())
for item in (sdk/"bin").iterdir():(kit/"bin"/item.name).symlink_to(binary if item.name=="cargo" else item)
mode="default"
trial=root/mode
status=exercise(["python3","-IB",scripts/"focused.py",trial,kit,mode])
if (trial/"results.json").is_file():shutil.copy2(trial/"results.json",reports/(mode+".json"))
diag=reports/"default-logs";diag.mkdir()
for item in list(trial.glob("*.log")) + list(trial.glob("*.strace.*")):
    shutil.copy2(item,diag/item.name)
for i,item in enumerate(trial.rglob("declared-native/inputs.json")):shutil.copy2(item,diag/f"reported-inputs-{i}.json")
save("checks.json",dict(default=status))
assert status==0,status
