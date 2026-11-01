"""Bind exactly the two reviewed writer commits on the original 81-member corrected #301."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
P = "393b4b05a4bfa3f531a36023846f86236a6b71a9"
Q = "0db3ef0437fed86de99b68959abd1f65be9c82c2"
R = "7c0c305743727cb08e3c1de61183c9cb953d3f33"
REF = "refs/heads/charlie/qa-ruff-repair-tables-pilot-20261101"
QA = "762fc25095e317ac5632ec835df3c7f9cfc64a64"
HISTORICAL = "b1f863353a63c91bebf5d2bc2ca68a4aca93f6bb"
QA_PARENT = "6894b244568856bf0f30b5b155d8fb7f000c00c4"
REFUSED_RUNNER = "nsc-runner-q2lf6o1hf07tq"
PACK = "fc4c45fe401cfb23a63c3c7b9552502349a5b8ca71acea66447538bc13e029ab"
EXPECTED = {
    "compiler/rustc_incremental/src/persist/fs.rs",
    "compiler/rustc_incremental/src/persist/fs/packed.rs",
    "compiler/rustc_incremental/src/persist/fs/packed/tests.rs",
    "compiler/rustc_incremental/src/persist/fs/tests.rs",
    "compiler/rustc_incremental/src/persist/load.rs",
    "compiler/rustc_session/src/session.rs",
    "tests/run-make/ohm-packed-branch-cache/rmake.rs",
}


def need(ok, why):
    if not ok:
        raise ValueError(why)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(repo, *args, body=None):
    return subprocess.check_output(["git", "--no-lazy-fetch", "-C", repo, *args], input=body)


def identity(repo, ref):
    return git(repo, "rev-parse", ref).decode().strip()


def review_patch(repo, left, right):
    # Reproduce the reviewed sparse checkout's hunk labels even in a full Rust checkout.
    empty_tree = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    return git(repo, "--attr-source=" + empty_tree, "diff", "--full-index", "--binary", left, right, "--")


def check_sdk_sources(parent, candidate):
    original = json.loads((HERE / "inputs/original-E-source.json").read_bytes())
    need(
        parent["role"] == "E"
        and parent["source"] == original
        and original["role"]["commit"] == P
        and candidate["role"] == "R"
        and candidate["source"] == R,
        "wrong parent/child physical source",
    )


def checked(repo, *, install=False):
    enrolled = HERE / "inputs/product.json"
    need(
        sha(enrolled) == "61f7f6c49eaba6ecdd065f99f6a31e65e1910a9574e0b0a979a8ae5e091f4b84",
        "product enrollment changed",
    )
    data = json.loads(enrolled.read_bytes())
    pack = HERE / "inputs/writer.pack"
    need(
        not pack.is_symlink()
        and pack.stat().st_size == data["pack"]["bytes"] == 67747
        and sha(pack) == data["pack"]["sha256"] == PACK,
        "different compiler transport",
    )
    if install:
        git(repo, "index-pack", "--stdin", body=pack.read_bytes())
    need(
        [data["base"], data["previous"], data["head"]] == [P, Q, R]
        and identity(repo, R + "^") == Q
        and identity(repo, Q + "^") == P,
        "wrong product ancestry",
    )
    for key in ("HEAD^{tree}", "HEAD:compiler", "HEAD:tests", "HEAD:library", "HEAD:src/bootstrap"):
        need(identity(repo, key.replace("HEAD", R)) == data[key], "different " + key)
    need(
        all(
            identity(repo, P + ":" + k) == identity(repo, R + ":" + k)
            for k in (
                "library",
                "src/bootstrap",
                "src/stage0",
                "Cargo.lock",
                "compiler/rustc_interface/src/queries.rs",
                "compiler/rustc_incremental/src/persist/fs/packed/objects.rs",
            )
        ),
        "changed toolchain or object policy",
    )
    need(
        set(git(repo, "diff", "--name-only", P, R).decode().splitlines()) == set(data["blobs"]) == EXPECTED,
        "unreviewed source path",
    )
    for path, row in data["blobs"].items():
        for rev in (P, R):
            blob = row[rev]
            need(
                identity(repo, rev + ":" + path) == blob["git"]
                and hashlib.sha256(git(repo, "show", rev + ":" + path)).hexdigest() == blob["sha256"],
                path,
            )
    need(
        hashlib.sha256(review_patch(repo, P, R)).hexdigest() == data["patches"]["candidate-narrow.patch"],
        "full review patch differs",
    )
    return data


def official_job():
    need(
        os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and os.environ.get("GITHUB_REPOSITORY") == "astral-experiments/ohm"
        and os.environ.get("GITHUB_REF") == REF
        and os.environ.get("GITHUB_RUN_ATTEMPT") == "1"
        and os.environ.get("REVIEWED_HEAD") == os.environ["GITHUB_SHA"] == identity(HERE, "HEAD")
        and os.environ["RUNNER_NAME"] != REFUSED_RUNNER
        and os.environ.get("GITHUB_JOB") == "pilot",
        "wrong official QA job",
    )
    need(identity(HERE, "HEAD^") == QA_PARENT, "unreviewed carrier ancestry")


if __name__ == "__main__":
    print(json.dumps(checked(Path(sys.argv[1]))["pack"], sort_keys=True))
