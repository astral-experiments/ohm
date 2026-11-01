"""Bind the bounded Git reader on its qualified parent to the enrolled Git object closure and the reviewed QA run."""

from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ORIGINAL = "393b4b05a4bfa3f531a36023846f86236a6b71a9"
OLD = "d95494a6a63c22222806c06e3d3aa0de504d8e8a"
DONOR_QA = "a333316177ef3f9c8b3264ca3bf76c451e0ca079"
CARRIER_PARENT = "830181f5024dee093d5d5e92b47255988379d071"
SOURCE_QA = "762fc25095e317ac5632ec835df3c7f9cfc64a64"
REF = "refs/heads/charlie/qa-rust-fast-packed-ref-source-v2-20261101"
EXPECTED = {
    "compiler/rustc_incremental/src/persist/fs.rs",
    "compiler/rustc_incremental/src/persist/fs/tests.rs",
}
UNITS = (
    "test_all_except_most_recent",
    "test_timestamp_serialization",
    "test_find_source_directory_in_iter",
    "checkout_sessions_prefer_a_match_and_keep_one_alternate",
    "pack_only_on_checkout_switch",
    "prefer_the_newest_session_at_the_same_revision",
    "resolve_revisions_in_a_linked_git_worktree",
    "resolve_complete_rows_at_the_start_of_large_packed_refs",
)
RUN_MAKE = (
    "ohm-packed-branch-cache",
    "ohm-branch-cache-opt-out",
    "incremental-missing-query-cache",
)
RUN_MAKE_TREES = dict(
    zip(
        RUN_MAKE,
        (
            "06d96af3b998b53c49bc703209d46f969225b0a3",
            "1d1544a1690d9c9e641b6d584fd6d258269be35b",
            "ebb70623534f1cb53f9b0f5f8ad23788d198aee4",
        ),
        strict=True,
    )
)
COMPONENTS = (
    "compiler",
    "library",
    "tests",
    "Cargo.lock",
    "src",
    "src/bootstrap",
    "src/stage0",
    "src/llvm-project",
    "src/tools/cargo",
    "src/tools/run-make-support",
)
# freeze.py writes the complete immutable source ID, tree and receipt SHA before enrollment.
sys.path.insert(0, str(HERE))
from source_ids import NEW, TREE, SOURCE_RECEIPT


def need(condition, why):
    if not condition:
        raise ValueError(why)


def digest(body):
    return hashlib.sha256(body).hexdigest()


def sha(path):
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def git(repo, *args, body=None):
    return subprocess.check_output(
        ["git", "-C", repo, *args],
        input=body,
        env=os.environ | {"GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": "file"},
    )


def rev(repo, name):
    return git(repo, "rev-parse", name).decode().strip()


def save(path, result):
    with Path(path).open("x") as file:
        file.write(json.dumps(result, indent=2, sort_keys=True) + "\n")


def job():
    header = git(HERE, "cat-file", "commit", "HEAD").split(b"\n\n", 1)[0]
    parents = [line[7:].decode() for line in header.splitlines() if line.startswith(b"parent ")]
    need(
        os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and os.environ.get("GITHUB_REPOSITORY") == "astral-experiments/ohm"
        and os.environ.get("GITHUB_REF") == REF
        and os.environ.get("GITHUB_RUN_ATTEMPT") == "1"
        and os.environ.get("GITHUB_JOB") == "qualify"
        and os.environ.get("REVIEWED_HEAD") == os.environ["GITHUB_SHA"] == rev(HERE, "HEAD")
        and parents == [CARRIER_PARENT],
        "foreign QA source or invocation",
    )


def inspect_source(repo):
    need(
        re.fullmatch(r"[0-9a-f]{40}", NEW)
        and rev(repo, NEW + "^{tree}") == TREE
        and git(repo, "rev-list", "--parents", "-1", NEW).decode().split() == [NEW, OLD],
        "foreign source tree or parents",
    )
    changes = set(git(repo, "diff", "--no-renames", "--name-only", OLD, NEW).decode().splitlines())
    need(changes == EXPECTED, ("unexpected source scope", changes))
    blobs = {}
    for name in sorted(changes):
        blobs[name] = {}
        for role, revision in (("parent", OLD), ("candidate", NEW)):
            oid = rev(repo, revision + ":" + name)
            blobs[name][role] = [oid, digest(git(repo, "cat-file", "blob", oid))]
    comps = {name: rev(repo, NEW + ":" + name) for name in COMPONENTS}
    need(
        all(
            oid == rev(repo, OLD + ":" + name) for name, oid in comps.items() if name != "compiler"
        ),
        "changed bootstrap, library, test framework, or Cargo",
    )
    patch = git(
        repo,
        "--attr-source=4b825dc642cb6eb9a060e54bf8d69288fbee4904",
        "diff",
        "--full-index",
        "--binary",
        OLD,
        NEW,
    )
    names = sorted(
        line.split()[0]
        for line in git(repo, "rev-list", "--objects", NEW, "^" + OLD).decode().splitlines()
    )
    return dict(
        parent=OLD,
        child=NEW,
        tree=TREE,
        pack_objects=names,
        patch_sha256=digest(patch),
        components=comps,
        blobs=blobs,
    )


def validate(repo, install=False):
    src = HERE / "inputs/product.json"
    pack = HERE / "inputs/child.pack"
    need(sha(src) == SOURCE_RECEIPT, "foreign product receipt")
    data = json.loads(src.read_bytes())
    need(
        data["pack"]
        == {
            "sha256": sha(pack),
            "bytes": pack.stat().st_size,
            "count": len(data["source"]["pack_objects"]),
        }
        and 0 < pack.stat().st_size < 256 * 1024,
        "invalid Git object transport",
    )
    if install:
        git(repo, "index-pack", "--stdin", body=pack.read_bytes())
    need(
        all(
            rev(repo, NEW + ":tests/run-make/" + case) == ref
            for case, ref in RUN_MAKE_TREES.items()
        ),
        "changed real packed, opt-out or cache-recovery run-make",
    )
    need(inspect_source(repo) == data["source"], "original source object or component mismatch")
    return data


if __name__ == "__main__":
    print(json.dumps(validate(Path(sys.argv[1]))["pack"], sort_keys=True))
