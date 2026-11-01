"""Restore the checked E and CTFE C source-built SDKs at the ordinary worker's canonical path."""

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
C = "df2c077a113a709ab379c8ec34e62c94c7513325"
RUN, JOB = 41280518860, 124771325405
HEAD = "18b0cf251988b5967f8ffb0b11db850966eae9d1"
BRANCH = "charlie/qa-ctfe-literal-identity-20261101"
DRIVER = "lib/librustc_driver-c5276fb6f0cdddb4.so"
ARMS = ("Eon", "Con")
C_SDK_BYTES = 761639195
MANIFEST = {
    "E": "2f104fd6f02b2cf583a6b203e55cc17af4fbb9539398d915277cdfe2be9c0113",
    "C": "5c852dd08970b9762189eb1e1094df97bfba84bf06aea35e7db6e10530bcd701",
}
SOURCE_ARTIFACT = "ctfe-identity-source-and-driver"
RUFF_ARTIFACT = "ctfe-identity-ruff"
ARTIFACTS = {
    SOURCE_ARTIFACT: (13073575142, 45051721, "47d25435b57caaeab914fa637525eb59b99fa4e11f28ea245d035ceb0c483314"),
    RUFF_ARTIFACT: (13073252134, 46861589, "d6febdb3e3292615b26654da7f886a3aebe4daae31e14dac77e9dcc40319538b"),
}
# Literal file allowlist. The failed historical workload contributes only these two recorded SDK inventories.
MEMBERS = {
    SOURCE_ARTIFACT: {
        "C/native-qualified.json": (1880, "b8c98f135ec3dec38ce7f8913917f6bde711746d36709bdbe5831fd054ad5d58"),
        "C/overlay/manifest.json": (1041, MANIFEST["C"]),
        "C/overlay/0.zst": (5897387, "a9362da75ad14cc4306daab36f6bc3fc8b243e8367c2b28f7a6ea9514e6cc28e"),
        "C/overlay/1.zst": (39255688, "6f36891a6c7ba6d46a659a94a431360a44f177e3099b649ac20f9ed020679c3f"),
    },
    RUFF_ARTIFACT: {
        "sdk/E.json": (19767, "9e50ee7a36861db1b3493ffebaa83ed16d381499d31d145c8ffcced53ed1171f"),
        "sdk/C.json": (16322, "36591008b2645d7f2437f0e0b495b59e1273e7a4cb42433ff79735cb93b1b7d6"),
    },
}
UPLOAD = "Run actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
STEPS = {
    8: ("Reopen reviewed source and retained compiler verifier", "success"),
    9: ("Restore the immutable E SDK and verify sources", "success"),
    10: ("Build the exact compiler once and run native source and migration fixtures", "success"),
    11: ("Reproduce baseline and compare the exact ordinary Ruff AST edit to an independent empty build", "failure"),
    12: (UPLOAD, "success"),
    13: (UPLOAD, "success"),
}


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
        == (RUN, 1, HEAD, BRANCH, "workflow_dispatch", ".github/workflows/ci.yml", "completed", "failure")
        and run["repository"]["full_name"] == run["head_repository"]["full_name"] == REPO,
        "wrong original CTFE run or its recorded refusal",
    )
    require(
        (job["id"], job["run_id"], job["run_attempt"], job["head_sha"], job["head_branch"],
         job["name"], job["status"], job["conclusion"])
        == (JOB, RUN, 1, HEAD, BRANCH, "GNU compiler and ordinary Ruff allocation identity", "completed", "failure")
        and job["labels"] == ["namespace-profile-ubuntu-24-04-16"],
        "wrong original GNU source job",
    )
    steps = {s["number"]: (s["name"], s["conclusion"]) for s in job["steps"]}
    require(
        len(steps) == len(job["steps"])
        and all(s["status"] == "completed" for s in job["steps"])
        and {i: steps.get(i) for i in STEPS} == STEPS
        and {i for i, (_, verdict) in steps.items() if verdict == "failure"} == {11},
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
    return {"run": RUN, "head": HEAD, "job": JOB, "attempt": 1, "original_workflow": "failure",
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
    return json.loads((dest / "C/native-qualified.json").read_bytes())


def content(record):
    return {n: [v[0], v[4], v[3]] for n, v in record.items()}


def classify(donor, records, native):
    old, new = (records[r] for r in ("E", "C"))
    require(
        old["role"] == "E" and new["role"] == "C" and old["source"]["role"]["commit"] == E
        and new["source"] == C and native["old"] == E and native["new"] == C
        and native["qa"] == HEAD and native["run"] == str(RUN) and native["overlay"] == MANIFEST["C"]
        and old["driver"] == new["driver"] == native["driver"] == DRIVER,
        "foreign source, overlay or SDK reconstruction record",
    )
    old_files, new_files = content(old["files"]), content(new["files"])
    require(
        old_files == content(donor) and len(old_files) == 81 and old_files.keys() == new_files.keys()
        and {n for n in old_files if old_files[n] != new_files[n]} == {DRIVER, "bin/rustdoc"}
        and sum(v[1] for v in new_files.values()) == C_SDK_BYTES
        and old_files[DRIVER] == native["old_driver"] and new_files[DRIVER] == native["new_driver"],
        "previously authenticated E does not match source pair",
    )
    return new_files


def reconstruct(transfer, native, parent, e_dir, c_dir, b):
    """Rebuild the C SDK using the authenticated input pair and verify every physical member."""
    records = {r: json.loads((transfer / "sdk" / (r + ".json")).read_bytes()) for r in ("E", "C")}
    expected = classify(parent, records, native)
    subprocess.run(
        [sys.executable, "-IB", SCRIPTS / "gnu-ctfe-literal-identity/overlay.py", transfer / "C/overlay",
         transfer, e_dir, c_dir], check=True,
    )
    actual = b.inventory(c_dir)
    require(content(actual) == expected, "restored bytes, sizes or modes differ from C source SDK")
    identities = {tuple(v[1:3]) for v in actual.values()}
    require(len(identities) == 81 and identities.isdisjoint(tuple(v[1:3]) for v in parent.values()),
            "restored C shares an inode with E")
    b.verify_physical(e_dir, parent)
    return {**records["C"], "files": actual}


def acquire(source):
    """Authenticate official archives. Return only E and C with this host's physical file identities."""
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
    b.save(receipt / "ctfe-official.json", historical)
    # Newly retained files are the two ZIPs, six selected records and one 81-member SDK.
    needed = (sum(size for _, size, _ in ARTIFACTS.values())
              + sum(size for files in MEMBERS.values() for size, _ in files.values()) + C_SDK_BYTES)
    require(shutil.disk_usage(b.PARK).free >= needed + (5 << 30), "insufficient native evidence reserve")
    inbox = b.ROOT / "ctfe-originals"
    inbox.mkdir()
    # Same authenticated streaming downloader used for the E capsule on the worker.
    old.subjects.download(historical["artifacts"], inbox)
    transfer = b.ROOT / "ctfe-selected-inputs"
    native = unpack({key: inbox / (key + ".zip") for key in ARTIFACTS}, transfer)
    candidate = reconstruct(transfer, native, parent, b.PARK / "E", b.PARK / "C", b)
    b.save(receipt / "C.json", candidate)
    b.save(receipt / "ctfe-native-source.json", native)
    return {"E": parent, "C": candidate["files"]}


def activate(arm, rows, out):
    """Verify and move the chosen SDK to the fixed canonical path without changing its member inodes."""
    require(arm in ARMS and set(rows) == {"E", "C"}, "unknown CTFE role or missing SDK")
    return policy().b.activate(arm, rows, Path(out), permitted=ARMS, source_manifest=MANIFEST[arm[0]])
