"""Enroll the actual Git child, then reconstruct, bootstrap and export its GNU SDK."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from native import CARGO_SHA, HOST, PARENT, WILD, need, save, sha
PREVIOUS = "bbd6c9b7da30dee3f8b3ed8121116873707b7a58"
BASE = "625207d26ce4449c9c95d871c88cfb50e904c09f"
SEED = "7bc72b798b019a9ec0de6eeea3bc22b783917b27"
TEST = "tests/run-make/rdr-public-hash-native-exports"
REGRESSIONS = [TEST, *["tests/run-make/" + n for n in ("rdr-public-hash-body-changes",
    "rdr-public-hash-private-native-derive", "rdr-public-hash-private-native-impls", "rdr-public-hash-staticlib")]]
FLAGS = ["--ci", "false", "--set", "build.submodules=false", "--set", "rust.channel=dev", "--set",
         "rust.omit-git-hash=false", "--set", "rust.debug-assertions=false", "--set", "rust.lto=off",
         "--set", "llvm.download-ci-llvm=true"]


def git(repo, *args):
    return subprocess.check_output(["git", "-C", repo, *args]).decode().strip()


def catalog(repo, candidate):
    need(git(repo, "rev-parse", candidate + "^") == PREVIOUS and git(repo,"rev-parse",PREVIOUS+"^")==PARENT,
         "candidate must be the reviewed follow-up to the preserved original")
    need(git(repo, "rev-parse", PARENT + "^{tree}") == "277af1f4d727b2e634696548e3a938e9d518b86f", "different parent")
    for key in ("compiler", "library", "tests", "src/bootstrap", "library/backtrace"):
        need(git(repo, "rev-parse", PARENT + ":" + key) == git(repo, "rev-parse", BASE + ":" + key), key)
    files = {}
    for name in git(repo, "diff", "--name-only", PARENT, candidate).splitlines():
        allowed = (name.startswith("compiler/rustc_metadata/") or name in ("compiler/rustc_incremental/src/persist/file_format.rs",
                  "compiler/rustc_middle/src/queries.rs") or name.startswith(TEST + "/"))
        need(allowed, ("outside qualification", name))
        data = subprocess.check_output(["git", "-C", repo, "show", candidate + ":" + name])
        files[name] = {"blob": git(repo, "rev-parse", candidate + ":" + name),
                       "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    need(TEST + "/rmake.rs" in files, "named regression missing")
    return {"base": BASE, "parent": PARENT, "previous": PREVIOUS, "candidate": candidate, "files": files,
            "trees": {s:git(repo, "rev-parse", candidate + (":" + s if s else "^{tree}"))
                      for s in ("", "compiler", "library", "tests", "src/bootstrap", "src/tools/cargo")}}


def pack(repo):
    c = git(repo, "rev-parse", "HEAD")
    info = catalog(repo, c)
    target = HERE / "source.pack"
    with target.open("xb") as stream:
        subprocess.run(["git", "-C", repo, "pack-objects", "--revs", "--stdout", "--no-reuse-delta"],
                       input=(c + "\n^" + BASE + "\n").encode(), stdout=stream, check=True)
    info["pack_sha256"] = sha(target)
    save(HERE / "source.json", info)


def seed():
    s = Path(os.environ["GITHUB_WORKSPACE"]) / "transport"
    need(git(s, "rev-parse", "HEAD") == SEED, "incorrect carrier")
    sys.path.insert(0, str(s / "scripts/rc22-native"))


def prepare(root):
    seed()
    import materialize
    materialize.source(root)
    repo = root / "rust"
    expected = json.loads((HERE / "source.json").read_bytes())
    src = HERE / "source.pack"
    need(sha(src) == expected.pop("pack_sha256"), "wrong Git source pack")
    with src.open("rb") as stream:
        subprocess.run(["git", "-C", repo, "index-pack", "--strict", "--stdin"], stdin=stream, check=True)
    commit = expected["candidate"]
    need(catalog(repo, commit) == expected, "source tree or named regression changed")
    subprocess.run(["git", "-C", repo, "checkout", "--detach", "-q", commit], check=True)
    need(not git(repo, "status", "--porcelain", "--ignore-submodules=none"), "dirty")
    need(git(repo / "library/backtrace", "rev-parse", "HEAD") == "d902726a1dcdc1e1c66f73d1162181b5423c645b", "wrong native backtrace")
    save(root / "reports/qualified-source.json", expected)


def build(root):
    seed()
    import sdk
    repo = root / "rust"
    spec = json.loads((HERE / "source.json").read_bytes())
    need(git(repo, "rev-parse", "HEAD") == spec["candidate"] and catalog(repo,spec["candidate"])["trees"] == spec["trees"], "dirty source identity")
    need(shutil.disk_usage(root).free > 32 << 30, "insufficient disk at compiler start")
    cmd = ["./x", *FLAGS, "build", "--stage", "1", "-j8", "--host", HOST, "--target", HOST,
           "compiler/rustc", "library", "src/tools/rustdoc"]
    sdk.log_run(cmd, repo, root / "reports/bootstrap.log")
    dest = root / "candidate"
    sdk.freeze(repo / "build" / HOST / "stage1", dest, repo, HOST)
    for path, wanted in ((Path("bin/cargo"), CARGO_SHA),
                         (Path("lib/rustlib") / HOST / "bin/wild-ld/ld.bfd", WILD)):
        product = root / "baseline" / path
        need(sha(product) == wanted, ("different common input", path))
        (dest / path).parent.mkdir(parents=True, exist_ok=True)
        need(not (dest / path).exists(), ("ambiguous stage product", path))
        shutil.copy2(product, dest / path)
    versions = {}
    for binary,rev in (("rustc",spec["candidate"]),("rustdoc",spec["candidate"]),("cargo","4591cf45cc10abb19d2456c40b99606e08167f29")):
        stamp = subprocess.check_output([dest / "bin" / binary, "-vV"], text=True)
        need("commit-hash: " + rev + "\n" in stamp and "host: " + HOST + "\n" in stamp, (binary, stamp))
        versions[binary] = stamp
    members = {str(p.relative_to(dest)):[sha(p), p.stat().st_size, stat.S_IMODE(p.stat().st_mode)]
               for p in sorted(dest.rglob("*")) if p.is_file()}
    box = root / "export"
    box.mkdir()
    save(box / "members.json", members)
    with subprocess.Popen(["zstd","-T3","-3","-q","-o",box / "sdk.tar.zst"], stdin=subprocess.PIPE) as z:
        with tarfile.open(fileobj=z.stdin, mode="w|") as bundle:
            for name in members:
                bundle.add(dest/name, arcname=name, recursive=False)
        z.stdin.close()
        need(z.wait() == 0, "SDK compression failed")
    driver, = [p for p in members if p.startswith("lib/librustc_driver-")]
    receipt = {"compiler": spec, "driver": members[driver], "versions": versions, "bootstrap": cmd,
               "bootstrap_log":sha(root/"reports/bootstrap.log"), "sdk": sha(box/"sdk.tar.zst"),
               "members":sha(box/"members.json"), "files":len(members),
               "qa":{n:os.environ[n] for n in ("GITHUB_RUN_ID","GITHUB_RUN_ATTEMPT","GITHUB_SHA","GITHUB_JOB")}}
    save(box/"receipt.json", receipt)
    save(root/"reports/built-sdk.json", receipt)


INCREMENTAL_TESTS = ["tests/incremental/rdr/"+n+"/main.rs" for n in
                     ("trait_impl_unreachable_local_trait","trait_impl_reachable_local_trait")]


def tests(root, incremental=False):
    seed()
    import sdk
    targets = INCREMENTAL_TESTS if incremental else REGRESSIONS
    label = "incremental" if incremental else "run-make"
    cmd = ["./x", *FLAGS, "--set", "rust.verbose-tests=true", "test", "--stage", "1",
           "-j8", "--host", HOST, "--target", HOST, *targets]
    log = root / "reports" / (label+".log")
    sdk.log_run(cmd, root / "rust", log)
    rows = log.read_text(errors="replace").splitlines()
    for test in targets:
        need(any(test in l and " ok" in l for l in rows), ("named successful run-make did not execute", test))
    save(root/"reports"/(label+".json"), {"argv":cmd, "log":sha(log), "lines":[l for l in rows if any(t in l for t in targets)]})


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("operation", choices=("pack","prepare","build","tests","incremental"))
    p.add_argument("root", type=Path)
    a = p.parse_args()
    {"pack":pack,"prepare":prepare,"build":build,"tests":tests,"incremental":lambda root:tests(root,True)}[a.operation](a.root.resolve())
