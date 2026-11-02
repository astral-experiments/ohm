"""Reconstruct and verify the published -23 source trees in an unprivileged qualification job."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

here = Path(__file__).resolve().parent
work = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
evidence = work / "cross-evidence"
evidence.mkdir(exist_ok=True)
plan = json.loads((here / "protocol.json").read_bytes())
assert os.environ["GITHUB_REPOSITORY"] == "astral-experiments/ohm"
assert os.environ["GITHUB_REF"] == "refs/heads/charlie/codex-rc23-qualify-cached-doctests-v2"
assert os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"

def git(repo, *args):
    return subprocess.check_output(["git", "-C", repo, *args], text=True).strip()

def sha(path):
    with path.open("rb") as reader:
        return hashlib.file_digest(reader, "sha256").hexdigest()

assert git(work,"rev-parse","HEAD") == os.environ["REVIEWED_HEAD"] == os.environ["GITHUB_SHA"]
original = work / "release-reference"
published = work / "release-candidate"
assert git(original,"rev-parse","HEAD") == plan["original_coordinator"]
assert git(published,"rev-parse","HEAD") == plan["published_coordinator"]
relative = "toolchains/1.99.0/23.json"
initial = original / relative
manifest = published / relative
assert sha(initial) == plan["original_manifest_sha256"]
assert sha(manifest) == plan["published_manifest_sha256"]
before = json.loads(initial.read_bytes())
final = json.loads(manifest.read_bytes())
assert final["release"] == before["release"] and final["bundled_tools"] == before["bundled_tools"]
assert final["prepare_relocated_pgo_dependencies"] is True
assert sha(published/"scripts/smoke-test-release.sh") == plan["smoke_script_sha256"]
assert sha(published/"scripts/build-optimized-dist.sh") == plan["build_script_sha256"]
assert sha(published/"release/bootstrap.toml") == plan["bootstrap_sha256"]
assert sha(published/"release/rustc-perf-relocated-dependencies.patch") == plan["profile_patch_sha256"]
subprocess.run([sys.executable, "-IB", work/"scripts/integrated-dist-qa/sources.py"], check=True)
spec = importlib.util.spec_from_file_location("original_source",work/"scripts/dep-graph-slots/qualify.py")
hub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub)
rust = work/"source/rust"
hub.install_source(work,rust,work/"source/reports")
hub.verify_live(rust)
assert set(plan["sources"]) == set(final["sources"]) == {"rust","cargo","clippy","rustfmt"}
verified = {}
for name, source in plan["sources"].items():
    repo = rust if name == "rust" else rust / "src/tools" / name
    assert git(repo,"rev-parse","HEAD") == before["sources"][name]["revision"] == source["base"]
    for packet in source["packets"]:
        path = here / packet["file"]
        assert path.parent == here and path.stat().st_size == packet["bytes"]
        assert sha(path) == packet["sha256"]
        with path.open("rb") as reader:
            subprocess.run(["git","-C",repo,"index-pack","--strict","--stdin"],stdin=reader,check=True)
    revision=source["end"]
    assert revision == final["sources"][name]["revision"]
    assert git(repo,"rev-parse",revision+"^{tree}") == source["tree"]
    if name == "rust":
        assert git(repo,"rev-parse",revision+":src/tools/cargo") == final["sources"]["cargo"]["revision"]
    subprocess.run(["git","-C",repo,"checkout","--quiet","--no-recurse-submodules","--detach",revision],check=True)
    assert git(repo,"rev-parse","HEAD") == revision
    verified[name] = {"revision":revision,"tree":source["tree"]}
subprocess.run([published/"scripts/verify-release-sources.sh",manifest,rust,*[rust/"src/tools"/n for n in ("cargo","clippy","rustfmt")]],check=True)
proof={"target":os.environ["OHM_TARGET"],"source_trees":verified,"manifest":final,"coordinator":plan["published_coordinator"],"manifest_sha256":sha(manifest),"workflow":git(work,"rev-parse","HEAD"),"run":os.environ["GITHUB_RUN_ID"],"attempt":os.environ["GITHUB_RUN_ATTEMPT"]}
(evidence/"source.json").write_text(json.dumps(proof,indent=2)+"\n")
