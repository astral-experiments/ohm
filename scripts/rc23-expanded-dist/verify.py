"""Bind staged distribution checks to the coordinator and four component revisions under review."""
import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
COORDINATOR = "634d090f0f565936996a817bcb884c64cbe7e6cc"
MANIFEST = "toolchains/1.99.0/23.json"
MANIFEST_SHA = "634a8b8c22792642adf33766c02c33b7b50eccf6b07e17caa4a180c973f819f6"
PREVIOUS_SHA = "67a62c80e9ae1dda7650819511f2329add5db7a9ccf35ef7b1b9b64a314b18a2"
BOOTSTRAP_SHA = "5822d2ae682a27193ef413f013281b0849797c88c78545607ab563ea48f87684"
TOOLCHAIN = "ohm-1.99.0-23"
TARGETS = ("aarch64-apple-darwin", "x86_64-unknown-linux-gnu")
SOURCES = {
    "rust": "f12924d918dbc66898325531940a20aa8cf4f5fc",
    "cargo": "159be68484a7f8cb05debf82bee89e594b7f19b6",
    "clippy": "5b5d9fb377e21872c83ed1598f9ffee1420c7b39",
    "rustfmt": "4b772602480c276b46cd51d44ae3ac0770ca81f5",
}

PROFILE_PATCH = "rustc-perf-relocated-dependencies.patch"
PROFILE_PATCH_SHA = "e9bf8ac4b08fbdb731f9944689d33d0fc7478b75cce39b0883743ac627872bed"
BUILD_SCRIPT_SHA = "cc924169c77f9b0e68eff72a6e5074b254da7293386a201d2794e36521f4460e"

def require(value, message):
    if not value:
        raise ValueError(message)

def digest(path):
    require(stat.S_ISREG(path.lstat().st_mode), f"not a regular file: {path}")
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()

def read(path):
    return json.loads(path.read_bytes())

def head(path):
    return subprocess.check_output(["git", "-C", path, "rev-parse", "HEAD"], text=True).strip()

def coordinator(root):
    manifest = read(root / MANIFEST)
    require(head(root) == COORDINATOR, "different coordinator checkout")
    require(digest(root / MANIFEST) == MANIFEST_SHA, "different release manifest")
    require(digest(root / "toolchains/1.99.0/22.json") == PREVIOUS_SHA, "changed published manifest")
    require({k: v["revision"] for k, v in manifest["sources"].items()} == SOURCES,
            "different component revisions")
    require(manifest["release"]["toolchain_name"] == TOOLCHAIN, "different release name")
    require(manifest.get("prepare_relocated_pgo_dependencies") is True, "missing relocated-dependency preparation")
    require(digest(root / "release" / PROFILE_PATCH) == PROFILE_PATCH_SHA and digest(root / "scripts/build-optimized-dist.sh") == BUILD_SCRIPT_SHA, "changed fixed profile recipe")
    return manifest

def context(root):
    coordinator(root)
    expected = os.environ["REVIEWED_HEAD"]
    require(head(HERE) == os.environ["GITHUB_SHA"] == expected, "different QA revision")
    require(os.environ["GITHUB_REPOSITORY"] == "astral-experiments/ohm"
            and os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"
            and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
            and os.environ["GITHUB_REF"] == "refs/heads/charlie/qa-rc23-profiled-gnu-stage-20261101",
            "unexpected QA workflow")
    return {"coordinator": COORDINATOR, "qa": expected, "run": int(os.environ["GITHUB_RUN_ID"]),
            "job": os.environ["GITHUB_JOB"], "manifest": MANIFEST_SHA, "sources": SOURCES}

def staged(root, directory, target):
    """Read the exact platform archive, its provenance and the checksums embedded by assembly."""
    manifest = coordinator(root)
    require(target in TARGETS, "unknown target")
    stem = f"{TOOLCHAIN}-{target}"
    archive = stem + ".tar.gz"
    provenance = stem + "-provenance.json"
    snapshot = TOOLCHAIN + ".json"
    installer = "ohm-installer.sh"
    expected_local = {archive, archive + ".sha256", provenance, provenance + ".sha256",
                      snapshot, installer, "SHA256SUMS"}
    # The stock coordinator downloads both artifacts directly into its tracked release/ directory.
    require({x.name for x in directory.iterdir()} == expected_local | {"bootstrap.toml", PROFILE_PATCH},
            "unexpected staged asset roster")
    require(digest(directory / "bootstrap.toml") == BOOTSTRAP_SHA, "changed coordinator bootstrap config")
    require(digest(directory / PROFILE_PATCH) == PROFILE_PATCH_SHA, "changed coordinator profile patch")
    hashes = {name: digest(directory / name) for name in expected_local}
    require(hashes[snapshot] == MANIFEST_SHA, "staged manifest differs from coordinator")
    global_hashes = {}
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  ([A-Za-z0-9_.-]+)", line)
        require(match and match[2] not in global_hashes, "invalid global checksum entry")
        global_hashes[match[2]] = match[1]
    artifacts = {f"{TOOLCHAIN}-{t}{tail}" for t in TARGETS
                 for tail in (".tar.gz", ".tar.gz.sha256", "-provenance.json")}
    require(set(global_hashes) == artifacts | {snapshot, installer}, "incomplete global checksum list")
    require(all(global_hashes[name] == hashes[name] for name in expected_local & set(global_hashes)),
            "different staged asset bytes")
    for name in (archive, provenance):
        require((directory / (name + ".sha256")).read_text() == hashes[name] + "  " + name + "\n",
                "incorrect platform checksum")
    embedded = (directory / installer).read_text().splitlines()
    for name in TARGETS:
        binding = f"embedded_archive_sha256_{name.replace('-', '_')}={global_hashes[TOOLCHAIN + '-' + name + '.tar.gz']}"
        require(embedded.count(binding) == 1, "installer selects a different archive")
    require(embedded.count(f"embedded_version={TOOLCHAIN}") == 1, "wrong installer version")
    expected_provenance = {
        "schema_version": 1, "target": target, "toolchain": TOOLCHAIN,
        "coordinator": {"revision": COORDINATOR, "repository": "astral-experiments/ohm"},
        "manifest": {"path": MANIFEST, "sha256": MANIFEST_SHA},
        "sources": {key: {"revision": value} for key, value in SOURCES.items()},
        "bundled_tools": manifest["bundled_tools"] if target == "x86_64-unknown-linux-gnu" else {},
    }
    require(read(directory / provenance) == expected_provenance, "wrong source or tool provenance")
    return {"target": target, "assets": hashes, "bootstrap_sha256": BOOTSTRAP_SHA,
            "archive_bytes": (directory / archive).stat().st_size,
            "global_checksums": global_hashes, "provenance": expected_provenance}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("checkout", "staged"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--target", choices=TARGETS)
    args = parser.parse_args()
    result = context(args.root)
    if args.command == "staged":
        require(args.directory is not None and args.target is not None, "missing staged asset inputs")
        result.update(staged(args.root, args.directory, args.target))
    print(json.dumps(result, sort_keys=True, indent=2))

if __name__ == "__main__":
    main()
