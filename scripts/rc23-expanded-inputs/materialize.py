"""Reconstruct the release's four pinned, composite Git checkouts on an empty host."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REG = json.loads((HERE / "registration.json").read_bytes())
NAMES = ("rust", "cargo", "clippy", "rustfmt")


def need(value, why):
    if not value:
        raise ValueError(str(why))


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")


def git(repo, *args):
    return subprocess.check_output(["git", "-C", repo, *args], text=True).strip()


def checkout(path, expected):
    need(
        path.is_dir()
        and not path.is_symlink()
        and Path(git(path, "rev-parse", "--show-toplevel")).samefile(path)
        and git(path, "rev-parse", "HEAD") == expected,
        ("wrong checkout", path, expected),
    )
    need(not git(path, "status", "--porcelain", "--untracked-files=no"), ("modified tracked source", path))


def index(repo, packet, spec):
    with packet.open("rb", buffering=0) as stream:
        header = stream.read(12)
        need(
            header[:4] == b"PACK"
            and int.from_bytes(header[4:8], "big") in (2, 3)
            and int.from_bytes(header[8:], "big") == spec["objects"]
            and packet.stat().st_size == spec["bytes"]
            and sha(packet) == spec["sha256"],
            ("different source transport", packet),
        )
        stream.seek(0)
        subprocess.run(["git", "-C", repo, "index-pack", "--strict", "--stdin"], stdin=stream, check=True)


def verify_tail(repo, tail):
    need(git(repo, "rev-parse", tail["from"] + "^{tree}") == tail["from_tree"], "different tail base tree")
    need(
        git(repo, "rev-list", tail["commit"], "^" + tail["from"]).splitlines()
        == [r[0] for r in tail["chain"]],
        "unexpected tail commits",
    )
    for commit, parent, tree in tail["chain"]:
        need(
            git(repo, "rev-parse", commit + "^", commit + "^{tree}").splitlines() == [parent, tree],
            ("different parent or tree", commit),
        )


def verify_files(repo, tail):
    need(
        git(repo, "rev-parse", "HEAD", "HEAD^{tree}").splitlines() == [tail["commit"], tail["tree"]],
        "wrong final checkout",
    )
    changed = git(repo, "diff", "--name-only", tail["from"], "HEAD").splitlines()
    need(changed == sorted(tail["paths"].keys() | tail["gitlinks"].keys()), "different tail paths")
    for name, oid in tail["paths"].items():
        p = repo / name
        need(
            p.is_file() and not p.is_symlink() and git(repo, "hash-object", "--no-filters", p) == oid,
            ("different source", name),
        )
    for name, oid in tail["gitlinks"].items():
        need(
            git(repo, "ls-tree", "HEAD", "--", name) == "160000 commit " + oid + "\t" + name
            and git(repo / name, "rev-parse", "HEAD") == oid,
            ("different nested source", name),
        )


def verify_layout(rust, layout):
    tail, sources = REG["rust_tail"], REG["sources"]
    verify_files(rust, tail)
    verify_files(rust / "src/tools/cargo", REG["cargo_tail"])
    required = {
        "compiler/rustc_middle/src/dep_graph/serialized.rs": "006bc1a676dc34e3ba5a32f4aaf3fa6c3a55a7ed",
        "tests/run-make/incremental-missing-query-cache/rmake.rs": "bb5da6413f2f97b33414d61679a2ea6a9bde5ffc",
        "src/tools/cargo/tests/testsuite/ohm_ready_tests.rs": "4eb3367c71899fd1e1e22cd42e2683ebe4664f6b",
    }
    for name, oid in required.items():
        need(
            git(rust, "hash-object", "--no-filters", rust / name) == oid,
            ("changed native regression source", name),
        )
    need(
        sha(rust / "src/tools/cargo/tests/testsuite/ohm_ready_tests.rs") == sha(HERE / "ohm_ready_tests.rs"),
        "terminal fixture differs from Cargo's real source",
    )
    for path, key in (
        ("compiler", "compiler"),
        ("library", "library"),
        ("tests", "tests"),
        ("src/bootstrap", "bootstrap"),
        ("src/tools/rustc-perf", "rustc-perf"),
        *((f"src/tools/{n}", n) for n in NAMES[1:]),
    ):
        need(git(rust, "rev-parse", "HEAD:" + path) == REG["native_subtrees"][key], path)
    substitutions = {"src/tools/" + n: (sources[n]["end"], sources[n]["tree"]) for n in ("clippy", "rustfmt")}
    composite = layout.checked(rust, tail["commit"], tail["tree"], substitutions)
    status = layout.git(
        rust, "status", "--porcelain", "-z", "--untracked-files=no", "--ignore-submodules=all"
    )
    observed = {os.fsdecode(row[3:]) for row in status.split(b"\0")[:-1]}
    expected = {p for p, (old, _) in composite["authorized_differences"].items() if old}
    need(observed == expected, ("unexpected outer source paths", sorted(observed ^ expected)))
    need(composite["gitlinks"]["src/tools/cargo"]["tree"] == REG["cargo_tail"]["tree"], "foreign Cargo tree")
    composite["native_regression_inputs"] = required
    return composite


def materialize(workspace, rust, out):
    need(
        workspace == Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
        and rust == workspace / "source/rust"
        and not rust.parent.exists(),
        "expected fresh source root",
    )
    checkout(workspace, REG["coordinator"])
    legacy = workspace / "legacy"
    checkout(legacy, REG["legacy"])
    checkout(workspace / "qa-cross", REG["cross"])
    for name, commit in REG["seeds"].items():
        checkout(legacy / name, commit)
    cross = workspace / "qa-cross/scripts/rc23-cross-qualification"
    need(
        sha(cross / "protocol.json") == REG["cross_protocol"]
        and json.loads((cross / "protocol.json").read_bytes())["sources"] == REG["sources"],
        "foreign transport",
    )
    manifest = workspace / "toolchains/1.99.0/23.json"
    need(sha(manifest) == REG["manifest"], "wrong release manifest bytes")
    stage = legacy / "source"
    need(not stage.exists(), "historical seed directory exists")
    sys.path.insert(0, str(legacy / "scripts/dep-graph-slots"))
    import qualify
    import layout

    sys.path.insert(0, str(legacy / "scripts/integrated-dist-qa"))
    import sources

    # Reconstruct the previous kit under its own immutable coordinator. It creates
    # its own old 23.json. The real coordinator and its new manifest are untouched.
    try:
        os.environ["GITHUB_WORKSPACE"] = str(legacy)
        sources.prepare(legacy)
        qualify.install_source(legacy, stage / "rust", stage / "reports")
        qualify.verify_live(stage / "rust")
    finally:
        os.environ["GITHUB_WORKSPACE"] = str(workspace)
    stage.rename(rust.parent)
    repos = {"rust": rust, **{n: rust / "src/tools" / n for n in NAMES[1:]}}
    specs, tail = REG["sources"], REG["rust_tail"]
    for name, repo in repos.items():
        spec = specs[name]
        need(git(repo, "rev-parse", "HEAD") == spec["base"], ("different precursor", name))
        index(repo, cross / (name + ".pack"), spec)
        need(git(repo, "rev-parse", spec["end"] + "^{tree}") == spec["tree"], name)
    for name in ("rust", "cargo"):
        delta = REG[name + "_tail"]
        git(repos[name], "merge-base", "--is-ancestor", delta["from"], specs[name]["end"])
        index(repos[name], HERE / (name + "-tail.pack"), delta)
        verify_tail(repos[name], delta)
    # Restore the outer repository's tracked tool subtrees before switching Rust,
    # while keeping each complete release tool checkout independently intact.
    for name in ("clippy", "rustfmt"):
        repos[name].rename(rust.parent / ("expanded-donor-" + name))
    git(rust, "restore", "--source=HEAD", "--worktree", "--", "src/tools/clippy", "src/tools/rustfmt")
    git(rust, "checkout", "--no-recurse-submodules", "--quiet", "--detach", tail["commit"])
    for name in ("clippy", "rustfmt"):
        repos[name].rename(rust.parent / ("expanded-original-" + name))
        (rust.parent / ("expanded-donor-" + name)).rename(repos[name])
    for name in NAMES[1:]:
        commit = REG["cargo_tail"]["commit"] if name == "cargo" else specs[name]["end"]
        git(repos[name], "checkout", "--no-recurse-submodules", "--quiet", "--detach", commit)
    complete = verify_layout(rust, layout)
    revisions = {n: git(repo, "rev-parse", "HEAD") for n, repo in repos.items()}
    need(
        {n: r["revision"] for n, r in json.loads(manifest.read_bytes())["sources"].items()} == revisions,
        "source/manifest revisions differ",
    )
    verified = subprocess.run(
        [workspace / "scripts/verify-release-sources.sh", manifest, *repos.values()],
        check=True,
        capture_output=True,
        text=True,
    )
    save(
        out,
        {
            "coordinator": REG["coordinator"],
            "source": revisions,
            "layout": complete,
            "epoch": REG["epoch"],
            "native_subtrees": REG["native_subtrees"],
            "cross": REG["cross"],
            "rust_tail": tail,
            "cargo_tail": REG["cargo_tail"],
            "manifest_sha256": sha(manifest),
            "source_verifier": verified.stdout,
            "qa": os.environ["GITHUB_SHA"],
            "run": os.environ["GITHUB_RUN_ID"],
            "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
            "job": os.environ["GITHUB_JOB"],
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("workspace", "rust", "out"):
        p.add_argument("--" + key, type=Path, required=True)
    a = p.parse_args()
    materialize(a.workspace.resolve(strict=True), a.rust.absolute(), a.out.absolute())
