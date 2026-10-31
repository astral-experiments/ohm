"""Seal and reconstruct only the reviewed, one-parent Linux compiler source above the genuine K."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / "branch-return-source"
sys.path.insert(0, str(OLD))
import registration as reg
sys.path.insert(0, str(HERE))
import selector_record

K = "0afbeff303d3658bff52582d8f1a996d59e6c8ce"
SOURCE = "caef389ed580829583f1a63df129b7b649e43508"
REF = "refs/heads/charlie/qa-branch-first-session-e-source-20261031"
LEGACY = {
    "scripts/branch-return-source": "0740766c294f8170885165a4143910c576b6a296",
    "scripts/ohm-packed-ruff": "d9fd6c8e4152d468a3a40d600ee1c6ebda13e5f2",
    "scripts/ohm-apple-zmij/source-transport": "02af0c56f52d8270882348903e4d89275620b8aa",
}


K_ORIGIN = json.loads((HERE / "inputs/k-origin.json").read_bytes())
need = reg.need
sha = reg.sha


def names_for(commit):
    control = json.loads((HERE / "inputs/required-tests.json").read_bytes())
    need(control["policy"] == "first-git-session-tables" and control["commit"] == commit
         and re.fullmatch("[0-9a-f]{40}", commit), "first-session source and tests await enrollment")
    need(isinstance(control["rustc_incremental"], list)
         and isinstance(control["additional_run_make"], list)
         and isinstance(control["changed_files"], dict) and control["changed_files"],
         "missing reviewed first-session source, tests and paths")
    return control


def required_tests(commit):
    return set(names_for(commit)["rustc_incremental"])


def inherited():
    checkout = HERE.parents[1]
    for path, tree in LEGACY.items():
        need(
            reg.rev(checkout, "HEAD:" + path) == tree
            and not reg.git(checkout, "status", "--porcelain", "--", path),
            "foreign historical source " + path,
        )
    need(
        K_ORIGIN["head"] == SOURCE
        and K_ORIGIN["run"] == 41199659076
        and K_ORIGIN["manifest"] == "c29e2e57626491804d9c24e5fa50a709015a002067a3bf39e884d8b6ef0fea43"
        and reg.SOURCE()["roles"]["K"]["commit"] == K,
        "wrong native K enrollment",
    )


def ident(repo, commit):
    return dict(
        commit=reg.rev(repo, commit + "^{commit}"),
        tree=reg.rev(repo, commit + "^{tree}"),
        **{
            p: reg.rev(repo, commit + ":" + p)
            for p in ("compiler", "library", "tests", "src/bootstrap")
        },
    )


def validate(s):
    need(
        isinstance(s, dict)
        and s.get("parent") == K
        and s.get("policy") == "first-git-session-tables"
        and set(s)
        == {
            "parent",
            "role",
            "pack",
            "delta",
            "additional_linux_units",
            "additional_run_make",
            "policy",
        },
        "E source not enrolled",
    )
    r = s["role"]
    need(
        set(r) == {"commit", "tree", "compiler", "library", "tests", "src/bootstrap"}
        and all(re.fullmatch("[0-9a-f]{40}", x) for x in r.values())
        and r["commit"] != K,
        "invalid candidate trees",
    )
    need(
        r["library"] == reg.SOURCE()["roles"]["K"]["library"]
        and r["compiler"] != reg.SOURCE()["roles"]["K"]["compiler"],
        "wrong library or unchanged compiler",
    )
    p = s["pack"]
    need(
        set(p) == {"bytes", "sha256"}
        and 0 < p["bytes"] <= 2**20
        and re.fullmatch("[0-9a-f]{64}", p["sha256"]),
        "invalid E source transport",
    )
    units = s["additional_linux_units"]
    make = s["additional_run_make"]
    need(
        isinstance(units, dict)
        and required_tests(r["commit"]) == set(units.get("rustc_incremental", [])),
        "required first-session tests absent",
    )
    need(
        set(units) == {"rustc_incremental", "rustc_fs_util"}
        and all(
            isinstance(v, list)
            and len(v) == len(set(v))
            and all(re.fullmatch(r"(?:[a-zA-Z0-9_]+::)+[a-zA-Z0-9_]+", n) for n in v)
            for v in units.values()
        ),
        "unnamed or duplicate Linux test",
    )
    need(
        isinstance(make, list)
        and len(make) == len(set(make))
        and all(re.fullmatch(r"[a-z0-9][a-z0-9-]+", n) for n in make),
        "invalid run-make",
    )
    delta = s["delta"]
    need(
        set(delta) == {"raw_sha256", "rows"} and re.fullmatch("[0-9a-f]{64}", delta["raw_sha256"]),
        "unverified source delta",
    )
    paths = [row["path"] for row in delta["rows"]]
    need(
        all(not PurePosixPath(p).is_absolute() and ".." not in PurePosixPath(p).parts for p in paths),
        "unsafe source path",
    )
    need(
        len(paths) == 4 and set(paths) == {
            "compiler/rustc_incremental/src/persist/fs.rs",
            "compiler/rustc_interface/src/queries.rs",
            "compiler/rustc_session/src/session.rs",
            "tests/run-make/ohm-packed-branch-cache/rmake.rs",
        },
        "unreviewed source scope",
    )
    need(
        bool(sum(units.values(), []) or make or any(p.startswith("tests/run-make/") for p in paths)),
        "no new source-bound qualification",
    )
    controls = names_for(r["commit"])
    actual = {row["path"]: row["new"]["sha256"] if row["new"] else None for row in delta["rows"]}
    need(actual == controls["changed_files"], "expected all and only the reviewed source and test bytes")
    need(set(make) == set(controls["additional_run_make"]),
         "wrong first-session run-make registration")
    return s


def load():
    inherited()
    selector_record.signed()
    candidate = validate(json.loads((HERE / "inputs/subject.json").read_bytes())["candidate"])
    pack = HERE / "inputs/E.pack"
    need(pack.is_file() and not pack.is_symlink() and pack.stat().st_size == candidate["pack"]["bytes"]
         and sha(pack) == candidate["pack"]["sha256"], "missing or changed E source pack")
    return candidate


def verify(repo, s, install=False):
    s = validate(s)
    r = s["role"]
    p = HERE / "inputs/E.pack"
    if install:
        need(
            p.is_file()
            and not p.is_symlink()
            and p.stat().st_size == s["pack"]["bytes"]
            and sha(p) == s["pack"]["sha256"],
            "foreign candidate pack",
        )
        reg.git(repo, "index-pack", "--stdin", data=p.read_bytes())
    need(
        ident(repo, r["commit"]) == r
        and reg.git(repo, "rev-list", "--parents", "-1", r["commit"]).decode().split()
        == [r["commit"], K],
        "not the exact registered one-parent E",
    )
    need(
        reg.rev(repo, K + ":src/bootstrap") == r["src/bootstrap"]
        and reg.identity_delta(repo, K, r["commit"]) == s["delta"],
        "foreign bootstrap, mode, content or source path",
    )
    return s


def verify_pack(repo, parent, commit, payload):
    expected = {
        line.split()[0]
        for line in reg.git(repo, "rev-list", "--objects", commit, "^" + parent).splitlines()
    }
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp) / "check.git"
        subprocess.run(["git", "init", "--bare", "--quiet", store], check=True)
        reg.git(store, "index-pack", "--stdin", data=payload)
        (index,) = (store / "objects/pack").glob("*.idx")
        held = {
            line.split()[0]
            for line in reg.git(store, "verify-pack", "-v", str(index)).splitlines()
            if re.match(rb"^[0-9a-f]{40} (commit|tree|blob) ", line)
        }
        need(
            expected == held,
            "pack does not independently contain exactly the registered child-only objects",
        )
    return len(expected)


def seal(repo, commit, linux_tests, pack, out):
    """Take the supplied bounded pack or export just E minus the known K, without writing the Rust repo."""
    l = ident(repo, commit)
    need(
        l["commit"] == commit
        and reg.git(repo, "rev-list", "--parents", "-1", commit).decode().split() == [commit, K],
        "need a literal direct K child",
    )
    payload = (
        pack.read_bytes()
        if pack
        else reg.git(
            repo,
            "-c",
            "pack.threads=1",
            "pack-objects",
            "--stdout",
            "--revs",
            "--no-reuse-object",
            "--no-reuse-delta",
            data=f"{commit}\n^{K}\n".encode(),
        )
    )
    names = json.loads(linux_tests.read_bytes())
    delta = reg.identity_delta(repo, K, commit)
    s = validate(
        dict(
            parent=K,
            role=l,
            pack=dict(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest()),
            delta=delta,
            policy="first-git-session-tables",
            **names,
        )
    )
    verify(repo, s)
    verify_pack(repo, K, commit, payload)
    out.mkdir()
    (out / "E.pack").write_bytes(payload)
    reg.write(out / "subject.json", {"candidate": s})


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="mode", required=True)
    sub.add_parser("preflight")
    k = sub.add_parser("seal")
    k.add_argument("repository", type=Path)
    k.add_argument("E")
    k.add_argument("tests", type=Path)
    k.add_argument("new_directory", type=Path)
    k.add_argument("--pack", type=Path)
    a = p.parse_args()
    if a.mode == "seal":
        seal(a.repository, a.E, a.tests, a.pack, a.new_directory)
    else:
        print(json.dumps(load(), sort_keys=True))
