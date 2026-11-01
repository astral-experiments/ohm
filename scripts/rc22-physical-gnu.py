"""Compare real rustc invocations for the same unchanged ty check on Linux."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time

root = Path(os.environ["RUNNER_TEMP"]) / "rc22-ty-native-scripts"
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
new = "c92c1c066a3a75a12da46c0b19c16e7a79929688"
ruff_pin = "93526150df078af7dd8fc4226cdcc469539d2001"
cargo_src = Path("cargo-source").resolve()
ruff = Path("ruff").resolve()
assert run(["git", "rev-parse", "HEAD"], ruff) == ruff_pin
assert run(["git", "rev-parse", "HEAD"], cargo_src) == new and run(["git", "rev-parse", "HEAD^"], cargo_src) == base
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
build_env = dict(env, CARGO_TARGET_DIR=str(root/"bootstrap"), CARGO_PROFILE_DEV_DEBUG="0", CARGO_INCREMENTAL="0", CFG_RELEASE="1.99.0-dev", CFG_RELEASE_CHANNEL="dev")
provenance = dict(ruff=ruff_pin, rustc=version, rustc_sha256=sha(rustc), sdk_sha256=sha(archive), readers={})
readers = {}
for role, ref in [("base",base),("patch",new)]:
    subprocess.run(["git","switch","--detach",ref], cwd=cargo_src, check=True)
    assert not run(["git","status","--porcelain"],cargo_src)
    args=[str(cargo),"-Zohm-defaults=no","build","--locked","-p","cargo","--bin","cargo","--features","all-static,ohm-defaults","-j8"]
    with (reports / (role+"-build.log")).open("wb") as log:
        subprocess.run(args,cwd=cargo_src,env=build_env,stdout=log,stderr=subprocess.STDOUT,check=True)
    binary=root/role/"cargo"
    binary.parent.mkdir()
    shutil.copy2(root/"bootstrap/debug/cargo",binary)
    stamp=run([binary,"-Vv"],env=env)
    assert "commit-hash: "+ref in stamp,(role,stamp)
    readers[role]=binary
    provenance["readers"][role]=dict(ref=ref,sha256=sha(binary),version=stamp,command=args)
    save("binaries.json",provenance)
source=ruff/"crates/ty_project/src/lib.rs"
original=source.read_bytes()
warning=b'\n#[deprecated(note = "OHM_QA_PRESERVED_WARNING")]\nconst OHM_QA_OLD_CONST: u8 = 17;\n#[warn(deprecated)]\nconst _: u8 = OHM_QA_OLD_CONST;\n'
lock=sha(ruff/"Cargo.lock")
work=root/"work"
args=["check","-p","ty_project","--tests","--locked","--offline","-j4","-vv","--message-format=json"]
records={}
try:
    for role,cargo in readers.items():
        work.mkdir()
        env_run=dict(env,CARGO_TARGET_DIR=str(work/"target"),CARGO_BUILD_BUILD_DIR=str(work/"build"))
        subprocess.run([cargo,"fetch","--locked","--target","x86_64-unknown-linux-gnu"],cwd=ruff,env=env_run,check=True)
        rows=[]
        for phase in ("clean","edit","repeat1","repeat2"):
            if phase=="edit": source.write_bytes(original+warning)
            start=time.monotonic()
            result=subprocess.run([cargo,*args],cwd=ruff,env=env_run,capture_output=True)
            seconds=time.monotonic()-start
            for channel,data in [("stdout",result.stdout),("stderr",result.stderr)]:
                (reports/f"{role}-{phase}.{channel}.gz").write_bytes(gzip.compress(data,mtime=0))
            result.check_returncode()
            events=[json.loads(l) for l in result.stdout.splitlines() if l.startswith(b"{")]
            assert events[-1]=={"reason":"build-finished","success":True}
            targets=[m for m in events if m['reason']=='compiler-artifact']
            warnings=[m["message"]["message"] for m in events if m['reason']=='compiler-message' and 'OHM_QA_PRESERVED_WARNING' in m['message']['message']]
            assert bool(warnings)==(phase!="clean") and len(targets)>250
            invocations=[]
            for l in result.stderr.decode(errors="replace").splitlines():
                if "Running " in l and (match:=re.search(r"--crate-name ([^ ]+)",l)):
                    invocations.append(dict(crate=match[1],link_only="link-only" in l))
            rows.append(dict(phase=phase,source=sha(source),lock=sha(ruff/"Cargo.lock"),warnings=warnings,units=len(targets),dirty=sorted(m["target"]["name"] for m in targets if not m["fresh"]),rustc=invocations,elapsed_seconds=seconds))
            save(role+".json",rows)
        records[role]=rows
        source.write_bytes(original)
        work.rename(root/(role+"-outputs"))
    for b,p in zip(records["base"],records["patch"],strict=True):
        assert all(b[k]==p[k] for k in ("phase","source","lock","warnings","units"))
        assert b['lock']==lock
    assert all(r['rustc'] for r in records["base"][2:]),"baseline did not reproduce a warm compiler invocation"
    save("complete.json",records)
finally:
    source.write_bytes(original)
