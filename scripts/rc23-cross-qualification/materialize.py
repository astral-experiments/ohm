"""Reconstruct the four release sources from the verified original -23 checkouts."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

here = Path(__file__).resolve().parent
work = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
reference = work / "release-reference"
evidence = work / "cross-evidence"
evidence.mkdir(exist_ok=True)
plan = json.loads((here / "protocol.json").read_text())
arm, = sys.argv[1:]
assert arm in plan["arms"]
assert os.environ["GITHUB_REPOSITORY"] == "astral-experiments/ohm"
assert os.environ["GITHUB_REF"] == "refs/heads/charlie/codex-rc23-profile-diagnostic"
assert os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"

def git(root, *args):
    return subprocess.check_output(["git", "-C", root, *args], text=True).strip()

def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

assert git(work, "rev-parse", "HEAD") == os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"]
assert git(reference, "rev-parse", "HEAD") == plan["original_coordinator"]
old = reference / "toolchains/1.99.0/23.json"
assert digest(old) == plan["original_manifest_sha256"]
manifest = json.loads(old.read_text())
subprocess.run([sys.executable, "-IB", work / "scripts/integrated-dist-qa/sources.py"], check=True)
spec = importlib.util.spec_from_file_location("original_source", work / "scripts/dep-graph-slots/qualify.py")
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)
rust = work / "source/rust"
qa.install_source(work, rust, work / "source/reports")
qa.verify_live(rust)
for name, source in plan["sources"].items():
    repo = rust if name == "rust" else rust / "src/tools" / name
    assert git(repo, "rev-parse", "HEAD") == source["base"] == manifest["sources"][name]["revision"]
    packet = here / (name + ".pack")
    assert packet.stat().st_size == source["bytes"] and digest(packet) == source["sha256"]
    with packet.open("rb") as stream:
        subprocess.run(["git", "-C", repo, "index-pack", "--strict", "--stdin"], stdin=stream, check=True)
    assert git(repo, "rev-parse", source["end"] + "^{tree}") == source["tree"]
    revision = plan["arms"][arm]["commit"] if name == "rust" else source["end"]
    if name == "rust":
        assert git(repo, "rev-parse", revision + "^{tree}") == plan["arms"][arm]["tree"]
        assert git(repo, "rev-parse", revision + ":src/tools/cargo") == plan["sources"]["cargo"]["end"]
        paths = git(repo, "diff", "--name-only", plan["arms"]["base"]["commit"], plan["arms"]["cross"]["commit"])
        assert sorted(paths.splitlines()) == sorted(plan["cross_paths"])
    git(repo, "checkout", "--no-recurse-submodules", "--quiet", "--detach", revision)
    assert git(repo, "rev-parse", "HEAD") == revision
    manifest["sources"][name]["revision"] = revision
with tempfile.TemporaryDirectory() as stage:
    root = Path(stage) / "toolchains"
    versions = root / "1.99.0"
    versions.mkdir(parents=True)
    (root / "manifest.schema.json").write_bytes((reference / "toolchains/manifest.schema.json").read_bytes())
    candidate = versions / "23.json"
    candidate.write_text(json.dumps(manifest, indent=2) + "\n")
    subprocess.run([reference / "scripts/verify-release-sources.sh", candidate, rust, *[rust / "src/tools" / name for name in ("cargo", "clippy", "rustfmt")]], check=True)
assert manifest["bundled_tools"] == json.loads(old.read_text())["bundled_tools"]
(evidence / "source.json").write_text(json.dumps({"arm": arm, "sources": manifest, "transport": plan["sources"], "workflow": os.environ["GITHUB_SHA"], "run": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"]}, indent=2) + "\n")
