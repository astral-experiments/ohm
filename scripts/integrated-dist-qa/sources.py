"""Reopen the four release Git trees without credentials for private source repositories."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
RUST = "1bc7b35699479d5899a2935d79392b7bdaf7497d"
PARENT = "00526133a6352eb88eca70382000e6221253235c"
CARGO = "4591cf45cc10abb19d2456c40b99606e08167f29"
TOOLS = {
    "clippy": ("0d76dc1f4fe7ffb86ee5e1a8a9cc4d6bef1d1bf6", "597138f8e9a24972dd23acd15a8eee063c3a39f9"),
    "rustfmt": ("3c9620c92b01e6c393324729c4861823cc3676e2", "48c3ccd52f999a69778e9af7930b1d0408c7213c"),
}
RUST_TREE = "bbfe1faca29784b74e01830873eae7d8f27b52f0"
CARGO_TREE = "a2c9a62722e1ef849cb68874e79617c92d165a8b"
REVIEWED = "64e2c3213fd69f28dfbcce3c18495507156f81fe"


def need(condition, message):
    if not condition:
        raise ValueError(message)


def git(root, *args):
    return subprocess.check_output(["git", "-C", root, *args]).decode().strip()


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def unpack(repo, name):
    data = json.loads((HERE / "packs.json").read_bytes())[name]
    file = HERE / (name + ".pack")
    need(file.stat().st_size == data[0] and sha(file) == data[1], f"{name} transport changed")
    with file.open("rb") as stream:
        subprocess.run(["git", "-C", repo, "index-pack", "--strict", "--stdin"], stdin=stream, check=True)


def install_tool(root, name):
    revision, tree = TOOLS[name]
    root.mkdir()
    git(root, "init", "--quiet", "--template=")
    (root / ".git/shallow").write_text(revision + "\n")
    unpack(root, name)
    need(git(root, "rev-parse", revision + "^{tree}") == tree, f"wrong full {name} source tree")
    git(root, "checkout", "--quiet", "--detach", revision)
    git(root, "fsck", "--strict", "--no-dangling", "--no-reflogs")
    need(not git(root, "status", "--porcelain"), f"dirty {name}")


def check_rust(repo):
    need(git(repo, "rev-parse", RUST + "^", RUST + "^{tree}").splitlines() == [PARENT, RUST_TREE], "wrong integrated Rust source")
    paths = git(repo, "diff-tree", "--no-commit-id", "-r", "--raw", PARENT, RUST).splitlines()
    need(paths == [f":160000 160000 8269d772aa1ef02e5efaa331dfb40eb55d71f719 {CARGO} M\tsrc/tools/cargo"], paths)
    need(git(repo, "rev-parse", RUST + ":src/tools/cargo") == CARGO, "wrong Cargo gitlink")


def prepare(workspace):
    root = workspace / "source"
    carrier = workspace / "source-carrier"
    need(git(carrier, "rev-parse", "HEAD") == "0c9c558ce24212e5da6fb66150790b0af3cee90b", "incorrect Rust source transport")
    manifest = json.loads((workspace / "toolchains/1.99.0/22.json").read_bytes())
    commits = {"rust": RUST, "cargo": CARGO, **{name: row[0] for name, row in TOOLS.items()}}
    need({k: v["revision"] for k, v in manifest["sources"].items()} == commits, "wrong coordinator manifest")
    subprocess.run([sys.executable, "-IB", carrier / "scripts/rc22-private-export-ice/subject.py", "prepare", root], check=True)
    rust = root / "rust"
    need(git(rust, "rev-parse", "HEAD") == PARENT, "incorrect qualified precursor")
    unpack(rust, "rust")
    check_rust(rust)
    git(rust, "checkout", "--quiet", "--detach", RUST)
    fixture = rust / "tests/run-make/rdr-public-hash-native-exports/dylib"
    for name in ("leaf.rs", "hidden.rs", "owner.rs", "client.rs"):
        need((fixture / name).read_bytes() == (HERE / "rust-dylib" / name).read_bytes(), f"different checked-in {name}")
    cargo = root / "cargo-source"
    need(git(cargo, "rev-parse", "HEAD", "HEAD^{tree}").splitlines() == [CARGO, CARGO_TREE], "incorrect parsed Cargo source")
    git(rust, "submodule", "init", "--", "src/tools/cargo")
    tools = rust / "src/tools"
    if (tools / "cargo").exists():
        (tools / "cargo").rmdir()
    cargo.rename(tools / "cargo")
    for name in TOOLS:
        (tools / name).rename(root / ("parent-tree-" + name))
        install_tool(tools / name, name)
    subprocess.run([workspace / "scripts/verify-release-sources.sh", workspace / "toolchains/1.99.0/22.json", rust,
                    tools / "cargo", tools / "clippy", tools / "rustfmt"], check=True)
    receipt = {"qa": os.environ["GITHUB_SHA"], "release_coordinator": REVIEWED, "run": os.environ["GITHUB_RUN_ID"],
               "attempt": os.environ["GITHUB_RUN_ATTEMPT"], "target": os.environ["OHM_TARGET"], "commits": commits,
               "trees": {n: git(p, "rev-parse", "HEAD^{tree}") for n, p in [("rust", rust),
                   *((n, tools / n) for n in ("cargo", *TOOLS))]}, "manifest_sha256": sha(workspace / "toolchains/1.99.0/22.json")}
    (root / "reports/integrated-source.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    prepare(Path(os.environ["GITHUB_WORKSPACE"]).resolve())
