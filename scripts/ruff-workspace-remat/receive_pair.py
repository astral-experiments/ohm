"""Receive a registered nonrelease compiler build on a fresh GitHub Actions worker."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

REPO = "astral-experiments/ohm"
BRANCH = "charlie/qa-remat-live-pin-20261102"
ARTIFACT = "ohm-remat-matched-stage1"
GIB = 1024**3


def need(value, why):
    if not value:
        raise ValueError(why)


def api(endpoint):
    return json.loads(subprocess.check_output(["gh", "api", f"repos/{REPO}/actions/{endpoint}"]))


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def receive(artifact, target):
    size = artifact["size_in_bytes"]
    need(0 < size < 4 * GIB, "unexpected archive size")
    with target.open("xb") as dest, subprocess.Popen(
        ["gh", "api", f"repos/{REPO}/actions/artifacts/{artifact['id']}/zip"],
        stdout=subprocess.PIPE,
    ) as get:
        received = 0
        calc = hashlib.sha256()
        for block in iter(lambda: get.stdout.read(1024**2), b""):
            received += len(block)
            need(received <= size, "archive exceeded its receipt")
            calc.update(block)
            dest.write(block)
        need(get.wait() == 0 and received == size and f"sha256:{calc.hexdigest()}" == artifact["digest"],
             "download differs from registered archive")


def unpack(archive, folder, tar_digest):
    payload = folder / "matched-stage.tar.zst"
    with zipfile.ZipFile(archive) as z:
        member, = z.infolist()
        need(member.filename == payload.name and 0 < member.file_size < 4 * GIB, "foreign compiler ZIP")
        with z.open(member) as src, payload.open("xb") as out:
            shutil.copyfileobj(src, out, 1024**2)
    need(digest(payload) == tar_digest, "unregistered compiler payload")
    archive.unlink()
    seen = set()
    total = 0
    with subprocess.Popen(["zstd", "-dqc", payload], stdout=subprocess.PIPE) as decoder:
        with tarfile.open(fileobj=decoder.stdout, mode="r|") as tar:
            for member in tar:
                name = member.name
                if member.isdir() and name in {"capsule", "capsule/objects"}:
                    (folder / name).mkdir(exist_ok=True)
                    continue
                need(member.isfile() and re.fullmatch(r"capsule/(?:[PC]\.json|qualified\.json|objects/[0-9a-f]{64})", name)
                     and name not in seen, ("foreign compiler member", name))
                seen.add(name)
                total += member.size
                need(len(seen) < 900 and 0 < member.size <= 2 * GIB and total < 7 * GIB, "compiler size limit")
                if "/objects/" not in name:
                    need(member.size < 8 * 1024**2, "unexpected manifest size")
                target = folder / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as incoming, target.open("xb") as dest:
                    shutil.copyfileobj(incoming, dest, 1024**2)
                need(target.stat().st_size == member.size, "truncated compiler member")
                if "/objects/" in name:
                    need(digest(target) == target.name and member.mode & ~0o555 == 0 and member.mode & 0o400,
                         "invalid compiler object hash or permissions")
                    target.chmod(member.mode)
        # tarfile may stop at the first end-of-archive block. zstd must finish the complete frame.
        for padding in iter(lambda: decoder.stdout.read(64 * 1024), b""):
            need(not any(padding), "unexpected bytes after compiler archive")
        need(decoder.wait() == 0, "truncated compiler frame")
    need({"capsule/P.json", "capsule/C.json", "capsule/qualified.json"}.issubset(seen), "missing compiler manifest")
    payload.unlink()


def main(registration, recipe, folder):
    reg = json.loads(registration.read_bytes())
    need(reg["schema"] == "ohm-ruff-compiler-factory-v1" and os.environ["GITHUB_REPOSITORY"] == REPO,
         "wrong compiler receiver")
    rid = reg["run"]
    run = api(f"runs/{rid}")
    need(run["id"] == rid and run["event"] == "workflow_dispatch" and run["run_attempt"] == 1
         and run["head_branch"] == BRANCH and run["head_sha"] == reg["head"] and run["path"] == ".github/workflows/ci.yml"
         and run["conclusion"] == "success", "unqualified compiler factory run")
    job, = api(f"runs/{rid}/jobs")["jobs"]
    need(job["id"] == reg["job"] and job["name"] == reg["job_name"] and job["conclusion"] == "success", "factory job")
    reported = api(f"runs/{rid}/artifacts")
    arts = {a["name"]: a for a in reported["artifacts"]}
    need(reported["total_count"] == len(arts) == 2 and set(arts) == set(reg["artifacts"]), "factory artifacts")
    for name, entry in reg["artifacts"].items():
        live = arts[name]
        need(not live["expired"] and [live[k] for k in ("id", "size_in_bytes", "digest")] == entry,
             ("factory artifact changed", name))
    need(subprocess.check_output(["git", "-C", recipe, "rev-parse", "HEAD"], text=True).strip() == reg["head"],
         "different factory source")
    materializer = recipe / "scripts/ruff-matched-stage/capsule.py"
    need(digest(materializer) == reg["materializer_sha256"], "different compiler materializer")
    need(folder.resolve() == folder and not folder.exists() and shutil.disk_usage(folder.parent).free > 12 * GIB,
         "use an empty private receiver with enough space")
    folder.mkdir(mode=0o700)
    archive = folder / "attributed.zip"
    receive(arts[ARTIFACT], archive)
    unpack(archive, folder, reg["tar_sha256"])
    subprocess.run([sys.executable, "-IB", materializer, folder / "capsule", folder / "roots"], check=True)
    manifest = folder / "roots/rustcs.json"
    need(json.loads(manifest.read_bytes())["schema"] == "ohm-matched-rustcs-v1", "wrong materialized compiler pair")
    return {"compiler_study": reg, "manifest_sha256": digest(manifest)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("registration", "recipe", "folder"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    print(json.dumps(main(args.registration, args.recipe, args.folder), sort_keys=True))
