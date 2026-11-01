"""Apply Ruff #29761's production hunk to private B and verify the native CLI oracle."""

import ast
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent
B = "7b13f01ba1569887a25670820764b24c206da8e5"
B_TREE = "97ca36909f1ae8fa028b2c1f48f452fbdcdbbd4c"
UPSTREAM = "abee0da3f2ccf12f322ac50817b621d32753f860"
PARENT = "691b60a3f3bc0c28318ee866747da8c7f0af3d3a"
SRC = "crates/ruff_python_parser/src/parser/statement.rs"
FIXTURE = "crates/ruff_python_parser/resources/inline/ok/bare_raise_before_semicolon.py"
SNAP = "crates/ruff_python_parser/tests/snapshots/valid_syntax@bare_raise_before_semicolon.py.snap"
BRANCH = "refs/heads/qa-fixed-parser"
FIXTURE_SHA = "ef5231e62085dae61ce0f1ab5f1973515efc109c83dee7834669baca211433e4"
PATCH_SHA = "d7b56046da7498457052b3677f5955b6b7ce6423ef677dd763b4e3fcbff6b65b"
SOURCE_SHA = {
    "baseline": "ed90735bde9b18cfce30b119e0a460be995ec3e56f2f70f16a4899d4fdd4f13f",
    "invalid": "d261995f43fe34ef6b4e1891a4f0798ef8c3efe12ea83fe4ced29ae41354976e",
    "edited": "b107023b112e7339871356521ca3db829608da015518fdd20674ce2c7f4db8d5",
}
FILENAME = "/corpus/bare_raise_before_semicolon.py"
CLI_ARGS = [
    "check",
    "--isolated",
    "--no-cache",
    "--select",
    "F401",
    "--output-format",
    "json",
    "--stdin-filename",
    FILENAME,
    "-",
]


def require(cond, message):
    if not cond:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(repo, *args, stdin=None):
    env = {
        **os.environ,
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    return subprocess.check_output(["git", "-C", repo, *args], env=env, input=stdin)


def pinned_inputs():
    patch = gzip.decompress((HERE / "production.patch.gz").read_bytes())
    body = (HERE / "bare_raise_before_semicolon.py").read_bytes()
    require((sha(patch), sha(body)) == (PATCH_SHA, FIXTURE_SHA), "input changed")
    handler = ast.parse(body).body[0].handlers[0]
    first, last = handler.body
    require(
        isinstance(first, ast.Raise) and first.exc is None and first.cause is None, "not a bare raise"
    )
    require(
        isinstance(last, ast.Expr)
        and isinstance(last.value, ast.Call)
        and last.value.func.id == "report",
        "lost following call",
    )
    return patch, body


def state(repo, expected):
    head = git(repo, "rev-parse", "HEAD").decode().strip()
    branch = git(repo, "symbolic-ref", "HEAD").decode().strip()
    tree = git(repo, "rev-parse", "HEAD^{tree}").decode().strip()
    require((head, branch, tree) == (B, BRANCH, B_TREE), "wrong branch, HEAD or tree")
    require(git(repo, "diff", "--cached", "--name-only", "-z") == b"", "staged change")
    status = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    require(
        status == (b"" if expected == "baseline" else b" M " + SRC.encode() + b"\0"),
        "wrong tracked or untracked changes",
    )
    source = sha((repo / SRC).read_bytes())
    require(source == SOURCE_SHA[expected], "wrong production source")
    index = Path(
        git(repo, "rev-parse", "--path-format=absolute", "--git-path", "index").decode().strip()
    )
    watched = {}
    for name in ("HEAD", BRANCH):
        path = repo / ".git" / name
        require(path.is_file() and path.resolve(strict=True) == path, "wrong physical fixed ref")
        info = path.stat()
        watched[name] = [
            sha(path.read_bytes()),
            info.st_dev,
            info.st_ino,
            info.st_mtime_ns,
            info.st_ctime_ns,
        ]
    return {
        "head": head,
        "branch": branch,
        "tree": tree,
        "index_sha256": sha(index.read_bytes()),
        "watched": watched,
        "status": status.rstrip(b"\0").decode(),
        "source_sha256": source,
        "source_blob": git(repo, "hash-object", SRC).decode().strip(),
    }


def switch(repo, target):
    patch, _ = pinned_inputs()
    before = state(repo, "baseline" if target == "edited" else "edited")
    options = ["--whitespace=error-all", *(["--reverse"] if target == "baseline" else [])]
    git(repo, "apply", "--check", *options, "-", stdin=patch)
    git(repo, "apply", *options, "-", stdin=patch)
    after = state(repo, target)
    require(before["index_sha256"] == after["index_sha256"], "git apply changed index bytes")
    return after


def change_control(repo, target):
    """Caller must explicitly create this branch in its own disposable QA checkout."""
    require(
        (repo / ".git").is_dir() and not (repo / ".git").is_symlink(),
        "requires a standalone private checkout",
    )
    require(git(repo, "remote").strip() == b"", "requires a private checkout with no remote")
    return switch(repo, target)


def check_output(binary, mode, *, env=None, cwd=None, verify=True):
    _, body = pinned_inputs()
    with binary.open("rb") as image:
        require(image.read(4) == b"\x7fELF", "expected a GNU native ELF")
        image.seek(0)
        digest = hashlib.file_digest(image, "sha256").hexdigest()
    version = subprocess.run(
        [binary, "version", "--output-format", "json"], capture_output=True, check=True, cwd=cwd, env=env
    )
    parsed = json.loads(version.stdout)
    require(parsed["commit_info"]["commit_hash"] == B, "wrong embedded Ruff revision")
    rows = {}
    for case, content in cases(body).items():
        run = subprocess.run([binary, *CLI_ARGS], input=content, capture_output=True, cwd=cwd, env=env)
        rows[case] = {
            "stdin": content.decode(),
            "exit": run.returncode,
            "stdout": run.stdout.decode(),
            "stderr": run.stderr.decode(),
        }
    report = {
        "path": str(binary),
        "bytes": binary.stat().st_size,
        "sha256": digest,
        "version_argv": [str(binary), "version", "--output-format", "json"],
        "version": parsed,
        "argv": [str(binary), *CLI_ARGS],
        "expected": mode,
        "cases": rows,
    }
    if verify:
        validate(report, binary, mode)
    return report


def cases(body):
    return {
        "bare-semicolon": body,
        "ordinary-raise": b"try: work()\nexcept ValueError: raise\n",
        "explicit-exception-semicolon": b"try: work()\nexcept ValueError: raise ValueError(); report()\n",
        "cause-without-exception": b"try: work()\nexcept ValueError: raise from ValueError\n",
    }


def validate(report, binary, mode):
    _, body = pinned_inputs()
    require(
        report["path"] == str(binary)
        and report["argv"] == [str(binary), *CLI_ARGS]
        and report["expected"] == mode
        and report["version_argv"] == [str(binary), "version", "--output-format", "json"]
        and report["version"]["commit_info"]["commit_hash"] == B,
        "wrong CLI, native revision or syntax command",
    )
    require(set(report["cases"]) == set(cases(body)), "missing or extra syntax probe")
    errors = {"cause-without-exception": ("Exception missing in `raise` statement with cause", 26, 30)}
    if mode == "baseline":
        errors["bare-semicolon"] = ("Expected an expression", 25, 26)
    for case, content in cases(body).items():
        run = report["cases"][case]
        require(run["stdin"] == content.decode(), "wrong source tested")
        require(
            run["stderr"] == "" and run["exit"] == int(case in errors),
            f"{case}: unexpected status/stderr",
        )
        ds = json.loads(run["stdout"])
        if case not in errors:
            require(ds == [], f"{case}: unexpected diagnostics")
        else:
            message, start, end = errors[case]
            require(isinstance(ds, list) and len(ds) == 1, f"{case}: ambiguous diagnostic")
            d = ds[0]
            require(
                [d["code"], d["message"], d["filename"], d["location"], d["end_location"]]
                == [
                    "invalid-syntax",
                    message,
                    FILENAME,
                    {"row": 2, "column": start},
                    {"row": 2, "column": end},
                ],
                f"{case}: wrong raw parser diagnostic",
            )
