"""Bind three independent product files to a real C3b commit and the exact #337 and C2 source trees."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

PARENT = "531eb1980c08c75ccbf3f6b77adbee53cd9b8bd5"
C2 = "4e546b27c311f29d99f9528e64420887f57c7538"
C2_TREE = "8086616a193235c75c09117f384fb4fa11673aad"
ORIGINAL_QA = "5b853a9f313227ce60ac43134a7070ef60bbca5b"
QA_BRANCH = "charlie/qa-ruff-placement-c3b-20261102"


def need(value, reason):
    if not value:
        raise ValueError(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(repo, *args):
    return subprocess.check_output(["git", "--no-optional-locks", "-C", repo, *args])


def revision(repo, name):
    return git(repo, "rev-parse", "--verify", name).decode().strip()


def sizes(repo, rev, names):
    objects = {}
    for name in names:
        rows = git(repo, "ls-tree", "-z", rev, "--", name).split(b"\0")
        if rows == [b""]:
            continue
        need(len(rows) == 2 and not rows[1], "ambiguous product path")
        line, path = rows[0].split(b"\t", 1)
        mode, kind, oid = line.decode().split()
        need(
            path == os.fsencode(name) and mode in ("100644", "100755") and kind == "blob",
            "unhandled product file mode or object",
        )
        content = git(repo, "cat-file", "blob", oid)
        need(0 < len(content) <= 4 << 20, "unbounded compiler file")
        objects[name] = {"blob": oid, "mode": mode, "bytes": len(content), "sha256": sha(content)}
    return objects


def shape(repo, candidate):
    need(
        re.fullmatch("[0-9a-f]{40}", candidate) and candidate not in (PARENT, C2),
        "requires a newly frozen physical C3b commit",
    )
    need(
        revision(repo, candidate + "^{commit}") == candidate
        and revision(repo, C2 + "^{tree}") == C2_TREE,
        "different immutable Rust source",
    )
    subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "-C",
            repo,
            "merge-base",
            "--is-ancestor",
            PARENT,
            candidate,
        ],
        check=True,
    )
    changes = git(repo, "diff", "--name-status", "--no-renames", "-z", C2, candidate, "--").split(
        b"\0"
    )
    need(
        changes[-1] == b"" and len(changes) == 7,
        "requires exactly the three independently supplied source bodies relative to C2",
    )
    names = {}
    for k in range(0, 6, 2):
        action, name = changes[k].decode(), os.fsdecode(changes[k + 1])
        need(
            action in ("A", "M")
            and re.fullmatch(r"compiler/[A-Za-z0-9_./-]+", name)
            and ".." not in Path(name).parts
            and name not in names,
            "unexpected source change",
        )
        names[name] = action
    history = (
        git(
            repo, "rev-list", "--reverse", "--ancestry-path", "--parents", PARENT + ".." + candidate
        )
        .decode()
        .splitlines()
    )
    current = PARENT
    for line in history:
        fields = line.split()
        need(len(fields) == 2 and fields[1] == current, "nonlinear or unbound Rust history")
        current = fields[0]
    need(current == candidate and 1 <= len(history) <= 5, "unexpected source history breadth")
    old, new = sizes(repo, C2, names), sizes(repo, candidate, names)
    need(
        set(new) == set(names) and set(old) == {n for n, s in names.items() if s == "M"},
        "different candidate/parent Git membership",
    )
    return {
        "schema": "source-placed-native-C3b-v1",
        "parent": PARENT,
        "parent_tree": revision(repo, PARENT + "^{tree}"),
        "C2": C2,
        "C2_tree": C2_TREE,
        "candidate": candidate,
        "candidate_tree": revision(repo, candidate + "^{tree}"),
        "candidate_compiler_tree": revision(repo, candidate + ":compiler"),
        "actual_history": history,
        "changes": names,
        "C2_files": old,
        "candidate_files": new,
        "original_C2_QA": ORIGINAL_QA,
    }


def bind_packet(result, paths):
    need(
        set(result["candidate_files"]) == set(paths) and len(paths) == 3,
        "packet must cover all actual changed files once",
    )
    for name, path in paths.items():
        st = path.lstat()
        spec = result["candidate_files"][name]
        need(
            stat.S_ISREG(st.st_mode)
            and st.st_size == spec["bytes"]
            and sha(path.read_bytes()) == spec["sha256"],
            f"independently supplied file differs from real commit: {name}",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("candidate")
    parser.add_argument("--packet-file", action="append", default=[], metavar="TRACKED_PATH=FILE")
    parser.add_argument("--expected", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    value = shape(args.repo, args.candidate)
    if args.packet_file:
        paths = {}
        for entry in args.packet_file:
            name, sep, f = entry.partition("=")
            need(sep and name not in paths, "missing or duplicate packet source")
            paths[name] = Path(f)
        bind_packet(value, paths)
    if args.expected:
        need(
            value == json.loads(args.expected.read_bytes()),
            "hosted full native commit, ancestry or three source bytes differ",
        )
    if args.out:
        need(args.packet_file and len(paths) == 3, "cannot mint a registration from Git alone")
        with args.out.open("x") as f:
            json.dump(value, f, sort_keys=True, indent=2)
            f.write("\n")
    print(
        value["candidate"],
        value["candidate_tree"],
        len(value["changes"]),
        sha(json.dumps(value, sort_keys=True).encode()),
    )
