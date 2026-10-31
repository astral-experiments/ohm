"""Authenticate the real #28233 edit on Ruff's enrolled A and the archived, already-built A CLI."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

A = "b5dba861cc38e3f7fb4524c9ceba3e01a474ea13"
B = "7b13f01ba1569887a25670820764b24c206da8e5"
EDIT = "0ecff877901a0377ad966ffab528488ce872b50e"
PARENT = "1edf9fe2cab23e34c383419b8c7830324c428a58"
CHANGE_SHA = "8f5df0673081205c8aac262563e3bd2d174e264b6b643e16ad1ddc424a017ba5"
ARCHIVE_SHA = "99c8caed1c871739262b2a8496ff375a05c8cf1215b176a24b7b7095e8521315"
CLI_SHA = "37e119a61caf20043894fd99718fa4d156cbc95457790235e736c1c33819e61d"
DIR = "crates/ruff_python_parser/"
PATHS = (
    DIR + "resources/inline/err/signed_pattern_non_literal_operand.py",
    DIR + "src/parser/pattern.rs",
    DIR + "tests/snapshots/invalid_syntax@signed_pattern_non_literal_operand.py.snap",
)
BAD = b"match value:\n    case -1**2: ...\n"
GOOD = b"match value:\n    case -1: ...\n"
ARGS = [
    "check",
    "--no-cache",
    "--isolated",
    "--ignore",
    "ALL",
    "--target-version",
    "py315",
    "--output-format=json",
    "--stdin-filename",
    "match.py",
    "-",
]
WARNING = b"warning: Support for Python 3.15 is under development and may be unstable. Enable `preview` to remove this warning.\n"


def h(data):
    return hashlib.sha256(data).hexdigest()


def need(b, reason):
    if not b:
        raise ValueError(reason)


def git(repo, *args, check=True, data=None):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=check, input=data
    )


def original_patch(repo):
    need(
        git(repo, "rev-parse", EDIT + "^").stdout.decode().strip() == PARENT,
        "wrong historical parent",
    )
    delta = git(
        repo, "show", "--format=", "--no-ext-diff", "--binary", "--no-renames", "--full-index", EDIT
    ).stdout
    need(h(delta) == CHANGE_SHA, "different complete public patch")
    files = git(repo, "diff", "--name-only", PARENT, EDIT).stdout.decode().splitlines()
    need(tuple(files) == PATHS, "different affected paths")
    return delta


def source_check(repo):
    patch = original_patch(repo)
    observed = {}
    with tempfile.TemporaryDirectory() as area:
        root = Path(area)
        for rel in PATHS:
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            body = git(repo, "show", A + ":" + rel).stdout
            need(
                body
                == git(repo, "show", EDIT + ":" + rel).stdout
                == git(repo, "show", B + ":" + rel).stdout,
                "current historical fixture drifted",
            )
            path.write_bytes(body)
            observed[rel] = {"A": h(body)}
        git(root, "apply", "--reverse", "--check", "-", data=patch)
        git(root, "apply", "--reverse", "-", data=patch)
        for rel in PATHS:
            p = root / rel
            parent = git(repo, "show", PARENT + ":" + rel, check=False)
            if parent.returncode == 0:
                need(
                    p.read_bytes() == parent.stdout, "inverse failed to restore the original bytes"
                )
            else:
                need(not p.exists() and rel != PATHS[1], "wrong removed historical fixture")
            observed[rel]["reversed"] = h(p.read_bytes()) if p.exists() else None
        git(root, "apply", "--check", "-", data=patch)
        git(root, "apply", "-", data=patch)
        need(
            all(h((root / rel).read_bytes()) == s["A"] for rel, s in observed.items()),
            "repair changed A",
        )
    return {
        "A": A,
        "B": B,
        "edit": EDIT,
        "parent": PARENT,
        "complete_patch_sha256": h(patch),
        "edits": observed,
        "source_only": True,
    }


def oracle(executable, directory, expects_bug, *, pass_fds=()):
    rows = {}
    for label, body in (("case", BAD), ("neighbor", GOOD)):
        p = subprocess.run(
            [executable, *ARGS],
            cwd=directory,
            env={"PATH": "/usr/bin:/bin", "HOME": str(directory), "LANG": "C.UTF-8"},
            pass_fds=pass_fds,
            input=body,
            capture_output=True,
        )
        msgs = json.loads(p.stdout)
        bad = label == "case" and not expects_bug
        need(
            p.returncode == int(bad) and p.stderr == WARNING,
            (label, p.returncode, p.stdout.decode(), p.stderr.decode()),
        )
        if bad:
            need(
                len(msgs) == 1
                and msgs[0]["code"] == "invalid-syntax"
                and msgs[0]["message"] == "Expected a numeric literal after unary operator"
                and msgs[0]["filename"] == str(Path(directory) / "match.py")
                and msgs[0]["location"] == {"row": 2, "column": 11}
                and msgs[0]["end_location"] == {"row": 2, "column": 15},
                ("wrong native parser diagnostic", msgs, directory),
            )
        else:
            need(msgs == [], "unexpected valid/known-bug diagnostic")
        rows[label] = {
            "stdin": body.decode(),
            "exit": p.returncode,
            "stdout": p.stdout.decode(),
            "stderr": p.stderr.decode(),
        }
    return rows


def archived_control(path):
    with path.open("rb") as f:
        need(
            hashlib.file_digest(f, "sha256").hexdigest() == ARCHIVE_SHA,
            "unregistered official artifact",
        )
    with zipfile.ZipFile(path) as z:
        m = json.loads(gzip.decompress(z.read("cold-A/native.json.gz")))
        need(m["source"] == A and m["cli"]["whole"] == CLI_SHA, "different enrolled binary")
        fd = os.memfd_create("first-session-real-Ruff-A", os.MFD_CLOEXEC)
        try:
            subprocess.run(
                ["zstd", "-dq"],
                input=z.read("native-bodies/" + CLI_SHA + ".zst"),
                stdout=fd,
                check=True,
            )
            os.lseek(fd, 0, 0)
            with os.fdopen(os.dup(fd), "rb") as f:
                need(
                    hashlib.file_digest(f, "sha256").hexdigest() == CLI_SHA, "physical ELF differs"
                )
            os.fchmod(fd, 0o500)
            with tempfile.TemporaryDirectory() as tmp:
                got = oracle(f"/proc/self/fd/{fd}", tmp, False, pass_fds=(fd,))
                try:
                    oracle(f"/proc/self/fd/{fd}", tmp, True, pass_fds=(fd,))
                except ValueError:
                    pass
                else:
                    raise ValueError("correct binary passed the opposite behavior gate")
        finally:
            os.close(fd)
    return {
        "run": 41221390896,
        "artifact": 13050556244,
        "zip_sha256": ARCHIVE_SHA,
        "A_ELF": CLI_SHA,
        "argv": ARGS,
        "observed": got,
        "wrong_role_refused": True,
        "real_reversed_tree_not_built_here": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--out", type=Path)
    opts = parser.parse_args()
    out = source_check(opts.repo)
    if opts.archive:
        out["positive_control"] = archived_control(opts.archive)
    text = json.dumps(out, sort_keys=True, indent=2) + "\n"
    if opts.out:
        with opts.out.open("x") as target:
            target.write(text)
    else:
        print(text, end="")
