"""Check the registration against the two Git trees without changing a checkout."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tomllib


def verify(repo, registration):
    source = registration["source"]
    old, new, path = source["old"], source["new"], source["path"]

    def git(*args):
        return subprocess.check_output(["git", "-C", repo, *args])

    def revision(name):
        return git("rev-parse", "--verify", name).strip().decode("ascii")

    assert revision(f"{new}^") == old
    assert git("diff", "--name-only", "-z", old, new) == path.encode() + b"\0"
    stats = git("diff", "--numstat", old, new).split(b"\t")[:2]
    assert list(map(int, stats)) == source["diff_numstat"]
    patch = git("diff", "--no-ext-diff", "--unified=0", old, new, "--", path)
    for line in patch.splitlines():
        if line[:1] in (b"+", b"-") and not line.startswith((b"+++ ", b"--- ")):
            change = line[1:].strip()
            assert not change or change.startswith(b"///"), line

    for index, label in enumerate(("old", "new")):
        head = source[label]
        assert revision(f"{head}^{{tree}}") == source[f"{label}_tree"]
        assert revision(f"{head}:{path}") == source[f"{label}_blob"]
        lock = git("show", f"{head}:Cargo.lock")
        assert hashlib.sha256(lock).hexdigest() == source["lock_sha256"]
        profile = tomllib.loads(git("show", f"{head}:Cargo.toml").decode())["profile"]["dev"]
        expected = registration["profile"]
        assert (profile["opt-level"], profile["debug"], profile["lto"]) == (
            expected["opt_level"], expected["debug"], expected["lto"]
        )
        manifest = tomllib.loads(git("show", f"{head}:crates/ty_server/Cargo.toml").decode())
        assert manifest["dependencies"]["ty_python_semantic"]["workspace"] is True
        test_root = f"{head}:crates/ty_server/tests/e2e"
        assert b"mod signature_help;" in git("show", f"{test_root}/main.rs")
        test_name = registration["named_test"].split("::")[1].encode()
        assert b"\n#[test]\nfn " + test_name + b"()" in git("show", f"{test_root}/signature_help.rs")
        snapshot = f"{test_root}/snapshots/e2e__signature_help__works_in_function_name.snap"
        assert revision(snapshot) == source["e2e_snapshot_blob"]
        lines = git("show", f"{head}:{path}").decode().splitlines()
        for old_line, new_line, signature in registration["source_sites"]:
            assert signature in lines[(old_line, new_line)[index] - 1]


if __name__ == "__main__":
    if len(sys.argv) != 2 or not __debug__:
        raise SystemExit("usage: python3 verify_source.py RUFF_REPOSITORY")
    plan = json.loads(Path(__file__).with_name("registration.json").read_text())
    verify(sys.argv[1], plan)
    print("Verified both Ruff trees, the documentation-only edit, the Cargo profile, and the e2e source oracles.")
