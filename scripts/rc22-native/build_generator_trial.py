"""Build the standalone Cargo fix against the enrolled compiler and bind the executable to each replay."""
import os
import subprocess
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
import materialize
import sdk

REV = "cc483e5b78b876d647e2f3f78e791936670de47a"
TREE = "23acb5e5ae4861990047845d53862158317339f2"
PARENT = "8269d772aa1ef02e5efaa331dfb40eb55d71f719"
ROLE = "candidate330"
FEATURES = {"all-static", "ohm-defaults"}

def directory():
    return Path(os.environ["RUNNER_TEMP"]) / "rc22-generator-cargo"

def verify(record, donor):
    root = directory()
    common.require((record["commit"], record["tree"], record["parent"]) == (REV, TREE, PARENT), "wrong Cargo source")
    common.require(record["driver"] == donor["rust"]["driver_sha256"] and record["rustc"] == donor["rust"]["rustc_sha256"], "wrong compiler")
    common.require(record["host"] == common.host() and record["job"] == common.job(), "candidate built on another worker")
    common.require(common.sha(root/"cargo") == record["sha256"] and common.sha(root/"reports/build.log") == record["log_sha256"], "candidate or build log changed")
    common.require("commit-hash: "+REV in record["version_verbose"] and "host: "+common.host() in record["version_verbose"], "wrong binary stamp")
    common.require(FEATURES <= set(record["features"]) and record["path"] == "roles/candidate330/cargo", "wrong Cargo artifact")
    return record

def enroll(kit, donor, receipts):
    record = verify(common.read(directory()/"reports/candidate330.json"), donor)
    dest = kit / record["path"]
    dest.parent.mkdir()
    os.link(directory()/"cargo", dest)
    common.require(common.sha(dest) == record["sha256"], "installed candidate differs")
    common.save(receipts/"candidate330.json", record)
    return {**donor, "cargos": {"pinned": donor["cargos"]["pinned"], ROLE: record}}

def build(bundle):
    root = directory()
    root.mkdir()
    reports = root/"reports"
    reports.mkdir()
    kit = root/"original-kit"
    donor = sdk.reopen(bundle, kit)
    materialize.cargo(root)
    source = root/"cargo-source"
    packed=Path(__file__).with_name("generator-candidate.pack")
    common.require(common.sha(packed) == "2f46a73c1d77b1928bcd370421ee3af4594dd8444f9a59f0cf67e637ab289bbb", "experimental source digest")
    with packed.open("rb") as stream:
        subprocess.run(["git","index-pack","--stdin"],cwd=source,stdin=stream,check=True)
    common.git(source, "checkout", "--detach", "-q", REV)
    common.require(common.git(source, "rev-parse", "HEAD^{tree}") == TREE and common.git(source, "rev-parse", "HEAD^") == PARENT, "wrong standalone tree")
    paths = set(common.git(source, "diff", "--name-only", PARENT, REV).splitlines())
    common.require(paths == {'src/compiler/mod.rs', 'src/compiler/fingerprint/mod.rs', 'src/compiler/fingerprint/worktree.rs'}, paths)
    common.require(not common.git(source,"status","--porcelain"), "dirty source")
    work = root/"build"
    work.mkdir()
    env = common.context(work, kit/"sdk")
    env.update(CFG_RELEASE="1.99.0-dev", CFG_RELEASE_CHANNEL="dev")
    common.require(common.run(["rustc","+ohm","-vV"],env=env) == donor["rust"]["version_verbose"], "different Rust")
    # The donor already authenticates the previous Cargo. Disable its defaults for building the candidate.
    bootstrap = ["cargo", "+ohm", "-Zohm-defaults=no"]
    sdk.log_run([*bootstrap,"fetch","--locked","--target",common.host()], source, reports/"fetch.log", env)
    command = [*bootstrap,"build","--release","--offline","--locked","-p","cargo","--bin","cargo","--features","all-static,ohm-defaults","-j"+("4" if common.host()==common.APPLE else "8"),"--message-format=json"]
    sdk.log_run(command, source, reports/"build.log", env)
    messages = list(sdk.rows(reports/"build.log"))
    leaf, = [m for m in messages if m["reason"] == "compiler-artifact" and m["target"]["name"] == "cargo" and m["target"]["kind"] == ["bin"]]
    binary = Path(leaf["executable"]).resolve()
    common.require(messages[-1] == {"reason":"build-finished","success":True} and not leaf["fresh"] and binary.is_relative_to(work/"target"), "incomplete Cargo build")
    shutil.copy2(binary, root/"cargo")
    version = common.run([root/"cargo","-Vv"],env=env)
    common.require("release: 1.99.0-dev" in version and not common.git(source, "status", "--porcelain", "--untracked-files=no"), "release stamp or source changed")
    record = dict(commit=REV, tree=TREE, parent=PARENT, host=common.host(), job=common.job(), path="roles/candidate330/cargo", rustc=donor["rust"]["rustc_sha256"], driver=donor["rust"]["driver_sha256"], sha256=common.sha(root/"cargo"), command=command, log_sha256=common.sha(reports/"build.log"), features=leaf["features"], version_verbose=version)
    common.save(reports/"candidate330.json",verify(record,donor))
    print("standalone Cargo", REV, record["sha256"], flush=True)

if __name__ == "__main__":
    build(Path(sys.argv[1]))
