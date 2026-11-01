"""Versioned source and native semantic contract for the unchanged, ordinary Ruff CLI argv."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess

HERE = Path(__file__).resolve().parent
REFERENCE = json.loads((HERE / "stub-reference.json").read_bytes())
SOURCE = REFERENCE["source"].encode()
AST = "crates/ruff_python_ast/src/lib.rs"
PARSER = "crates/ruff_python_parser/src/lib.rs"
BEFORE = "712c897ad642964bb8526dcb13d97bb1917add11cb627e894b738c6f4affa428"
AFTER = "cb988a3c7709f0a5cb184ceb5776f67f527f0c458d8b5111f9595d448f12f06b"
GOOD = "ee24a1933840a400c4730778a5c222d30c36d4b1b4f96bd97b502acfc07a4875"
BAD = "3fbac7f54be2b5cd47eee1993f11e6d58724e32301c0ba3e5afb624562283ab5"
INVALID = b"\nconst ohm_branch_switch_invalid: () = 1u32;\n"
OLD, NEW = b'"pyi" => Self::Stub,', b'"pyi" => Self::Python,'
REVS = {"A": "b5dba861cc38e3f7fb4524c9ceba3e01a474ea13", "B": "7b13f01ba1569887a25670820764b24c206da8e5"}
TREES = {"A": "2b61306d708a211b3725c8d920e7590be6da41ad", "B": "97ca36909f1ae8fa028b2c1f48f452fbdcdbbd4c"}
NAMES = {"A": "historical-parent", "B": "historical-feature"}
PHASES = ("Y-B", "X-A", "X-B", "edit", "repeat", "invalid", "repair", "revert", "empty-edit")
EDITED = {"edit", "repeat", "invalid", "repair", "empty-edit"}
LINKED = {"edit", "revert"}
COLD = {"Y-B", "empty-edit"}
CASES = {
    "pyi": ("pyi", ()),
    "py": ("py", ()),
    "qno": ("qno", ()),
    "qno-as-pyi": ("qno", ("--extension", "qno:pyi")),
    "pyi-as-py": ("pyi", ("--extension", "pyi:python")),
}
GRAPH = "f5909e1cbd4832369f783bdbd733e54562bcce15e44592b8ec15793e9996c660"
WILD = "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
WILD_SHA = "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"


def need(condition, reason):
    if not condition:
        raise ValueError(str(reason))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def argv(case):
    ext, options = CASES[case]
    return [
        "check",
        "--isolated",
        "--no-cache",
        "--select",
        "PYI009",
        "--output-format",
        "json",
        "--stdin-filename",
        "dev_loop." + ext,
        *options,
        "-",
    ]


def verdict(case, edited, actual, stdout, stderr, cwd):
    warning = case == "qno-as-pyi" or (case == "pyi" and not edited)
    expected = (
        [REFERENCE["diagnostic"] | {"filename": str(PurePosixPath(cwd) / ("dev_loop." + CASES[case][0]))}]
        if warning
        else []
    )
    need(
        type(actual) is int and actual == int(warning) and stderr == b"" and json.loads(stdout) == expected,
        ("wrong native PYI009 verdict", case, edited, actual, stdout[:300], stderr[:200]),
    )
    return [actual, sha(stdout), sha(stderr)]


def altered(raw):
    changed = raw.replace(OLD, NEW)
    need(sha(raw) == BEFORE and raw.count(OLD) == 1 and sha(changed) == AFTER, "unregistered Ruff edit")
    return changed


def git(repo, *args):
    return subprocess.check_output(["git", "--no-optional-locks", "-C", repo, *args])


def advance(repo, phase):
    need(phase in PHASES, "unknown phase")
    if phase == "X-A":
        git(repo, "switch", "--quiet", NAMES["A"])
    elif phase == "X-B":
        git(repo, "merge", "--ff-only", "--no-edit", NAMES["B"])
    elif phase in ("edit", "empty-edit"):
        if phase == "edit":
            git(repo, "switch", "--quiet", NAMES["B"])
        file = repo / AST
        file.write_bytes(altered(file.read_bytes()))
    elif phase == "invalid":
        file = repo / PARSER
        body = file.read_bytes()
        need(sha(body) == GOOD and sha(body + INVALID) == BAD, "wrong parser fault")
        file.write_bytes(body + INVALID)
    elif phase in ("repair", "revert"):
        path = PARSER if phase == "repair" else AST
        need(
            sha((repo / path).read_bytes()) == (BAD if phase == "repair" else AFTER),
            "unknown state before restore",
        )
        git(repo, "restore", "--worktree", "--", path)


def source_state(phase):
    branch = "A" if phase == "X-A" else "B"
    ref = NAMES["A"] if phase in ("X-A", "X-B") else NAMES["B"]
    modified = sorted(([AST] if phase in EDITED else []) + ([PARSER] if phase == "invalid" else []))
    return dict(
        branch=branch,
        ref=ref,
        revision=REVS[branch],
        tree=TREES[branch],
        modified=modified,
        ast=AFTER if phase in EDITED else BEFORE,
        parser=BAD if phase == "invalid" else GOOD,
    )


def snapshot(repo, phase):
    want = source_state(phase)
    need(
        git(repo, "rev-parse", "HEAD").decode().strip() == want["revision"]
        and git(repo, "rev-parse", "HEAD^{tree}").decode().strip() == want["tree"]
        and git(repo, "symbolic-ref", "--short", "HEAD").decode().strip() == want["ref"]
        and git(repo, "status", "--porcelain=v1")
        == b"".join(b" M " + p.encode() + b"\n" for p in want["modified"]),
        ("wrong complete source/branch", phase),
    )
    need(
        sha((repo / AST).read_bytes()) == want["ast"] and sha((repo / PARSER).read_bytes()) == want["parser"],
        "source bytes differ",
    )
    watched = {}
    for f in ("HEAD", "refs/heads/" + want["ref"]):
        p = repo / ".git" / f
        s = p.lstat()
        need(p.is_file() and not p.is_symlink(), "unbound watched Git input")
        watched[f] = [s.st_dev, s.st_ino, s.st_ctime_ns, s.st_mtime_ns, sha(p.read_bytes())]
    return want | {"watched": watched}


def check_source(receipt, phase):
    want = source_state(phase)
    need(receipt == want | {"watched": receipt["watched"]}, "unexpected source record")
    head = "refs/heads/" + want["ref"]
    files = {"HEAD": sha(("ref: " + head + "\n").encode()), head: sha((want["revision"] + "\n").encode())}
    need(
        set(files) == set(receipt["watched"])
        and all(
            len(v) == 5 and v[-1] == files[k] and all(type(i) is int and i > 0 for i in v[:4])
            for k, v in receipt["watched"].items()
        ),
        "wrong watched Git bytes",
    )


def roots(env, base):
    target, build = (PurePosixPath(env[key]) for key in ("CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR"))
    need(
        base.is_absolute()
        and target == base / "work/target"
        and build == base / "work/build"
        and env["CARGO_ENCODED_RUSTFLAGS"] == "-Zohm-branch-cache=yes"
        and env["CARGO_NET_OFFLINE"] == "true",
        "wrong or overlapping Cargo roots",
    )
    need(
        str(target) == env["CARGO_TARGET_DIR"] and str(build) == env["CARGO_BUILD_BUILD_DIR"],
        "noncanonical output spelling",
    )
    return target, build


def physical_roots(paths, *, empty):
    found = {}
    for value in paths:
        path = Path(value)
        if not empty and not path.exists() and not path.is_symlink():
            continue
        st = path.lstat()
        need(
            path.is_dir() and not path.is_symlink() and path.resolve() == path and not path.is_mount(),
            "foreign output directory",
        )
        need(not empty or not any(path.iterdir()), "nonempty independent output root")
        found[str(path)] = [st.st_dev, st.st_ino]
    need(
        len(set(map(str, paths))) == 2 and len({tuple(v) for v in found.values()}) == len(found),
        "physically overlapping output roots",
    )
    return found


def require_same_output(reported, linked, expected_sha):
    need(
        reported.resolve(strict=True) == reported
        and linked.resolve(strict=True) == linked
        and reported.samefile(linked),
        "stock linker wrote a different physical file",
    )
    with linked.open("rb") as artifact:
        need(hashlib.file_digest(artifact, "sha256").hexdigest() == expected_sha, "wrong complete linked CLI")


def flag(argv, name):
    values = [argv[i + 1] for i in range(len(argv) - 1) if argv[i] == name]
    need(len(values) == 1, ("missing/ambiguous native operand", name))
    return values[0]


def link_rows(rustcs, wilds, cli, sdk, phase):
    bins = [r for r in rustcs if r["crate"] == "ruff" and flag(r["argv"], "--crate-type") == "bin"]
    need(len(bins) == 1 and bins[0]["mode"] in ("full", "link-only"), "missing actual CLI compiler")
    r = bins[0]
    output = str(PurePosixPath(flag(r["argv"], "--out-dir")) / "ruff")
    need(
        r["exe"] == r["argv"][0] == str(sdk / "bin/rustc")
        and flag(r["argv"], "--crate-name") == "ruff"
        and PurePosixPath(cli) == sdk.parents[3] / "work/target/debug/ruff",
        "wrong compiler or reported CLI",
    )
    need(
        PurePosixPath(output).name == PurePosixPath(cli).name == "ruff"
        and any(PurePosixPath(output).is_relative_to(sdk.parents[3] / "work" / r) for r in ("build", "target")),
        "foreign Wild output",
    )
    need(
        ".." not in PurePosixPath(output).parts and str(PurePosixPath(output)) == output,
        "noncanonical linker output",
    )
    matches = [w for w in wilds if w["output"] == output]
    need(
        len(matches) == 1
        and matches[0]["exe"] == matches[0]["argv"][0] == str(sdk / WILD)
        and flag(matches[0]["argv"], "-o") == output,
        "missing unique actual stock Wild writer",
    )
    if phase == "edit":
        need(
            any(
                e["exe"] == str(sdk / "bin/rustc") and e["crate"] == "ruff_python_ast" and e["mode"] == "full"
                for e in rustcs
            ),
            "genuine changed AST compiler missing",
        )
    return r, matches[0]
