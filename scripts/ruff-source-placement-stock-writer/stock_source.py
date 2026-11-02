"""Bind one reviewed source successor of the real, guarded C3b compiler."""

from hashlib import sha1, sha256
import json
import os
from pathlib import Path
import re
import subprocess

PARENT = "531eb1980c08c75ccbf3f6b77adbee53cd9b8bd5"
GUARDED = "ed0262f9bdc384576925229764971f23a141c95f"
GUARDED_TREE = "d4a6f3ab70185bec03263086863376298c293360"
CPP = "compiler/rustc_llvm/llvm-wrapper/OhmSourcePlacement.cpp"
SELECTED = "a77736dfe65c89b92ff6f316f56a31cf54efb60a6480011a9e7954f520fef077"
PATCH = "e70edbb822ab1a0d153d6fdb6cc3fe197f6224a39156e7669ed7ebf287284fe3"
ATTESTATION = "f9e7fc214254bae5b272c62bf3d3ed8775f228b0e1e0f8f9b6d364a79473b3ab"
BRANCH = "charlie/qa-ruff-placement-stock-writer-20261102"
GUARDED_DIR = Path(__file__).resolve().parent.parent / "ruff-source-placement-c3b"
UNCHANGED = (
    "src/llvm-project",
    "src/tools/cargo",
    "src/librustdoc",
    "src/bootstrap",
    "library",
    "x.py",
)


def need(condition, message):
    if not condition:
        raise ValueError(message)


def git(repo, *args):
    return subprocess.check_output(
        ["git", "--no-optional-locks", "-C", str(repo), *args],
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"},
    )


def oid(repo, ref):
    return git(repo, "rev-parse", "--verify", ref).decode().strip()


def shape(repo, selected, reviewed):
    need(re.fullmatch(r"[0-9a-f]{40}", selected), "an actual full product commit is required")
    need(
        git(repo, "rev-list", "--parents", "-n1", selected).decode().split() == [selected, GUARDED],
        "the selected product is not the real direct guarded compiler successor",
    )
    need(oid(repo, GUARDED + "^{tree}") == GUARDED_TREE, "different guarded source tree")
    need(
        reviewed.get(CPP) == SELECTED
        and all(re.fullmatch(r"[0-9a-f]{64}", s) for s in reviewed.values()),
        "different selected and independently reviewed source",
    )
    actual = git(
        repo,
        "diff-tree",
        "--no-commit-id",
        "--no-renames",
        "-r",
        "--name-only",
        "-z",
        GUARDED,
        selected,
    )
    paths = [os.fsdecode(x) for x in actual.split(b"\0") if x]
    need(sorted(reviewed) == sorted(paths), "unobserved or missing compiler source file")
    bodies = {}
    for path in paths:
        need(
            re.fullmatch(r"compiler/[a-zA-Z0-9_./-]+", path) and ".." not in Path(path).parts,
            "non-compiler source change",
        )
        pair = {}
        for role, rev in (("guarded", GUARDED), ("selected", selected)):
            raw = git(repo, "ls-tree", "-z", rev, "--", path)
            if not raw and role == "guarded":
                pair[role] = None
                continue
            mode, kind, rest = raw.rstrip(b"\0").split(b" ", 2)
            blob, name = rest.split(b"\t", 1)
            need(
                mode == b"100644" and kind == b"blob" and os.fsdecode(name) == path,
                "unexpected source mode",
            )
            data = git(repo, "cat-file", "blob", blob.decode())
            need(0 < len(data) < 4 << 20, "unbounded compiler source body")
            git_blob = sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            need(
                git_blob == blob.decode(),
                "actual source bytes do not reproduce the original Git object",
            )
            pair[role] = {
                "blob": blob.decode(),
                "bytes": len(data),
                "sha256": sha256(data).hexdigest(),
            }
        need(
            pair["selected"]["sha256"] == reviewed[path],
            "unexpected independently reviewed source bytes",
        )
        bodies[path] = pair
    stable = {}
    for path in UNCHANGED:
        left, right = (oid(repo, rev + ":" + path) for rev in (GUARDED, selected))
        need(left == right, "different Cargo, LLVM, std, rustdoc, or bootstrap")
        stable[path] = left
    return {
        "schema": "explicit-stock-b3-source-1",
        "base": GUARDED,
        "base_tree": GUARDED_TREE,
        "subject": selected,
        "tree": oid(repo, selected + "^{tree}"),
        "compiler": oid(repo, selected + ":compiler"),
        "reviewed_sha256": reviewed,
        "physical_files": bodies,
        "unchanged": stable,
    }


def bundle_header(data, selected):
    need(0 < len(data) < 4 << 20, "unbounded incremental source bundle")
    header, sep, pack = data.partition(b"\n\n")
    need(sep and pack.startswith(b"PACK"), "missing complete native Git pack")
    lines = header.decode("utf-8").splitlines()
    need(lines.pop(0) in ("# v2 git bundle", "# v3 git bundle"), "not an original Git bundle")
    if lines and lines[0] == "@object-format=sha1":
        lines.pop(0)
    need(
        len(lines) == 2 and lines[0].split(" ", 1)[0] == "-" + GUARDED,
        "wrong or multiple bundle prerequisite",
    )
    target, ref = lines[1].split(" ", 1)
    need(
        target == selected
        and (ref == "HEAD" or re.fullmatch(r"refs/heads/charlie/[a-zA-Z0-9_./-]+", ref)),
        "unregistered source bundle head",
    )
    return {
        "sha256": sha256(data).hexdigest(),
        "bytes": len(data),
        "branch": ref,
        "prerequisite": GUARDED,
    }


def binding(here):
    candidate = json.loads((here / "source-packet.json").read_bytes())
    registration = json.loads((here / "registration.json").read_bytes())
    expected = json.loads((here / "protocol.json").read_bytes())
    original = (here / "root-source-attestation.json").read_bytes()
    need(sha256(original).hexdigest() == ATTESTATION, "different independently reopened source")
    proof = json.loads(original)
    need(
        proof["head"] == candidate["subject"]
        and proof["tree"] == candidate["tree"]
        and proof["parent"] == GUARDED
        and proof["bundle"] == registration["bundle"]["sha256"]
        and proof["patch"] == PATCH
        and proof["blobs"] == candidate["reviewed_sha256"]
        and len(proof["blobs"]) == 6,
        "physical patch, bundle or six compiler files disagree with the independent review",
    )
    need(
        registration["roles"]["C"]
        == {
            "revision": candidate["subject"],
            "tree": candidate["tree"],
            "compiler": candidate["compiler"],
        }
        and registration["roles"]["P"]["revision"] == PARENT
        and expected["source"] == candidate["subject"]
        and candidate["reviewed_sha256"][CPP] == SELECTED
        and candidate["base"] == GUARDED,
        "source registration differs from the complete reviewed compiler",
    )
    return candidate, registration
