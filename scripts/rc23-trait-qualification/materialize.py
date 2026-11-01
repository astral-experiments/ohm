"""Reconstruct the RC sources and apply the checked trait-lookup Git trees."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

here = Path(__file__).resolve().parent
w = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
ref = w / "release-reference"
rust = w / "source/rust"
proof = w / "trait-evidence"
proof.mkdir(exist_ok=True)
arm, = sys.argv[1:]
pins = json.loads((here/"arms.json").read_bytes())
spec = pins["arms"][arm]
def git(p,*args):
    return subprocess.check_output(["git","-C",p,*args],text=True).strip()
def digest(file):
    with file.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()
def load(path):
    s = importlib.util.spec_from_file_location("qa_source",path)
    mod = importlib.util.module_from_spec(s)
    s.loader.exec_module(mod)
    return mod
assert os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"
assert os.environ["GITHUB_REPOSITORY"] == "astral-experiments/ohm"
assert os.environ["GITHUB_REF"] == "refs/heads/charlie/codex-rc23-trait-qualification"
assert git(w,"rev-parse","HEAD") == os.environ["REVIEWED_HEAD"] == os.environ["GITHUB_SHA"]
assert git(ref,"rev-parse","HEAD") == "90575c9fc302c2af0858c711726b2d211e7d3114"
subject = ref/"toolchains/1.99.0/23.json"
assert digest(subject) == pins["source_manifest_sha256"]
manifest = json.loads(subject.read_bytes())
assert manifest["sources"]["rust"]["revision"] == pins["arms"]["base"]["rust"]
subprocess.run([sys.executable,"-IB",w/"scripts/integrated-dist-qa/sources.py"],check=True)
qa = load(w/"scripts/dep-graph-slots/qualify.py")
qa.install_source(w,rust,w/"source/reports")
qa.verify_live(rust)
assert digest(w/"toolchains/1.99.0/23.json") == digest(subject)
packet = here/"candidates.pack"
assert packet.stat().st_size == pins["pack_bytes"] and digest(packet) == pins["pack_sha256"]
with packet.open("rb") as src:
    subprocess.run(["git","-C",rust,"index-pack","--strict","--stdin"],stdin=src,check=True)
for label, item in pins["arms"].items():
    oid = item["rust"]
    assert git(rust,"rev-parse",oid+"^{tree}") == item["tree"]
    assert git(rust,"rev-parse",oid+":src/tools/cargo") == pins["cargo"]
    if label != "base":
        assert git(rust,"rev-parse",oid+"^") == item["parent"]
        assert set(git(rust,"diff","--name-only",item["parent"],oid).splitlines()) == set(item["paths"])
subprocess.run(["git","-C",rust,"checkout","--no-recurse-submodules","--quiet","--detach",spec["rust"]],check=True)
assert git(rust,"rev-parse","HEAD") == spec["rust"]
assert not git(rust,"diff","--name-only","HEAD","--","compiler","tests/run-make/trait-impl-bucket-projection")
assert git(rust/"src/tools/cargo","rev-parse","HEAD") == pins["cargo"]
epoch = pins["base_epoch"] if arm == "base" else pins["epoch"]
assert f"const HEADER_FORMAT_VERSION: u16 = {epoch};" in (rust/"compiler/rustc_incremental/src/persist/file_format.rs").read_text()
manifest["sources"]["rust"]["revision"] = spec["rust"]
with tempfile.TemporaryDirectory() as tmp:
    toolchains = Path(tmp)/"toolchains"
    versions = toolchains/"1.99.0"
    versions.mkdir(parents=True)
    (toolchains/"manifest.schema.json").write_bytes((ref/"toolchains/manifest.schema.json").read_bytes())
    version = versions/"23.json"
    version.write_text(json.dumps(manifest,indent=2)+"\n")
    subprocess.run([ref/"scripts/verify-release-sources.sh",version,rust,*[rust/"src/tools"/k for k in ("cargo","clippy","rustfmt")]],check=True)
record = {"arm":arm,"source":spec,"manifest":manifest,"base_manifest_sha256":digest(subject),"epoch":epoch,
          "scripts":{n:digest(ref/n) for n in ("release/bootstrap.toml","scripts/build-optimized-dist.sh","scripts/prepare-wild.py")},
          "workflow":os.environ["GITHUB_SHA"],"run":os.environ["GITHUB_RUN_ID"],"attempt":os.environ["GITHUB_RUN_ATTEMPT"]}
(proof/"source.json").write_text(json.dumps(record,indent=2)+"\n")
