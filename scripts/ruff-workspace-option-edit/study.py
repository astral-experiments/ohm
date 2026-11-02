"""Exact source pair, ordinary invocation and consumer output for Ruff #28106."""

import hashlib
import json
from pathlib import Path
import re
import subprocess
import textwrap

HERE = Path(__file__).resolve().parent
OLD = "3c77dcc2a5c04fc0c54ce95cd51068734015f3e0"
NEW = "088b7b5f77fcb05994fd2a17cbc940cd9edb341a"
REVISIONS = {"old": OLD, "new": NEW}
OPTIONS = "crates/ruff_workspace/src/options.rs"
SCHEMA = "ruff.schema.json"
LOCK = "1f4922d9d6d3b62933529c31ca20d89be37ac270"
PACKAGE_MANIFEST = "e00e01c3cc8c6a6546490f886e0cd4fdb6248972"
INPUTS = {
    OLD: (
        "f2fe5c3732836c20a084f17402208a010e0fe3bf",
        "a108f73f74397a14b900b40370a0af25fff8b235",
        "ad8f8b3e43edc7ff59914c0791ccf681080e1689",
    ),
    NEW: (
        "bc9e2b5888c92b5db4260af31d4bb03465bfae08",
        "95682b75b9dab18b50a32940d671fe622aca3c64",
        "ba99644ac8dc9b64db363cfd1f73affe2978b7de",
    ),
}
EXPECTED = {
    OLD: "e65047ba02433d991a48910c34462adfba4886f8c9e4eb3c2b48460b10cbde9e",
    NEW: "ccae78bb0fc82d54b4d0f1024bbb6ad9c811bc034f233ae58b9c4072742113bd",
}
KEY = "lint.per-file-ignores"
SIBLING = "lint.extend-per-file-ignores"
MISSING = "lint.ohm-study-absent-option"
OWNER = "ruff_workspace"
INVALID = b"\nconst OHM_OPTION_STUDY_INVALID: () = 1u32;\n"
BAD_CLIENT = (
    b"use ruff_workspace::options::Options;\nuse ruff_options_metadata::OptionsMetadata;\n"
    b"fn main() { let _: u32 = Options::metadata(); }\n"
)
CMD = [
    "cargo",
    "+ohm",
    "build",
    "-p",
    OWNER,
    "--lib",
    "--locked",
    "--offline",
    "-j4",
    "--message-format=json",
]
FLAG = "-Csave-temps=yes"
BRANCH = "charlie/qa-llvm-remat-source-20261102"
JOB = "Signed GNU Ruff workspace option edit"
HISTORIES = {
    "plain": ("old", "new", "unchanged", "invalid", "repair", "revert"),
    "observe": ("old", "new"),
    "capture": ("old", "new", "unchanged", "invalid", "repair", "revert"),
    "reference": ("new",),
    "capture-empty": ("new",),
    "owner": ("old", "new"),
}


# Dedicated same-path empty OLD and NEW reference, neither inherits Cargo or rustc products.
def fresh(lane, phase):
    return phase == "old" or lane in ("reference", "capture-empty")


def revision(phase):
    return OLD if phase in ("old", "revert") else NEW


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(repo, *args):
    return subprocess.check_output(["git", "--no-optional-locks", "-C", repo, *args])


def source_pair(repo):
    need(git(repo, "rev-parse", NEW + "^").decode().strip() == OLD, "not adjoining Ruff revisions")
    need(
        git(repo, "diff-tree", "--no-commit-id", "-r", "--name-only", OLD, NEW).decode().splitlines()
        == [OPTIONS, SCHEMA],
        "unrelated edit",
    )
    for rev, (tree, options, schema) in INPUTS.items():
        for name, expected in (
            ("^{tree}", tree),
            (":" + OPTIONS, options),
            (":" + SCHEMA, schema),
            (":Cargo.lock", LOCK),
            (":Cargo.toml", "2e809b607964dd98782025a6b63e281cbd11c278"),
            (":crates/ruff_workspace/Cargo.toml", PACKAGE_MANIFEST),
        ):
            need(git(repo, "rev-parse", rev + name).decode().strip() == expected, (rev, name, expected))
    texts = {v: git(repo, "show", v + ":" + OPTIONS).decode() for v in INPUTS}
    return {v: expected_outputs(v, source) for v, source in texts.items()}


def field(source, ident):
    """Read the two exact registered attributes and their preceding Rustdoc independently of Ruff."""
    lines = source.splitlines()
    hits = [i for i, s in enumerate(lines) if s.lstrip().startswith("pub " + ident + ":")]
    need(len(hits) == 1, ident)
    end = hits[0]
    attr = max(i for i in range(end) if lines[i].strip() == "#[option(")
    start = attr
    while start and lines[start - 1].lstrip().startswith("///"):
        start -= 1
    doc = "\n".join(s.lstrip().removeprefix("///").removeprefix(" ") for s in lines[start:attr])
    opts = "\n".join(lines[attr:end])

    def value(name):
        hits = re.findall(r"^\s*" + name + r' = "([^"\n]*)",?$', opts, re.M)
        need(len(hits) == 1, name)
        return hits[0]

    (example,) = re.findall(r'example = r#"\n([\s\S]+?)\n\s*"#', opts)
    return {
        "doc": doc,
        "default": value("default"),
        "value_type": value("value_type"),
        "scope": value("scope"),
        "example": textwrap.dedent(example),
        "deprecated": None,
    }


def formatted(f):
    return (
        f["doc"]
        + "\n\nDefault value: "
        + f["default"]
        + "\nType: "
        + f["value_type"]
        + "\nExample usage:\n```toml\n"
        + f["example"]
        + "\n```\n"
    ).encode()


def expected_outputs(rev, source):
    values = {key: formatted(field(source, key.split(".")[1].replace("-", "_"))) for key in (KEY, SIBLING)}
    need(
        sha(values[KEY]) == EXPECTED[rev],
        "source field differs from independent pre-enrolled native stdout",
    )
    return values


def source_state(repo, rev, invalid):
    options = git(repo, "show", rev + ":" + OPTIONS)
    schema = git(repo, "show", rev + ":" + SCHEMA)
    need(
        git(repo, "rev-parse", "HEAD").decode().strip() == OLD,
        "changed branch/checkout, expected ordinary working-tree edit",
    )
    need(
        (repo / OPTIONS).read_bytes() == options + (INVALID if invalid else b"")
        and (repo / SCHEMA).read_bytes() == schema,
        "incomplete option/schema edit",
    )
    changed = set(git(repo, "diff", "--name-only", "HEAD").decode().splitlines())
    need(changed == ({OPTIONS, SCHEMA} if rev == NEW else set()), ("unregistered source edit", changed))
    need(not git(repo, "ls-files", "--others", "--exclude-standard"), "untracked source inputs")
    return {
        "base": OLD,
        "effective": rev,
        "invalid": invalid,
        "paths": sorted(changed),
        "physical": {
            n: [
                (repo / n).stat().st_dev,
                (repo / n).stat().st_ino,
                (repo / n).stat().st_mtime_ns,
                (repo / n).stat().st_ctime_ns,
            ]
            for n in (OPTIONS, SCHEMA)
        },
        "options": sha((repo / OPTIONS).read_bytes()),
        "schema": sha(schema),
        "lock": LOCK,
    }


def write_source(repo, rev, invalid):
    for name in (OPTIONS, SCHEMA):
        path = repo / name
        body = git(repo, "show", rev + ":" + name) + (INVALID if invalid and name == OPTIONS else b"")
        need(path.is_file() and path.resolve(strict=True) == path, "unrelated worktree file")
        if path.read_bytes() != body:
            path.write_bytes(body)
    return source_state(repo, rev, invalid)


def results(rows, success):
    need(
        rows
        and rows[-1] == {"reason": "build-finished", "success": success}
        and sum(r["reason"] == "build-finished" for r in rows) == 1,
        "Cargo verdict",
    )
    errors = [r for r in rows if r["reason"] == "compiler-message" and r["message"]["level"] == "error"]
    if success:
        need(not errors, "successful build with an error")
    else:
        codes = [r for r in errors if r["message"].get("code")]
        need(
            len(codes) == 1
            and codes[0]["target"]["name"] == OWNER
            and codes[0]["message"]["code"]["code"] == "E0308",
            "wrong source diagnostic",
        )
        primary = [s for s in codes[0]["message"]["spans"] if s["is_primary"]]
        need(
            len(primary) == 1
            and primary[0]["file_name"].endswith(OPTIONS)
            and any(t["text"].strip() == INVALID.decode().strip() for t in primary[0]["text"]),
            "uncorroborated E0308",
        )
    return [r for r in rows if r["reason"] == "compiler-artifact"]


def artifact(products, owner):
    matches = [r for r in products if r["target"]["name"] == owner and r["target"]["kind"] == ["lib"]]
    need(len(matches) == 1, (owner, len(matches)))
    archives = [Path(n) for n in matches[0]["filenames"] if n.endswith(".rlib")]
    need(len(archives) == 1, (owner, archives))
    return archives[0]


def save(path, value):
    with path.open("x") as f:
        json.dump(value, f, sort_keys=True, separators=(",", ":"))
        f.write("\n")
