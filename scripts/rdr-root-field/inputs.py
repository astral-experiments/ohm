"""Bind the exact live compiler fork tree and its previously built native parent."""

import gzip
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE.parent / "gnu-renderer-cgu-source"
sys.path.insert(0, str(ORIGINAL))
import build
import source
from restore import restore

P = source.BASE
C = "cb06be7edfc264edd87f44f58713e6ae00056c84"
TREE = "d99b741c05c4e62e41740fe338a4232bfe3aeb90"
COMPILER = "c448a179f26e051e2e2989e80142bc32d553d70b"
FIXTURE = "rdr-crate-root-field-visibility"
FIXTURE_TREE = "15fcd3f33090079fc5a86aaa60b4eaa4fcbbdd26"
QA = "a4afd181ae07107de6174a17a4ec189061fd18aa"
RUN, JOB, ATTEMPT = 41185180848, 124490558713, 1
MEMBERS = {
    "gnu-renderer-qualified-native": (13036884070, 303780362, "b526f3f4c4fd9a07974cc7456904b506f13aed106bee26553a421311cb21b2bc"),
    "gnu-renderer-source-native-observations": (13036848222, 1024910, "fc48c08002248c776ac82372c97dd308ef385e9ba43224fdd0a9b783b8289624"),
}
MANIFEST = "0b9c998d560decb25c9f30fb97a8d1f336fd151150edca1087b5e542a0923c72"
BOOT_ARGS = ["./x", *build.OPTIONS, "build", *build.HOST_FLAGS, *build.SDK_COMPONENTS]
need, git, obj = source.need, source.git, source.obj


def materialize(repo):
    source.live_base(repo, ORIGINAL / "packet")
    patch = gzip.decompress((HERE / "source.patch.gz").read_bytes())
    commit = (HERE / "source.commit").read_bytes()
    need(source.digest(patch) == "e15ef5874840580af55284381a9a51133d4de36f405cb0a82fa3d78312f9ff9c" and source.digest(commit) == "249f8f2a111a80fa5cb4a050a43f44393ef1e9c14eaf009bbcd06b015466fea0", "source envelope")
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(td) / "index"))
        git(repo, "read-tree", P, env=env)
        git(repo, "apply", "--cached", "--binary", "--whitespace=error", "--check", "-", env=env, data=patch)
        git(repo, "apply", "--cached", "--binary", "--whitespace=error", "-", env=env, data=patch)
        need(git(repo, "write-tree", env=env).decode().strip() == TREE, "reconstructed different tree")
        need(git(repo, "hash-object", "-t", "commit", "-w", "--stdin", data=commit).decode().strip() == C, "reconstructed different commit")
    need(obj(repo, C + "^") == P and obj(repo, C + ":compiler") == COMPILER and obj(repo, C + ":tests/run-make/" + FIXTURE) == FIXTURE_TREE, "wrong compiler or fixture")
    for path in ("library", "src/bootstrap", "src/llvm-project", "src/stage0", "src/version", "src/tools/run-make-support", "x", "x.py", "AGENTS.md"):
        need(obj(repo, C + ":" + path) == obj(repo, P + ":" + path), "non-treatment changed " + path)
    actual = source.two_dot(repo, P, C)
    # Bare Git and the checkout use different Rust function-context labels in one hunk header.
    # The five file pairs, complete before/after IDs and every hunk body must be identical.
    def hunk_body(raw):
        return re.sub(rb"(?m)^(@@ [-+0-9, ]+ @@)[^\n]*$", rb"\1", raw)
    need(source.digest(actual) in {source.digest(patch), "75b1dc2ea6220746542a61b76140835b6dc6f9669dd42792abfd6c1fb33aa15b"}
         and hunk_body(actual) == hunk_body(patch), "two-dot source")
    return {"P": source.identity(repo, P), "C": source.identity(repo, C)}


def api(endpoint, dest=None):
    cmd = [os.environ.get("RDR_GH", "gh"), "api", "repos/astral-experiments/ohm/actions/" + endpoint]
    if dest is None:
        return json.loads(subprocess.check_output(cmd))
    with dest.open("xb") as f:
        subprocess.run(cmd, stdout=f, check=True)


def official(dest):
    run = api("runs/" + str(RUN))
    job = api("jobs/" + str(JOB))
    need((run["id"], run["head_sha"], run["run_attempt"], run["conclusion"], run["event"], run["path"]) == (RUN, QA, ATTEMPT, "success", "workflow_dispatch", ".github/workflows/ci.yml"), "parent run")
    need((job["id"], job["run_id"], job["head_sha"], job["status"], job["conclusion"]) == (JOB, RUN, QA, "completed", "success"), "parent job")
    listing = api(f"runs/{RUN}/artifacts?per_page=100")
    records = {}
    for name,(ident,size,sha) in MEMBERS.items():
        selected = [a for a in listing["artifacts"] if a["name"] == name]
        need(len(selected) == 1, "ambiguous artifact")
        a, = selected
        need((a["id"], a["size_in_bytes"], a["digest"], a["expired"], a["workflow_run"]["head_sha"]) == (ident,size,"sha256:"+sha,False,QA), "official zip mismatch")
        api("artifacts/" + str(ident) + "/zip", dest / (name+".zip"))
        records[name] = a
    build.write(dest/"original-api.json", {"run": run,"job":job,"artifacts":records})


def parent(zips, out=None):
    for name,(_,size,digest) in MEMBERS.items():
        p = zips / (name+".zip")
        need(p.stat().st_size == size and build.sha(p) == digest, "original ZIP digest")
    with zipfile.ZipFile(zips / "gnu-renderer-qualified-native.zip") as z:
        names = z.namelist()
        raw = z.read("manifest.json")
        need(source.digest(raw) == MANIFEST, "parent native manifest SHA")
        data = json.loads(raw)
        need(len(names) == 4 and set(names) == {"manifest.json", *data["products"]}, "wrong prior member set")
        need(data["roles"]["P"]["source"]["commit"] == P and data["roles"]["P"]["source"]["compiler"] == source.COMPILER and len(data["files"]) == 81, "parent source/members")
        if out:
            transfer = out / "parent-transfer"
            transfer.mkdir()
            for name in names:
                with z.open(name) as src, (transfer / name).open("xb") as dst:
                    shutil.copyfileobj(src, dst)
            restore(transfer, out / "parent-sdk", "P", QA, RUN, ATTEMPT)
    with zipfile.ZipFile(zips / "gnu-renderer-source-native-observations.zip") as z:
        cmd = json.loads(z.read("receipts/P/bootstrap.command.json"))
        need(cmd["argv"] == BOOT_ARGS and cmd["cwd"] == str(build.ROOT / "rust") and cmd["returncode"] == 0, "source-built differently")
        need(cmd["output_sha256"] == source.digest(z.read("receipts/P/bootstrap.log")), "parent bootstrap log")
        need(json.loads(z.read("receipts/P/physical-files.json")) == data["files"], "all parent runtime members")
        identity = json.loads(z.read("receipts/P/source.json"))
        need(identity["commit"] == P and identity["llvm"] == build.LLVM and identity["stage0"] == build.STAGE0 and identity["bootstrap"] == source.BOOT, "bootstrap inputs")
        need(identity["launcher"]["blobs"] == build.ENTRYPOINTS, "entrypoint")
        need(z.read("receipts/P/rustc.log").decode() == data["compiler_verbose"], "physical parent version")
    return data


if __name__ == "__main__":
    action, arg = sys.argv[1:]
    if action == "source":
        print(json.dumps(materialize(Path(arg)),sort_keys=True))
    elif action == "original":
        print(json.dumps(parent(Path(arg))["roles"]["P"],sort_keys=True))
    elif action == "acquire":
        dest=Path(arg); official(dest); parent(dest, build.ROOT)
    else:
        raise ValueError(action)
