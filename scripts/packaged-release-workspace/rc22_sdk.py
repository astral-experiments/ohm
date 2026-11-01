"""Authenticate the completed GNU distribution job and open its exact host toolchain."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import re
import uuid
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from packages import REPO, api, fetch, need, save, sha

HOST = "x86_64-unknown-linux-gnu"
RUST = "1bc7b35699479d5899a2935d79392b7bdaf7497d"
CARGO = "4591cf45cc10abb19d2456c40b99606e08167f29"
RUN, JOB, ARTIFACT = 41256793646, 124701560401, 13064288126
HEAD = "8b2c911b32b7cad9442b7ddced987c5a1b0a62e5"
BRANCH = "charlie/qa-integrated-native-release-smoke-20261101"
LENGTH = 356748266
ZIP_SHA = "611ee35ee079032afc2f02b9bb832b11b4bde6d9ee7bb82b7332f7485d5b26ee"
TAR_SHA = "0b424df45b3bb9ccea5d1eda44f2481cb17a44f31ec6290e82d3db073489fe8a"
PROV_SHA = "4276832eba50830dbc462bee52958836214a569b05f9f2d996a8cc064aee19bf"
SPEC = json.loads((HERE / "rc22-sdk.json").read_bytes())
REPO_ID = 1319437234
STEPS = {"Verify exact coordinator, inputs and all four source trees", "Build optimized extended Rust distribution",
         "Write build provenance", "Retain distribution artifacts"}

PARENT = "84518a4be7835b57cf8561f9f5020770fad429e7"
PILOT = "charlie/qa-rc22-workspace-50-20261101"

def check_worker(q, expected_head):
    need(re.fullmatch("[0-9a-f]{40}", expected_head) and q["head"] == expected_head and
         q["parent"] == PARENT and q["ref"] == "refs/heads/" + PILOT and q["repository"] == REPO and
         q["workflow"] == ".github/workflows/ci.yml" and q["event"] == "workflow_dispatch" and
         q["attempt"] == 1 and q["job"] == "linux-workspace" and q["run"] > 0 and
         q["machine"] == "x86_64" and q["system"] == "Linux" and q["cpus"] >= 16 and
         q["free_at_entry"] >= (110 << 30) and str(uuid.UUID(q["boot"])) == q["boot"] and
         q["boot"] != "16abddd9-bd9e-4cec-abb2-de8048ac50b0", "unregistered native worker")
    path = Path(q["work_root"])
    need(path.is_absolute() and path.name == "packaged-linux-50", "foreign native workspace root")

def enroll(root):
    root = root.resolve(strict=True)
    need(root.parent == Path(os.environ["RUNNER_TEMP"]).resolve(strict=True), "unexpected runner root")
    git = lambda rev: subprocess.check_output(["git", "rev-parse", rev], text=True).strip()
    e = os.environ
    q = {"head": git("HEAD"), "parent": git("HEAD^"), "ref": e["GITHUB_REF"], "repository": e["GITHUB_REPOSITORY"],
         "workflow": ".github/workflows/ci.yml", "event": e["GITHUB_EVENT_NAME"], "attempt": int(e["GITHUB_RUN_ATTEMPT"]),
         "job": e["GITHUB_JOB"], "run": int(e["GITHUB_RUN_ID"]), "machine": platform.machine(), "system": platform.system(),
         "cpus": len(os.sched_getaffinity(0)), "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
         "kernel": platform.release(), "free_at_entry": shutil.disk_usage(root).free, "work_root": str(root)}
    need(e["GITHUB_SHA"] == e["REVIEWED_HEAD"], "different workflow input")
    check_worker(q, e["REVIEWED_HEAD"])
    save(root / "receipts/shared/enrollment.json", q)

def check_origin(origin):
    run, job, art = (origin[k] for k in ("run", "job", "artifact"))
    need((run["id"], run["run_attempt"], run["head_sha"], run["head_branch"], run["path"],
          run["event"], run["status"], run["conclusion"], run["repository"]["full_name"]) ==
         (RUN, 1, HEAD, BRANCH, ".github/workflows/ci.yml", "workflow_dispatch", "completed", "failure", REPO),
         "foreign original workflow")
    need((job["id"], job["run_id"], job["run_attempt"], job["head_sha"], job["name"],
          job["status"], job["conclusion"]) ==
         (JOB, RUN, 1, HEAD, "Private optimized dist " + HOST, "completed", "success"),
         "foreign or unsuccessful GNU job")
    need(run["repository"]["id"] == REPO_ID and art["workflow_run"]["repository_id"] == REPO_ID and
         art["workflow_run"]["head_repository_id"] == REPO_ID and art["workflow_run"]["head_branch"] == BRANCH,
         "foreign source or repository identifier")
    need(STEPS <= {s["name"] for s in job["steps"] if s["conclusion"] == "success"}, "missing native build step")
    need((art["id"], art["name"], art["size_in_bytes"], art["digest"], art["workflow_run"]["id"],
          art["workflow_run"]["head_sha"]) ==
         (ARTIFACT, "qa-dist-" + HOST, LENGTH, "sha256:" + ZIP_SHA, RUN, HEAD), "foreign GNU artifact")

def check_members(files):
    need(files == SPEC["files"] and len(files) == 79, "wrong physical GNU toolchain inventory")

def transfer(archive, destination=None):
    """Hash every selected tar member, optionally writing to the owner's new private directory."""
    need(archive.stat().st_size == LENGTH and sha(archive) == ZIP_SHA, "different official GNU ZIP")
    stem = "ohm-1.99.0-22-" + HOST
    tar, prov = stem + ".tar.gz", stem + "-provenance.json"
    files = {}
    with zipfile.ZipFile(archive) as z:
        need(sorted(z.namelist()) == sorted((tar, prov, tar + ".sha256", prov + ".sha256")), "unexpected ZIP member")
        need(z.getinfo(tar).file_size == 359784853 and z.getinfo(prov).file_size == 877, "unknown uncompressed archive")
        raw = z.read(prov)
        need(hashlib.sha256(raw).hexdigest() == PROV_SHA and json.loads(raw) == SPEC["provenance"], "bad source provenance")
        for name, digest in ((tar, TAR_SHA), (prov, PROV_SHA)):
            need(z.read(name + ".sha256").decode().split() == [digest, name], "incorrect inner checksum")
        with z.open(tar) as f:
            need(hashlib.file_digest(f, "sha256").hexdigest() == TAR_SHA, "inner GNU tar differs")
        with z.open(tar) as f, tarfile.open(fileobj=f, mode="r|gz", bufsize=1<<20) as tf:
            for member in tf:
                p = PurePosixPath(member.name)
                need(not p.is_absolute() and ".." not in p.parts and p.parts[0] == "rust-1.99.0-dev-" + HOST, "foreign tar pathname")
                if member.isdir() or len(p.parts) < 4:
                    continue
                _, component, *rest = p.parts
                if not (component == "cargo" and rest == ["bin", "cargo"]
                        or component == "rustc" and rest[0] in ("bin", "lib", "libexec")
                        or component == "rust-docs" and rest == ["bin", "rustdoc"]
                        or component == "rust-std-" + HOST and rest[0] == "lib"):
                    continue
                key = "/".join(rest)
                need(key in SPEC["files"] and key not in files and member.isfile(), "unrecognized installed member")
                length, expected, mode = SPEC["files"][key]
                need((member.size, member.mode & 0o755) == (length, mode), "foreign size/mode")
                hasher = hashlib.sha256()
                with tf.extractfile(member) as src:
                    if destination is None:
                        digest = hashlib.file_digest(src, "sha256").hexdigest()
                    else:
                        output = destination / key
                        output.parent.mkdir(parents=True, exist_ok=True)
                        with output.open("xb") as out:
                            while block := src.read(1<<20):
                                out.write(block)
                                hasher.update(block)
                        output.chmod(mode)
                        digest = hasher.hexdigest()
                        need(output.stat().st_size == length and sha(output) == digest, "installed member differs")
                need(digest == expected, "wrong member " + key)
                files[key] = [length, digest, mode]
    check_members(files)
    return files

def install(root):
    need(platform.system() == "Linux" and platform.machine() == "x86_64", "wrong workload host")
    need(root.name == "packaged-linux-50" and root.parent == Path(os.environ["RUNNER_TEMP"]).resolve(), "unexpected owner")
    original = {"run": api(f"actions/runs/{RUN}"), "job": api(f"actions/jobs/{JOB}"),
                "artifact": api(f"actions/artifacts/{ARTIFACT}")}
    check_origin(original)
    need(not original["artifact"]["expired"] and shutil.disk_usage(root).free >= (65<<30)+LENGTH+(650<<20),
         "GNU archive unavailable or insufficient private space")
    rec = root / "receipts/22"
    rec.mkdir(exist_ok=False)
    save(rec / "origin.json", original)
    final = root / "sdk-22"
    need(not final.exists(), "existing toolchain")
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        tmp = Path(tmp)
        kit = tmp / "kit"
        kit.mkdir()
        archive = tmp / "original.zip"
        fetch(f"actions/artifacts/{ARTIFACT}/zip", archive)
        files = transfer(archive, kit)
        kit.rename(final)
    save(rec / "installed.json", {k: v[1] for k, v in files.items()})
    save(rec / "custody.json", {"zip": ZIP_SHA, "tar": TAR_SHA, "provenance": SPEC["provenance"],
                                "members": files, "job": JOB})
    for tool, commit in (("rustc", RUST), ("rustdoc", RUST), ("cargo", CARGO)):
        raw = subprocess.check_output([final / "bin" / tool, "-vV"], text=True)
        need("commit-hash: " + commit in raw.splitlines() and "host: " + HOST in raw.splitlines(), "wrong executable version")
        (rec / (tool + ".version")).write_text(raw)

def verify_receipt(c):
    check_origin(c.json("22/origin.json"))
    q = c.json("22/custody.json")
    need((q["zip"], q["tar"], q["job"], q["provenance"]) == (ZIP_SHA, TAR_SHA, JOB, SPEC["provenance"]), "different native receipt")
    check_members(q["members"])
    need(c.json("22/installed.json") == {k: v[1] for k, v in q["members"].items()}, "different installed set")
    for tool, commit in (("rustc", RUST), ("rustdoc", RUST), ("cargo", CARGO)):
        lines = c.get("22/" + tool + ".version").decode().splitlines()
        need("commit-hash: " + commit in lines and "host: " + HOST in lines, "different installed " + tool)

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "read":
        print(len(transfer(Path(sys.argv[2]))), "authenticated GNU files")
    elif len(sys.argv) == 3 and sys.argv[1] == "enroll":
        enroll(Path(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "install":
        install(Path(sys.argv[2]).resolve(strict=True))
    else:
        raise SystemExit("rc22_sdk.py {read ZIP|enroll NEW_ROOT|install NEW_ROOT}")
