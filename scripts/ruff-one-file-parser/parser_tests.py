"""Run Ruff's native datatest harness after Cargo, with the upstream snapshot held fixed."""

import contextlib
import os
from pathlib import Path
import re
import subprocess

import fixture as f

NAME = "inline_ok::bare_raise_before_semicolon.py"
SNAP_SHA = "00bcbfaa2c3e1a876163b420a1a3b8ca54d87f62aebf28c7f4ef059f5712975f"
PREFIXES = {
    "valid": "valid_syntax",
    "invalid": "invalid_syntax",
    "inline/ok": "inline_ok",
    "inline/err": "inline_err",
}


def roster(repo):
    prefix = "crates/ruff_python_parser/resources/"
    paths = f.git(repo, "ls-tree", "-r", "--name-only", f.B, prefix).decode().splitlines()
    names = {
        test + "::" + p.removeprefix(prefix + sub + "/")
        for sub, test in PREFIXES.items()
        for p in paths
        if p.startswith(prefix + sub + "/") and re.search(r"\.pyi?$", p)
    }
    f.require(len(names) == 557 and NAME not in names, "wrong locked original test roster")
    return names


@contextlib.contextmanager
def injected(repo):
    src = f.HERE / "bare_raise_before_semicolon.py"
    snap = f.HERE / Path(f.SNAP).name
    files = [(repo / f.FIXTURE, src.read_bytes()), (repo / f.SNAP, snap.read_bytes())]
    f.require(
        [f.sha(b) for _, b in files] == [f.FIXTURE_SHA, SNAP_SHA], "wrong upstream fixture or snapshot"
    )
    held = []
    try:
        for dest, content in files:
            f.require(
                dest.parent.resolve(strict=True) == dest.parent and not dest.is_symlink(),
                "unexpected test fixture parent",
            )
            with dest.open("xb") as output:
                output.write(content)
                s = os.fstat(output.fileno())
            held.append((dest, content, s.st_dev, s.st_ino))
        yield
    finally:
        for dest, content, dev, ino in reversed(held):
            s = dest.lstat()
            f.require(
                (s.st_dev, s.st_ino) == (dev, ino)
                and not dest.is_symlink()
                and dest.read_bytes() == content,
                "replaced runtime fixture",
            )
            dest.unlink()


def verify_calls(records, names, state, binary=None, repo=None):
    f.require(
        f.sha(("\n".join(sorted(names)) + "\n").encode())
        == "e3101accb5f6232ae5e6cbb9436669f1eb50f3fdf1e9577932a5976e156e0d5d",
        "wrong original 557 names",
    )
    commands = {
        "list": ["--list"],
        "original-suite": ["--format", "pretty", "--test-threads", "2"],
        "list-plus-one": ["--list"],
        "exact": ["--exact", NAME, "--format", "pretty", "--test-threads", "1"],
    }
    f.require(set(records) == set(commands), "missing or unexpected native invocation")
    if binary is not None:
        f.require(
            all(
                records[k]["argv"] == [str(binary), *args]
                and records[k]["cwd"] == str(repo / "crates/ruff_python_parser")
                and records[k]["workspace_root"] == str(repo)
                for k, args in commands.items()
            ),
            "different physical test argv or working directory",
        )

    def listing(rec):
        f.require(rec["exit"] == 0 and rec["stderr"] == "", "native listing refused")
        lines = rec["stdout"].splitlines()
        f.require(
            all(s.endswith(": test") for s in lines) and len(set(lines)) == len(lines),
            "invalid native listing",
        )
        return {s[:-6] for s in lines}

    f.require(
        listing(records["list"]) == names and listing(records["list-plus-one"]) == names | {NAME},
        "physical test names differ",
    )
    suite = records["original-suite"]
    f.require(
        suite["exit"] == 0
        and re.search(r"test result: ok\. 557 passed; 0 failed; 0 ignored;", suite["stdout"]),
        "ordinary native suite failed",
    )
    passed = re.findall(r"^test (\S+)\s+\.\.\. ok$", suite["stdout"], re.M)
    f.require(
        len(passed) == 557 and set(passed) == names, "missing or extra original native test verdict"
    )
    one = records["exact"]
    result = one["stdout"] + one["stderr"]
    f.require(
        "running 1 test" in result and NAME in result and ".snap.new" not in result,
        "missing new native test",
    )
    if state == "baseline":
        f.require(
            re.search(r"^test " + re.escape(NAME) + r"\s+\.\.\. FAILED$", one["stdout"], re.M),
            "failed different case",
        )
        f.require(
            one["exit"] == 101
            and "Expected no syntax errors for a valid program" in result
            and one["stdout"].count("Syntax Error: Expected an expression") == 1
            and "2 | except ValueError: raise; report()\n  |                         ^ Syntax Error: Expected an expression"
            in one["stdout"]
            and "0 passed; 1 failed" in result,
            "wrong original parser failure",
        )
    else:
        f.require(
            re.search(r"^test " + re.escape(NAME) + r"\s+\.\.\. ok$", one["stdout"], re.M),
            "passed different case",
        )
        f.require(
            one["exit"] == 0
            and "1 passed; 0 failed" in result
            and "Expected an expression" not in result,
            "edited parser rejected upstream snapshot",
        )


def run(binary, repo, state, env):
    base = repo / "crates/ruff_python_parser"
    common = dict(**env, INSTA_UPDATE="no", INSTA_WORKSPACE_ROOT=str(repo), CLICOLOR="0", NO_COLOR="1")
    records = {}

    def call(name, args):
        proc = subprocess.run([binary, *args], env=common, cwd=base, capture_output=True, timeout=200)
        records[name] = {
            "argv": [str(binary), *args],
            "cwd": str(base),
            "workspace_root": str(repo),
            "exit": proc.returncode,
            "stdout": proc.stdout.decode(),
            "stderr": proc.stderr.decode(),
        }

    call("list", ["--list"])
    call("original-suite", ["--format", "pretty", "--test-threads", "2"])
    with injected(repo):
        call("list-plus-one", ["--list"])
        call("exact", ["--exact", NAME, "--format", "pretty", "--test-threads", "1"])
    return records
