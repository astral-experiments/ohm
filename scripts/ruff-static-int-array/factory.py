"""Build and identify the two compilers used by the integer-array experiment."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

here = Path(__file__).resolve().parent
register = json.loads((here / "registration.json").read_bytes())
root = Path(os.environ["RUNNER_TEMP"]) / "static-int-array"
src = Path(os.environ["GITHUB_WORKSPACE"]) / "source/rust"
role = os.environ["ARRAY_ARM"]
assert role in ("parent", "candidate")

def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def git(*args):
    return subprocess.check_output(["git", "-C", src, *args], text=True).strip()

def prepare():
    root.mkdir(exist_ok=True)
    assert git("rev-parse", "HEAD") == register["parent"]
    assert git("rev-parse", "HEAD^{tree}") == register["parent_tree"]
    record = root / "source.json"
    assert not record.exists()
    bundle = here / "compiler.bundle"
    assert sha(bundle) == register["bundle"]
    assert git("bundle", "list-heads", bundle).split() == [register["candidate"], register["ref"]]
    git("bundle", "verify", bundle)
    git("fetch", "--no-tags", "--no-recurse-submodules", bundle, register["ref"])
    assert git("rev-list", "--reverse", register["parent"] + "..FETCH_HEAD").splitlines() == register["compiler_commits"]
    assert git("rev-parse", register["compiler_commits"][0] + "^") == register["parent"]
    assert git("rev-parse", "FETCH_HEAD^{tree}") == register["candidate_tree"]
    assert git("diff", "--name-only", "HEAD", "FETCH_HEAD").splitlines() == register["paths"]
    if role == "candidate":
        git("checkout", "--quiet", "--no-recurse-submodules", "--detach", "FETCH_HEAD")
    assert git("rev-parse", "HEAD") == register[role]
    assert not git("status", "--porcelain", "--untracked-files=no", "--", "compiler")
    record.write_text(json.dumps({"role":role,"source":git("rev-parse","HEAD"),"tree":git("rev-parse","HEAD^{tree}"),
                                  "factory":os.environ["GITHUB_SHA"],"run":os.environ["GITHUB_RUN_ID"]},indent=2)+"\n")

def build():
    assert json.loads((root/"source.json").read_bytes())["source"] == register[role] == git("rev-parse","HEAD")
    host = "x86_64-unknown-linux-gnu"
    store = root / "output"
    cmd = [sys.executable, "-IB", "x.py", "--ci", "false", "--build-dir", str(store),
           "--set", "build.submodules=false", "--set", "build.profiler=true", "--set", "rust.debug-assertions=false",
           "--set", "rust.lto=off", "--set", "llvm.download-ci-llvm=true", "--set", "rust.download-rustc=false",
           "build", "--stage", "1", "-j6", "compiler/rustc", "library", "src/tools/rustdoc"]
    (root/"bootstrap.json").write_text(json.dumps(cmd,indent=2)+"\n")
    child={k:os.environ[k] for k in ("PATH","HOME","USER","LANG","TMPDIR") if k in os.environ}
    child["PYTHONDONTWRITEBYTECODE"]="1"
    subprocess.run(cmd,cwd=src,env=child,check=True)
    assert git("rev-parse","HEAD") == register[role]
    sdk=root/"sdk"
    shutil.copytree(store/host/"stage1",sdk,symlinks=False)
    dist=root/"ohm-1.99.0-24-x86_64-unknown-linux-gnu.tar.gz"
    assert sha(dist)==register["release_sha256"]
    with tarfile.open(dist,"r:gz") as tar:
        for name,member in register["release_members"].items():
            src_member=tar.getmember(member["source"])
            assert src_member.isfile() and src_member.size==member["bytes"]
            dest=sdk/name
            dest.parent.mkdir(parents=True,exist_ok=True)
            with tar.extractfile(src_member) as f,dest.open("wb") as out:
                shutil.copyfileobj(f,out)
            dest.chmod(0o755)
            assert sha(dest)==member["sha256"]
    alias=root/"rustup/toolchains/ohm"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(sdk,target_is_directory=True)
    versions={}
    e=dict(child,RUSTUP_HOME=str(alias.parent.parent))
    for tool in ("rustc","cargo"):
        versions[tool]=subprocess.check_output([tool,"+ohm","-vV"],env=e,text=True)
    assert register[role] in versions["rustc"] and register["cargo"] in versions["cargo"]
    driver,=(sdk/"lib").glob("librustc_driver-*.so")
    (root/"sdk.json").write_text(json.dumps({"role":role,"versions":versions,"driver":sha(driver),
            "rustc":sha(sdk/"bin/rustc"),"release_cargo":sha(sdk/"bin/cargo")},indent=2)+"\n")
    subprocess.run([sys.executable,"-IB",here/"probe.py",root/"probes",role],env=e,check=True)
    subprocess.run(["tar","--zstd","-cf",str(root/"sdk.tar.zst"),"-C",str(sdk),"bin","lib"],check=True)
    (root/"sdk-sha256").write_text(sha(root/"sdk.tar.zst")+"\n")
if __name__=="__main__":
    {"source":prepare,"build":build}[sys.argv[1]]()
