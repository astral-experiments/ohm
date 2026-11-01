"""Restore the checked E and D same-revision source-built SDKs at the ordinary worker's canonical path."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import zipfile


HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
REPO = "astral-experiments/ohm"
SOURCE_CHECKOUT = "762fc25095e317ac5632ec835df3c7f9cfc64a64"
E = "393b4b05a4bfa3f531a36023846f86236a6b71a9"
D = "d95494a6a63c22222806c06e3d3aa0de504d8e8a"
RUN, JOB = 41303656721, 124839568474
HEAD = "8f633d8fc21e453f4c81d81588b6dcab125bfeae"
BRANCH = "charlie/qa-ruff-same-revision-donor-source-20261101"
DRIVER = "lib/librustc_driver-c5276fb6f0cdddb4.so"
ARMS = ("Eon", "Don")
D_SDK_BYTES = 761611819
MANIFEST = {"E": "2f104fd6f02b2cf583a6b203e55cc17af4fbb9539398d915277cdfe2be9c0113",
            "D": "5afab54e76787132fa7773d0ede79745dbb858e7870eb89f0d039428f8626981"}
SOURCE_ARTIFACT = "same-revision-donor-source-and-driver"
RUFF_ARTIFACT = "same-revision-donor-sdk-and-resources"
SOURCE_BINDING = Path(__file__).resolve().parent / "enrollment" / "donor-source.json"
bound = json.loads(SOURCE_BINDING.read_bytes())
ARTIFACTS = {name: tuple(row) for name, row in bound["archives"].items()}
MEMBERS = bound["members"]
STEPS = {int(n): tuple(row) for n, row in bound["steps"].items()}
def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def policy():
    # Our entrypoint deliberately has a distinct module identity from the predecessor's subjects.py.
    directory = SCRIPTS / "branch-storage-e-confirmation"
    sys.path.insert(0, str(directory))
    try:
        import policy as old
    finally:
        sys.path.remove(str(directory))
    require(
        Path(old.__file__).resolve() == directory / "policy.py"
        and Path(old.subjects.__file__).resolve() == SCRIPTS / "branch-first-session-e-screen/subjects.py"
        and Path(old.b.__file__).resolve() == SCRIPTS / "branch-return-pmu/bindings.py",
        "unexpected original SDK/intake module",
    )
    return old


def official(run, job, artifacts):
    require(
        (run["id"], run["run_attempt"], run["head_sha"], run["head_branch"], run["event"], run["path"],
         run["status"], run["conclusion"])
        == (RUN, 1, HEAD, BRANCH, "workflow_dispatch", ".github/workflows/ci.yml", "completed", "success")
        and run["repository"]["full_name"] == run["head_repository"]["full_name"] == REPO,
        "wrong original CTFE run or scope",
    )
    require(
        (job["id"], job["run_id"], job["run_attempt"], job["head_sha"], job["head_branch"],
         job["name"], job["status"], job["conclusion"])
        == (JOB, RUN, 1, HEAD, BRANCH, "Build and qualify the exact GNU same-revision selector", "completed", "success")
        and job["labels"] == ["namespace-profile-ubuntu-24-04-16"],
        "wrong original GNU source job",
    )
    steps = {s["number"]: (s["name"], s["conclusion"]) for s in job["steps"]}
    require(
        len(steps) == len(job["steps"])
        and all(s["status"] == "completed" for s in job["steps"])
        and {i: steps.get(i) for i in STEPS} == STEPS
        and {i for i, (_, verdict) in steps.items() if verdict == "failure"} == set(),
        "wrong native qualification or original failed Ruff step",
    )
    entries = artifacts["artifacts"]
    require(artifacts["total_count"] == len(entries) == len(ARTIFACTS)
            and {a["name"] for a in entries} == set(ARTIFACTS), "unexpected artifact set")
    out = {}
    for a in entries:
        key = a["name"]
        n, size, digest = ARTIFACTS[key]
        origin = a["workflow_run"]
        require(
            (a["id"], a["size_in_bytes"], a["digest"], a["expired"]) == (n, size, "sha256:" + digest, False)
            and (origin["id"], origin["head_sha"], origin["head_branch"]) == (RUN, HEAD, BRANCH)
            and origin["repository_id"] == origin["head_repository_id"] == run["repository"]["id"],
            "wrong original source artifact " + key,
        )
        out[key] = {"id": n, "size_in_bytes": size, "digest": a["digest"]}
    return {"run": RUN, "head": HEAD, "job": JOB, "attempt": 1, "original_workflow": "success",
            "original_steps": STEPS, "artifacts": out}


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def unpack(archives, dest):
    """Copy only pinned regular files from complete, checksum-verified original ZIPs."""
    require(set(archives) == set(ARTIFACTS), "missing original archive")
    dest.mkdir()
    for key, path in archives.items():
        _, size, digest = ARTIFACTS[key]
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == size
                and sha(path) == digest, "wrong raw ZIP " + key)
        with zipfile.ZipFile(path) as z:
            require(len(z.namelist()) == len(set(z.namelist())), "duplicate raw ZIP name")
            for name, (length, expected) in MEMBERS[key].items():
                entry = z.getinfo(name)
                require(entry.file_size == length and stat.S_ISREG(entry.external_attr >> 16),
                        "unexpected source archive member " + name)
                out = dest / name
                out.parent.mkdir(parents=True, exist_ok=True)
                with z.open(entry) as src, out.open("xb") as target:
                    shutil.copyfileobj(src, target, 1 << 20)
                require(out.stat().st_size == length and sha(out) == expected, "wrong bytes of " + name)
    return json.loads((dest / "D/native-qualified.json").read_bytes())


def content(record):
    return {n: [v[0], v[4], v[3]] for n, v in record.items()}


def classify(donor, records, native):
    old, new = (records[r] for r in ("E", "D"))
    require(
        old["role"] == "E" and new["role"] == "D" and old["source"]["role"]["commit"] == E
        and new["source"] == D and native["old"] == E and native["new"] == D
        and native["qa"] == HEAD and native["run"] == str(RUN) and native["overlay"] == MANIFEST["D"]
        and old["driver"] == new["driver"] == native["driver"] == DRIVER,
        "foreign source, overlay or SDK reconstruction record",
    )
    old_files, new_files = content(old["files"]), content(new["files"])
    require(
        old_files == content(donor) and len(old_files) == 81 and old_files.keys() == new_files.keys()
        and {n for n in old_files if old_files[n] != new_files[n]} == {DRIVER}
        and sum(v[1] for v in new_files.values()) == D_SDK_BYTES
        and old_files[DRIVER] == native["old_driver"] and new_files[DRIVER] == native["new_driver"],
        "previously authenticated E does not match source pair",
    )
    return new_files


def reconstruct(transfer, native, parent, e_dir, c_dir, b):
    """Rebuild the D SDK using the authenticated input pair and verify every physical member."""
    records = {r: json.loads((transfer / "sdk" / (r + ".json")).read_bytes()) for r in ("E", "D")}
    measured = json.loads((transfer / "independent-ruff.json").read_bytes())
    source = json.loads((transfer / "source-qualified.json").read_bytes())
    require(measured == bound["native_reader"] and measured["qualified"] and source["qualified"]
            and measured["source"] == [E, D] and source["source"] == [E, D, native["tree"]]
            and source["physical_installation_reopened"] and source["overlay"] == MANIFEST["D"],
            "different independently qualified native source or 37-artifact study")
    expected = classify(parent, records, native)
    subprocess.run(
        [sys.executable, "-IB", SCRIPTS / "gnu-same-revision-donor/overlay.py", transfer / "D/overlay",
         transfer, e_dir, c_dir], check=True,
    )
    actual = b.inventory(c_dir)
    require(content(actual) == expected, "restored bytes, sizes or modes differ from D source SDK")
    identities = {tuple(v[1:3]) for v in actual.values()}
    require(len(identities) == 81 and identities.isdisjoint(tuple(v[1:3]) for v in parent.values()),
            "restored D shares an inode with E")
    b.verify_physical(e_dir, parent)
    return {**records["D"], "files": actual}


def acquire(source):
    """Authenticate official archives. Return only E and D with this host's physical file identities."""
    source = Path(source).resolve(strict=True)
    old = policy()
    b = old.b
    require(b.git(source, "rev-parse", "HEAD") == SOURCE_CHECKOUT and not b.PARK.exists(),
            "wrong parent source checkout or nonempty SDK root")
    require(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_REPOSITORY") == REPO,
            "online source acquisition requires the read-only Actions job")
    gh = "gh"
    def api(suffix):
        return json.loads(subprocess.check_output([gh, "api", "repos/" + REPO + "/actions/" + suffix], cwd=HERE))
    historical = official(api(f"runs/{RUN}"), api(f"jobs/{JOB}"), api(f"runs/{RUN}/artifacts?per_page=100"))
    prior = old.checked_source.enrollment()
    require(prior["qualified"]["manifest"] == MANIFEST["E"] and prior["qualified"]["source"] == E,
            "unexpected qualified parent source or manifest")
    old.checked_source.official(api, prior)
    parent = old.acquire(source)["E"]
    receipt = b.OUT / "sdk"
    b.save(receipt / "donor-official.json", historical)
    # Newly retained files are the two ZIPs, six selected records and one 81-member SDK.
    needed = (sum(size for _, size, _ in ARTIFACTS.values())
              + sum(size for files in MEMBERS.values() for size, _ in files.values()) + D_SDK_BYTES)
    require(shutil.disk_usage(b.PARK).free >= needed + (5 << 30), "insufficient native evidence reserve")
    inbox = b.ROOT / "donor-originals"
    inbox.mkdir()
    # Same authenticated streaming downloader used for the E capsule on the worker.
    old.subjects.download(historical["artifacts"], inbox)
    transfer = b.ROOT / "donor-selected-inputs"
    native = unpack({key: inbox / (key + ".zip") for key in ARTIFACTS}, transfer)
    candidate = reconstruct(transfer, native, parent, b.PARK / "E", b.PARK / "D", b)
    b.save(receipt / "D.json", candidate)
    b.save(receipt / "donor-native-source.json", native)
    return {"E": parent, "D": candidate["files"]}


def activate(arm, rows, out):
    """Verify and move the chosen SDK to the fixed canonical path without changing its member inodes."""
    require(arm in ARMS and set(rows) == {"E", "D"}, "unknown donor role or missing SDK")
    return policy().b.activate(arm, rows, Path(out), permitted=ARMS, source_manifest=MANIFEST[arm[0]])
