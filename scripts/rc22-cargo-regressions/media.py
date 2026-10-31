"""Seal or confirm an official, successful native SDK job on the dedicated packaging ref."""
import argparse
import base64
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kit

HERE = Path(__file__).resolve().parent
BRANCH = "charlie/qa-rc22-native-markers-20261031"
ARTIFACT = "rc22-native-sdk-" + kit.TRIPLE
STEPS = ("Build exact native Rust, standard library, rustdoc and both Cargo readers",
         "Reopen every completed SDK member", "Publish reusable native SDK")
SOURCE = "7bc72b798b019a9ec0de6eeea3bc22b783917b27"
SOURCE_RUN = 41212542603
SOURCE_JOB = 124570376741
READERS = {"sdk.py": "873a7658e11d66a9494fb9fa7d039c5632b7f8739e305ff1136f8982b204bdcb",
           "common.py": "e1e648c3e3ffd01a3436c4f2aa2dc0fc764cf3510d5232501f68a370efa5dfd0"}


def commit(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{40}", value) is not None


def canonical(gh, endpoint):
    return kit.strict_json(subprocess.check_output([gh, "api", endpoint]))


def body(official, location):
    row, = [x for x in location if x["name"] == ARTIFACT]
    wr = row["workflow_run"]
    size = row["size_in_bytes"]
    kit.need(wr["id"] == official["run"] and wr["head_sha"] == official["source_head"] and
             wr["repository_id"] == wr["head_repository_id"] == official["repository_id"] and wr["head_branch"] == BRANCH and
             row["expired"] is False and type(row["id"]) is int and row["id"] > 0 and
             0 < size <= sum(kit.ZIP_LIMITS.values()) + (1 << 20) and
             re.fullmatch(r"sha256:[a-f0-9]{64}", row["digest"]), "wrong, expired or unsealed official artifact")
    return {"name": ARTIFACT, "id": row["id"], "size": size, "sha256": row["digest"][7:]}


def catalog(repo, run, jobs, artifacts, source_head, run_id):
    kit.need(commit(source_head) and type(run_id) is int and run_id > 0, "invalid source identity")
    kit.need(repo["full_name"] == kit.REPO and repo["private"] is True and repo["id"] == 1319437234 and
             run["repository"]["id"] == run["head_repository"]["id"] == repo["id"] and
             run["repository"]["full_name"] == run["head_repository"]["full_name"] == kit.REPO,
             "untrusted repository or fork")
    kit.need(run["id"] == run_id and run["head_sha"] == source_head and run["head_branch"] == BRANCH
             and run["event"] == "workflow_dispatch" and run["run_attempt"] == 1
             and run["path"] == ".github/workflows/ci.yml" and run["workflow_id"] == 325165136,
             "wrong source workflow, ref, commit or attempt")
    kit.need(len(jobs["jobs"]) == jobs["total_count"] and len(artifacts["artifacts"]) == artifacts["total_count"],
             "truncated official inventory")
    job, = [j for j in jobs["jobs"] if j["name"] == "Native SDK (" + kit.TRIPLE + ")"]
    kit.need(job["run_id"] == run_id and job["head_sha"] == source_head and job["run_attempt"] == 1 and
             job["status"] == "completed" and job["conclusion"] == "success" and job["id"] > 0,
             "native source job did not pass on this head and attempt")
    ordinals = []
    for name in STEPS:
        step, = [s for s in job["steps"] if s["name"] == name]
        kit.need(step["status"] == "completed" and step["conclusion"] == "success", "missing successful " + name)
        ordinals.append(step["number"])
    kit.need(ordinals == sorted(set(ordinals)), "source build/reopen/upload out of order")
    result = {"schema": 1, "repository": kit.REPO, "repository_id": repo["id"], "run": run_id, "attempt": 1,
              "source_head": source_head, "branch": BRANCH, "workflow": run["workflow_id"], "job": job["id"]}
    result["artifact"] = body(result, artifacts["artifacts"])
    return result


def official(gh, head, run_id):
    kit.need((head, run_id) == (SOURCE, SOURCE_RUN), "source head or run needs an independent review")
    base = "repos/" + kit.REPO
    path = base + "/actions/runs/" + str(run_id)
    result = catalog(canonical(gh, base), canonical(gh, path + "/attempts/1"),
                   canonical(gh, path + "/attempts/1/jobs?per_page=100"),
                   canonical(gh, path + "/artifacts?per_page=100"), head, run_id)
    kit.need(result["job"] == SOURCE_JOB, "different official GNU source job")
    return result


def download(gh, expected, out):
    url = f"repos/{kit.REPO}/actions/artifacts/{expected['id']}/zip"
    hashed = hashlib.sha256()
    with subprocess.Popen([gh, "api", url], stdout=subprocess.PIPE) as proc:
        try:
            while data := proc.stdout.read(1 << 20):
                kit.need(out.tell() + len(data) <= expected["size"], "official archive too large")
                out.write(data)
                hashed.update(data)
        finally:
            proc.stdout.close()
        kit.need(proc.wait() == 0 and out.tell() == expected["size"], "incomplete official archive")
    kit.need(hashed.hexdigest() == expected["sha256"], "official archive digest mismatch")


def bind_media(raw, result):
    # Locally the original ZIP may already be the source author's read-only file.
    # Retain only the inner compressed tar in private RAM. No duplicate SDK or
    # decompressed tar is materialized in HOME or the native scratch reserve.
    expected = result["artifact"]
    raw.seek(0, os.SEEK_END)
    kit.need(raw.tell() == expected["size"], "different official media size")
    raw.seek(0)
    kit.need(hashlib.file_digest(raw, "sha256").hexdigest() == expected["sha256"], "different official media SHA")
    with zipfile.ZipFile(raw) as zipped, os.fdopen(os.memfd_create("rc22-inner-tar"), "w+b") as pack:
        entries = kit.zip_entries(zipped)
        data = {}
        members = {}
        for entry in entries:
            with zipped.open(entry) as src:
                if entry.filename == "kit.tar.zst":
                    h = hashlib.sha256()
                    while block := src.read(1 << 20):
                        h.update(block)
                        pack.write(block)
                    kit.need(pack.tell() == entry.file_size, "truncated compressed SDK")
                    members[entry.filename] = h.hexdigest()
                else:
                    content = src.read()
                    kit.need(len(content) == entry.file_size, "short source receipt")
                    data[entry.filename] = kit.strict_json(content)
                    members[entry.filename] = hashlib.sha256(content).hexdigest()
        receipt = data["receipt.json"]
        index = data["members.json"]
        kit.need(receipt["kit_sha256"] == members["kit.tar.zst"] and receipt["kit_bytes"] == pack.tell()
                 and receipt["members_sha256"] == members["members.json"], "source archive mismatch")
        reg, _ = kit.registration(receipt, index, result)
        pack.seek(0)
        kit.validate_tar(pack, index)
    return members, reg


def reader(gh, head):
    result = {}
    for name in READERS:
        path = "scripts/rc22-native/" + name
        row = canonical(gh, f"repos/{kit.REPO}/contents/{path}?ref={head}")
        kit.need(row["type"] == "file" and row["encoding"] == "base64" and row["path"] == path, "missing source reader")
        raw = base64.b64decode("".join(row["content"].split()), validate=True)
        oid = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        kit.need(0 < len(raw) == row["size"] <= 1 << 20 and oid == row["sha"], "source reader Git identity changed")
        result[name] = hashlib.sha256(raw).hexdigest()
    kit.need(result == READERS, "reviewed source reader hashes did not match")
    return result


def checked_anchor(path):
    a = kit.strict_json(path.read_bytes())
    kit.need(type(a) is dict and a.get("schema") == 1 and a.get("repository") == kit.REPO
             and a.get("branch") == BRANCH and a.get("attempt") == 1 and a.get("source_head") == SOURCE and a.get("run") == SOURCE_RUN and a.get("job") == SOURCE_JOB,
             "no source-complete enrolled native SDK")
    for n in ("job", "run", "repository_id", "workflow"):
        kit.need(type(a[n]) is int and a[n] > 0, "missing official " + n)
    artifact = a["artifact"]
    kit.need(artifact["name"] == ARTIFACT and type(artifact["id"]) is int and artifact["id"] > 0 and
             type(artifact["size"]) is int and 0 < artifact["size"] <= sum(kit.ZIP_LIMITS.values()) + (1 << 20)
             and kit.digest(artifact["sha256"]), "invalid GNU artifact enrollment")
    for key, names in (("members", kit.ZIP_LIMITS), ("reader", READERS)):
        kit.need(set(a[key]) == set(names) and all(kit.digest(v) for v in a[key].values()), "unbound " + key)
    kit.need(a["reader"] == READERS, "different reviewed SDK reader")
    r = a["registration"]
    kit.need(set(r) == {"rust","rustc","driver","wild","pinned","fixed"} and r["rust"] == kit.RUST[0]
             and kit.digest(r["rustc"]) and kit.digest(r["driver"]) and r["wild"] == kit.WILD,
             "unbound GNU runtime registration")
    for role, key in (("pinned", "pinned"), ("fourfix", "fixed")):
        c = r[key]
        kit.need((c["source"], c["tree"]) == kit.CARGO[role] and kit.digest(c["sha256"]), "unbound Cargo role")
    kit.need(r["pinned"]["sha256"] != r["fixed"]["sha256"], "Cargo roles are identical")
    return a


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gh", default="gh" if os.environ.get("GITHUB_ACTIONS") == "true" else "/home/dev-user/.local/bin/gh-auto")
    modes = p.add_subparsers(dest="mode", required=True)
    freeze = modes.add_parser("bind")
    freeze.add_argument("source_head")
    freeze.add_argument("run", type=int)
    freeze.add_argument("out", type=Path)
    freeze.add_argument("--zip", type=Path, help="Existing official ZIP, hashed before use")
    for mode in ("check", "get"):
        sub = modes.add_parser(mode)
        sub.add_argument("anchor", type=Path)
        sub.add_argument("out", type=Path)
    a = p.parse_args()
    if a.mode == "bind":
        result = official(a.gh, a.source_head, a.run)
        result["reader"] = reader(a.gh, a.source_head)
        # Reject a memory-short coordinator before materializing any compressed bytes.
        meminfo = Path("/proc/meminfo").read_text()
        free = int(re.search(r"^MemAvailable:\s+(\d+) kB$", meminfo, re.M)[1]) * 1024
        kit.need(free > (2 << 30) + result["artifact"]["size"] * (1 if a.zip else 2), "insufficient private RAM for enrollment")
        with a.zip.open("rb") if a.zip else os.fdopen(os.memfd_create("rc22-official-zip"), "w+b") as raw:
            if a.zip is None:
                download(a.gh, result["artifact"], raw)
            result["members"], result["registration"] = bind_media(raw, result)
        kit.save(a.out, result)
        checked_anchor(a.out)
    elif a.mode == "check":
        result = checked_anchor(a.anchor)
        live = official(a.gh, result["source_head"], result["run"])
        kit.need(all(result[k] == v for k, v in live.items()) and reader(a.gh, result["source_head"]) == result["reader"],
                 "official source no longer authenticates the reviewed binding")
        kit.save(a.out, live)
        print("source_head=" + result["source_head"])
        print("anchor_sha=" + kit.checksum(a.anchor))
    else:
        result = checked_anchor(a.anchor)
        with a.out.open("xb") as out:
            download(a.gh, result["artifact"], out)


if __name__ == "__main__":
    main()
