#!/usr/bin/env python3
"""Run every test in a pinned Ruff parser against a patched Ohm, with or without its resident graph."""

import argparse
import json
import os
import re
import subprocess
import tarfile
from pathlib import Path

REVISION = "fd5d636bdd58a5a42e0212988e1cdf710eec8558"
GRAPH_FLAG = "-Zohm-resident-query-graph"
PACKAGE = Path("crates/ruff_python_parser")
COUNT_KEYS = ("passed", "failed", "ignored", "measured", "filtered")
TEST_TARGETS = ("unit", "syntax_fixtures", "inline_test_generator")
EXPECTED_COUNTS = {
    "unit": 245,
    "syntax_fixtures": 557,
    "inline_test_generator": 1,
    "doctests": 10,
}
PACKAGE_CAPTURES = {
    "fixtures.bin",
    "generate_inline_tests.test",
    "ruff_python_parser.lib",
    "ruff_python_parser.test",
}
RESULT = re.compile(
    r"(\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out"
)


def archive_ruff(repo, checkout):
    checkout.mkdir(parents=True, exist_ok=True)
    marker = checkout / ".ohm-resident-ruff-revision"
    if (checkout / "Cargo.toml").exists():
        if not marker.is_file() or marker.read_text().strip() != REVISION:
            raise SystemExit(
                "--checkout must be empty or a disposable archive created by this tool"
            )
        return
    if any(checkout.iterdir()):
        raise SystemExit(
            "--checkout must be empty or a disposable archive created by this tool"
        )
    with subprocess.Popen(
        ["git", "-C", str(repo), "archive", "--format=tar", REVISION],
        stdout=subprocess.PIPE,
    ) as archive:
        assert archive.stdout is not None
        with tarfile.open(fileobj=archive.stdout, mode="r|") as files:
            files.extractall(checkout, filter="data")
        if archive.wait():
            raise SystemExit("git archive failed")
    marker.write_text(REVISION + "\n")


def compiler_version(stage):
    for executable in ("rustc", "rustdoc"):
        if not (stage / "bin" / executable).is_file():
            raise SystemExit(f"patched stage is missing bin/{executable}: {stage}")
    result = subprocess.run(
        [str(stage / "bin/rustc"), "-vV"], capture_output=True, text=True, check=True
    )
    return dict(
        line.split(": ", 1) for line in result.stdout.splitlines() if ": " in line
    )


def capture_flags(captures, docs):
    files = sorted(captures.glob("doctest.*.json" if docs else "*.json"))
    result = []
    for path in files:
        data = json.loads(path.read_text())
        enabled = GRAPH_FLAG in data["argv"] or any(
            GRAPH_FLAG in contents.splitlines()
            for contents in data.get("argfiles", {}).values()
        )
        result.append(
            {
                "target": "doctest_compiler"
                if docs
                else path.name.removesuffix(".json"),
                "resident_query_graph_enabled": enabled,
            }
        )
    return result


def run_mode(args, mode):
    graph = mode.startswith("graph-")
    docs = mode.endswith("doc")
    output = args.output / mode
    captures = output / "captures"
    captures.mkdir(parents=True, exist_ok=True)
    for capture in captures.glob("*.json"):
        capture.unlink()
    for path in ("src/lib.rs", "tests/fixtures.rs", "tests/generate_inline_tests.rs"):
        (args.checkout / PACKAGE / path).touch()
    tools = Path(__file__).resolve().parent
    env = dict(
        os.environ,
        CARGO_TARGET_DIR=str(args.target_dir),
        CARGO_BUILD_BUILD_DIR=str(args.target_dir / "build"),
        CARGO_INCREMENTAL="0",
        RUSTC=str(args.stage / "bin/rustc"),
        RUSTC_WRAPPER=str(tools / "capture_rustc.py"),
        OHM_RUFF_CAPTURE=str(captures),
        RUSTC_BOOTSTRAP="1",
        CARGO_TERM_COLOR="never",
        INSTA_UPDATE="no",
    )
    if graph:
        env["OHM_RUFF_QUERY_GRAPH"] = "1"
    else:
        env.pop("OHM_RUFF_QUERY_GRAPH", None)
    if docs:
        env["RUSTDOC"] = str(args.stage / "bin/rustdoc")
        flags = [
            "-Zunstable-options",
            "--test-builder-wrapper",
            str(tools / "capture_doctest.py"),
        ]
        if graph:
            flags.append(GRAPH_FLAG)
        env["CARGO_ENCODED_RUSTDOCFLAGS"] = "\x1f".join(flags)
    command = [
        "cargo",
        "+ohm",
        "-Zohm-defaults=no",
        "test",
        "--locked",
        "-p",
        "ruff_python_parser",
        "--all-features",
        "--doc" if docs else "--all-targets",
        "--verbose",
    ]
    if args.offline:
        command.append("--offline")
    with (output / "cargo.log").open("w") as log:
        log.write("$ " + " ".join(command) + "\n")
        log.flush()
        proc = subprocess.run(
            command,
            cwd=args.checkout,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    log = (output / "cargo.log").read_text()
    counts = [
        dict(zip(COUNT_KEYS, map(int, match.groups()), strict=True))
        for match in RESULT.finditer(log)
    ]
    expected_targets = ("doctests",) if docs else TEST_TARGETS
    invocations = capture_flags(captures, docs)
    problems = []
    if proc.returncode:
        problems.append(f"Cargo exited {proc.returncode}: {output / 'cargo.log'}")
    if len(counts) != len(expected_targets):
        problems.append(
            f"expected {len(expected_targets)} test summaries, found {len(counts)}"
        )
    for target, count in zip(expected_targets, counts):
        if count["passed"] != EXPECTED_COUNTS[target]:
            problems.append(
                f"{target}: expected {EXPECTED_COUNTS[target]} passing tests, found {count['passed']}"
            )
    if not invocations or (
        not docs
        and {invocation["target"] for invocation in invocations} != PACKAGE_CAPTURES
    ):
        problems.append("missing parser compiler captures")
    if any(
        invocation["resident_query_graph_enabled"] != graph
        for invocation in invocations
    ):
        problems.append(
            "captured compiler arguments did not match the requested query-graph setting"
        )
    if any(item["failed"] or item["ignored"] or item["filtered"] for item in counts):
        problems.append("some parser tests failed, were ignored, or were filtered")
    return {
        "returncode": proc.returncode,
        "counts": dict(zip(expected_targets, counts)),
        "total_passed": sum(item["passed"] for item in counts),
        "captured_invocations": invocations,
    }, problems


def fixture_counts(checkout):
    resources = checkout / PACKAGE / "resources"
    directories = {
        "valid": "valid",
        "invalid": "invalid",
        "inline_ok": "inline/ok",
        "inline_error": "inline/err",
    }
    return {
        name: sum(
            path.suffix in (".py", ".pyi")
            for path in (resources / directory).rglob("*")
        )
        for name, directory in directories.items()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("repo", "checkout", "target-dir", "stage", "output"):
        parser.add_argument(
            f"--{option}", type=lambda value: Path(value).resolve(), required=True
        )
    parser.add_argument("--mode", choices=("both", "graph", "default"), default="both")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="require dependencies to be cached locally",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    version = compiler_version(args.stage)
    archive_ruff(args.repo, args.checkout)
    modes = {
        "both": ("graph-test", "graph-doc", "test", "doc"),
        "graph": ("graph-test", "graph-doc"),
        "default": ("test", "doc"),
    }[args.mode]
    summary = {
        "ruff_revision": REVISION,
        "package": "ruff_python_parser",
        "rustc_version": version["release"],
        "rustc_self_reported_commit": version["commit-hash"],
        "host": version["host"],
        "cargo_incremental": False,
        "package_declares_optional_features": False,
        "syntax_fixtures_by_family": fixture_counts(args.checkout),
        "runs": {},
    }
    problems = []
    for mode in modes:
        result, failures = run_mode(args, mode)
        summary["runs"][mode] = result
        problems.extend(f"{mode}: {failure}" for failure in failures)
        print(
            f"{mode}: {result['total_passed']} passed; {len(failures)} validation failures",
            flush=True,
        )
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if problems:
        raise SystemExit("\n".join(problems))


if __name__ == "__main__":
    main()
