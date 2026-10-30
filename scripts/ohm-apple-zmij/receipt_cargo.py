"""Reconstruct and build the unmodified Cargo #293 source on the native QA runner."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study import CARGO_SOURCE, TRIPLE, check_host, env_for, load, need, physical, run, save, sha

CANDIDATE = "735e1528ed741015c57676dccf05dbdc0ff7bed1"
PARENT = "98d431a99779ccfbcfe42dfa74dd541de3a92d05"
TREE = "9cb7035b7adc52ecac48495666b95ba857ed3cdd"
PACK = "775494565d10143c9f34679ad21d90020ed9c82518f774fde923f4d5ef90ea4b"
FEATURES = "ohm-defaults,all-static"


def materialize(src):
    pack = Path(__file__).with_name("cargo293") / "source.pack"
    need(pack.stat().st_size == 5307709 and sha(pack) == PACK, "source pack differs")
    src.mkdir()
    def git(*args, data=None):
        return run(["git", "-c", "core.autocrlf=false", *args], cwd=src, data=data)
    git("init", "--quiet", "--template=", "-b", "exact-293")
    git("index-pack", "--stdin", data=pack.read_bytes())
    (src / ".git/shallow").write_text(CANDIDATE + "\n")
    git("update-ref", "refs/heads/exact-293", CANDIDATE)
    git("checkout", "-q", "-f", "exact-293")
    commit = git("cat-file", "commit", CANDIDATE)
    need(commit.splitlines()[:2] == [b"tree " + TREE.encode(), b"parent " + PARENT.encode()], "wrong native source")
    git("fsck", "--full", "--strict", "--no-progress")
    need(git("write-tree").decode().strip() == TREE and git("status", "--porcelain=v1") == b"", "dirty source")
    entries = git("ls-tree", "-r", "--full-tree", "HEAD").splitlines()
    need(len(entries) == 3114 and not any(x.startswith(b"160000 ") for x in entries), "incomplete source material")
    return {"commit": CANDIDATE, "parent": PARENT, "tree": TREE, "entries": len(entries), "source_pack": PACK,
            "lock": sha(src / "Cargo.lock"), "product_sources": {str(p.relative_to(src)):sha(p)
            for p in sorted((src / "src/compiler").glob("native_link*/**/*.rs"))}}


def build(root, aware=False):
    label = "cargo-aware" if aware else "cargo293"
    receipts = root / "receipts" / label
    check_host(root, 12)
    device = run(["df", "-P", str(root)]).decode().splitlines()[-1].split()[0]
    info = plistlib.loads(run(["diskutil", "info", "-plist", device]))
    filesystem = {key: info.get(key) for key in ("FilesystemType", "FilesystemName", "DeviceNode", "MountPoint", "Internal")}
    need(str(filesystem["FilesystemType"]).lower() == "apfs" and
         os.stat(filesystem["MountPoint"]).st_dev == root.stat().st_dev, "provider qualification requires APFS")
    save(receipts / "filesystem.json", filesystem)
    src = root / ("aware-cargo-source" if aware else "receipt-cargo-source")
    if aware:
        directory = Path(__file__).resolve().parents[1] / "ohm-gnu-syscall/release-reader"
        sys.path.insert(0, str(directory))
        from build import materialize as release_tree, REGISTERED
        release_tree(src)
        registered = REGISTERED["integrated"]
        selected = registered["commit"]
        source = {"commit": selected, "tree": registered["tree"], "parents": registered["parents"],
                  "entries": len(run(["git","ls-tree","-r","HEAD"],cwd=src).splitlines()),
                  "lock": sha(src/"Cargo.lock"), "transport": {p.name: sha(p) for p in directory.iterdir() if p.is_file()}}
        need(source["entries"] == 3114, "incomplete release Cargo tree")
    else:
        source = materialize(src)
        selected = CANDIDATE
    save(receipts / "source.json", source)
    work = root / ("aware-cargo-build" if aware else "receipt-cargo-build")
    work.mkdir()
    env = env_for(work, root / "signed")
    compiler = run(["rustc", "+ohm", "-vV"], env=env).decode()
    builder = run(["cargo", "+ohm", "-Vv"], env=env).decode()
    need(CARGO_SOURCE in builder and TRIPLE in compiler, "wrong builder")
    base = ["cargo", "+ohm", "-Zohm-defaults=no"]
    online = dict(env)
    online.pop("CARGO_NET_OFFLINE")
    fetch = [*base, "fetch", "--locked", "--target", TRIPLE]
    cmd = [*base, "build", "--release", "--locked", "--offline", "--bin", "cargo", "--package", "cargo",
           "--features", FEATURES, "-j4", "--message-format=json"]
    for name, argv, settings in (("fetch", fetch, online), ("build", cmd, env)):
        with (receipts / (name + ".stdout")).open("xb") as out, (receipts / (name + ".stderr")).open("xb") as err:
            p = subprocess.run(argv, cwd=src, env=settings, stdout=out, stderr=err, timeout=3600)
        save(receipts / (name + ".json"), {"argv":argv, "status":p.returncode})
        if p.returncode:
            print((receipts / (name + ".stderr")).read_text(errors="replace")[-2600:], flush=True)
        need(p.returncode == 0, "Cargo source " + name + " failed")
    rows = [json.loads(x) for x in (receipts / "build.stdout").read_bytes().splitlines()]
    need(rows[-1] == {"reason":"build-finished", "success":True}, "unsuccessful native Cargo construction")
    leaf, = [x for x in rows if x["reason"] == "compiler-artifact" and x["target"]["name"] == "cargo"
             and x["target"]["kind"] == ["bin"]]
    need(not leaf["fresh"] and {"ohm-defaults","all-static"} <= set(leaf["features"]), "missing release features")
    output = Path(leaf["executable"])
    dest = root / ("cargo-aware" if aware else "cargo-293")
    shutil.copyfile(output, dest);dest.chmod(0o555)
    version = run([str(dest), "-Vv"]).decode()
    need(f"commit-hash: {selected}" in version and f"host: {TRIPLE}" in version and sha(output)==sha(dest), "wrong native Cargo")
    deps = run(["otool","-L",str(dest)]).decode()
    need(str(work) not in deps, "compiler depends on transient build inputs")
    save(receipts / "product.json", {"source":source, "binary":physical(dest), "version":version, "builder":builder,
        "rustc":compiler, "builder_cargo":physical(root/"signed/bin/cargo"), "builder_rustc":physical(root/"signed/bin/rustc"),
        "features":leaf["features"], "linkage":deps, "lock":sha(src/"Cargo.lock"), "typed_outputs":len(rows),
        "build_stdout":sha(receipts/"build.stdout"), "build_stderr":sha(receipts/"build.stderr")})


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=("source","build","aware"));parser.add_argument("path",type=Path)
    args=parser.parse_args()
    if args.action=="source":print(json.dumps(materialize(args.path.resolve()),sort_keys=True))
    else:build(args.path.resolve(), aware=args.action=="aware")
