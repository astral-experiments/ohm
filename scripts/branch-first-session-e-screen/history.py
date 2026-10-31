"""The private measurement checkout carries a reproducible same-branch parser commit."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from same_branch import A, B, CHANGE_SHA, PATHS, need

HERE = Path(__file__).resolve().parent
MESSAGE = b"Replay the complete inverse of Ruff #28233 on the historical A branch\n"
IDENTITY = {
    "GIT_AUTHOR_NAME": "Ohm QA",
    "GIT_COMMITTER_NAME": "Ohm QA",
    "GIT_AUTHOR_EMAIL": "qa@localhost",
    "GIT_COMMITTER_EMAIL": "qa@localhost",
    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
}
EDITED = "7b40d968cd60dfabc8c36fc8437e7a583fff3fd1"
TREE = "81d2fc20d496700e98c7efb86f4b036cd1a5f8c8"


def command(repo, args, *, data=None, env=None):
    return subprocess.run(
        ["git", "-C", repo, *args], input=data, capture_output=True, check=True, env=env
    ).stdout


def construct(repo, patch, *, verify=True):
    if hashlib.sha256(patch).hexdigest() != CHANGE_SHA:
        raise ValueError("different public patch")
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(
            os.environ,
            **IDENTITY,
            GIT_INDEX_FILE=str(Path(tmp) / "index"),
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
        )
        command(repo, ["read-tree", A], env=env)
        command(repo, ["apply", "--cached", "--reverse", "--check", "-"], data=patch, env=env)
        command(repo, ["apply", "--cached", "--reverse", "-"], data=patch, env=env)
        tree = command(repo, ["write-tree"], env=env).decode().strip()
        edited = (
            command(repo, ["commit-tree", tree, "-p", A], data=MESSAGE, env=env).decode().strip()
        )
    if verify:
        need(
            (edited, tree) == (EDITED, TREE),
            "different synthetic commit/tree at actual historical A",
        )
    files = command(repo, ["diff", "--name-only", A, edited]).decode().splitlines()
    need(tuple(files) == PATHS, "unexpected modified Ruff sources")
    official = json.loads((HERE / "inputs/ruff-28233.json").read_bytes())["edits"]
    for rev, expected_key in ((A, "A"), (B, "A"), (edited, "reversed")):
        for name in PATHS:
            expected = official[name][expected_key]
            p = subprocess.run(["git", "-C", repo, "show", rev + ":" + name], capture_output=True)
            need(
                (expected is None and p.returncode == 128 and not p.stdout)
                or (
                    expected is not None
                    and p.returncode == 0
                    and hashlib.sha256(p.stdout).hexdigest() == expected
                ),
                (rev, name, "historic source mismatch"),
            )
    return edited, tree


def watched(repo, current):
    active = command(repo, ["symbolic-ref", "HEAD"]).decode().strip()
    need(active == "refs/heads/" + current, "different Git branch")
    rows = {}
    for name in ("HEAD", active):
        path = repo / ".git" / name
        st = path.lstat()
        need(path.is_file() and not path.is_symlink(), "missing actual watched ref")
        rows[name] = [
            st.st_dev,
            st.st_ino,
            st.st_mtime_ns,
            st.st_ctime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        ]
    return rows


def reset_inactive(repo, names):
    need(
        command(repo, ["symbolic-ref", "HEAD"]).decode().strip() == "refs/heads/" + names["B"],
        "only restore the inactive private historical A ref",
    )
    command(repo, ["update-ref", "refs/heads/" + names["A"], A, EDITED])


def select(repo, names, state, phase, out):
    active = names["B" if state == "B" else "A"]
    if phase in {"same-cold-A", "same-empty-edit"}:
        command(repo, ["switch", "-q", names["A"]])
        need(
            command(repo, ["rev-parse", "HEAD"]).decode().strip() == A,
            "did not start from genuine A",
        )
    if phase in {"same-edit", "same-empty-edit"}:
        need(
            command(repo, ["symbolic-ref", "HEAD"]).decode().strip() == "refs/heads/" + names["A"],
            "edit moved to a different branch",
        )
        command(repo, ["merge", "--no-edit", "--ff-only", EDITED])
    if phase == "same-first-B":
        command(repo, ["switch", "-q", names["B"]])
    rev = {"A": A, "B": B, "A-edit": EDITED}[state]
    need(
        command(repo, ["rev-parse", "HEAD"]).decode().strip() == rev
        and not command(repo, ["status", "--porcelain"]),
        "unexpected post-edit source tree",
    )
    rows = watched(repo, active)
    if phase == "same-repeat":
        old = json.loads((out.parent / "same-edit/source.json").read_bytes())
        need(old["watched"] == rows, "same-branch repeat rewrote recorded Git inputs")
    return {
        "commit": rev,
        "tree": command(repo, ["rev-parse", "HEAD^{tree}"]).decode().strip(),
        "branch": "refs/heads/" + active,
        "watched": rows,
    }
