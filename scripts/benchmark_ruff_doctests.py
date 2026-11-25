"""Measure warm cargo test --doc on a pinned set of Ruff crates."""

import argparse
import hashlib
import json
import os
import platform
import re
import statistics
import subprocess
import time
from pathlib import Path

RUFF_REVISION = "23a16fa018cf3b219c2edc7a2b739881e023a874"
# SHA-256 of tests.json at this revision, including each crate, example and outcome.
TESTS_SHA256 = "bfca3b70273c3dce6142698a4128c055a3a93d119c3db46e4765203e0d88ef9f"
PASSED = 207
IGNORED = 9
PROC_MACRO_TRUST = "CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST"
PACKAGES = (
    "ruff_annotate_snippets",
    "ruff_cache",
    "ruff_db",
    "ruff_formatter",
    "ruff_linter",
    "ruff_notebook",
    "ruff_options_metadata",
    "ruff_python_ast",
    "ruff_python_parser",
    "ruff_python_stdlib",
    "ruff_python_trivia",
    "ruff_source_file",
    "ruff_text_size",
    "ruff_unicode_names2",
    "ty_module_resolver",
    "ty_python_semantic",
)


def checked_output(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def test_inventory(log):
    """Include crate and test names so a different selection cannot give the same count."""
    tests = []
    package = None
    packages = set()
    for line in log.splitlines():
        if match := re.fullmatch(r"\s*Doc-tests (\w+)\s*", line):
            package = match[1]
            packages.add(package)
        elif match := re.fullmatch(r"test (.+) \.\.\. (ok|ignored)(?:, .*)?", line):
            if package is None:
                raise ValueError(f"Missing package for {line}")
            tests.append((package, match[1], match[2]))
    # These Ruff packages publish libraries under shorter crate names.
    library_names = {
        "ruff_annotate_snippets": "annotate_snippets",
        "ruff_unicode_names2": "unicode_names2",
    }
    if packages != {library_names.get(name, name) for name in PACKAGES}:
        raise ValueError("Doctest output did not cover all 16 Ruff crates")
    return sorted(tests)


def cargo_arguments(jobs):
    args = ["test", "--doc", "--all-features", "--locked", "--offline", "--jobs", str(jobs)]
    for name in PACKAGES:
        args.extend(["-p", name])
    return args


def lane_environment(lane, output):
    env = {
        k: os.environ[k]
        for k in ("PATH", "HOME", "CARGO_HOME", "RUSTUP_HOME", "LANG")
        if k in os.environ
    }
    env["CARGO_TERM_COLOR"] = "never"
    env["CARGO_TARGET_DIR"] = str(output / lane)
    if lane == "ohm":
        env[PROC_MACRO_TRUST] = "all"
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, required=True, help="clean Ruff checkout"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="new results directory"
    )
    parser.add_argument("--upstream", default="1.99.0")
    parser.add_argument("--ohm", required=True, help="versioned rustup toolchain")
    parser.add_argument("--jobs", type=int, default=32)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if checked_output("git", "rev-parse", "HEAD", cwd=source) != RUFF_REVISION:
        parser.error(f"check out Ruff {RUFF_REVISION}")
    if checked_output("git", "status", "--porcelain", cwd=source):
        parser.error("Ruff checkout must be clean")
    if output.is_relative_to(source) or args.jobs < 1:
        parser.error("use a separate output directory and a positive job count")
    output.mkdir(parents=True)
    lanes = {"stock": args.upstream, "ohm": args.ohm}
    environments = {lane: lane_environment(lane, output) for lane in lanes}
    tools = {}
    for lane, selector in lanes.items():
        env = environments[lane]
        tools[lane] = {}
        for name in ("cargo", "rustc", "rustdoc"):
            binary = checked_output(
                "rustup", "which", "--toolchain", selector, name, env=env
            )
            with open(binary, "rb") as f:
                tools[lane][name] = {
                    "version": checked_output(binary, "--version", env=env),
                    "sha256": hashlib.file_digest(f, "sha256").hexdigest(),
                }

    cargo_args = cargo_arguments(args.jobs)
    expected = None
    samples = []
    for pair in range(6):
        # Pair zero populates both targets and is excluded from the warm medians.
        order = ("ohm", "stock") if pair in (2, 4) else ("stock", "ohm")
        for lane in order:
            log = output / f"{pair}-{lane}.log"
            with log.open("xb") as stream:
                start = time.perf_counter()
                run = subprocess.run(
                    ["cargo", "+" + lanes[lane], *cargo_args],
                    cwd=source,
                    env=environments[lane],
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                seconds = time.perf_counter() - start
            if run.returncode:
                raise RuntimeError(
                    f"{lane} failed with exit {run.returncode}. See {log}"
                )
            raw = log.read_bytes()
            tests = test_inventory(raw.decode())
            if expected is None:
                expected = tests
                if (
                    sum(t[2] == "ok" for t in tests) != PASSED
                    or sum(t[2] == "ignored" for t in tests) != IGNORED
                ):
                    raise ValueError(f"Unexpected doctest selection. See {log}")
                (output / "tests.json").write_text(
                    json.dumps(expected, indent=2) + "\n"
                )
            elif tests != expected:
                raise ValueError(f"{lane} ran a different set of doctests. See {log}")
            samples.append(
                {
                    "pair": pair,
                    "toolchain": lane,
                    "seconds": seconds,
                    "log_sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
            print(lane, pair, f"{seconds:.3f} s", flush=True)

    report = {
        "project": "Ruff",
        "revision": RUFF_REVISION,
        "platform": platform.system(),
        "arch": platform.machine(),
        "upstream": args.upstream,
        "ohm": args.ohm,
        "cargo_args": cargo_args,
        "toolchains": tools,
        "proc_macro_trust": {
            lane: env.get(PROC_MACRO_TRUST) for lane, env in environments.items()
        },
        "passed": PASSED,
        "ignored": IGNORED,
        "tests_sha256": hashlib.sha256(
            (output / "tests.json").read_bytes()
        ).hexdigest(),
        "samples": samples,
        "warm_median_seconds": {
            lane: statistics.median(
                s["seconds"] for s in samples if s["pair"] and s["toolchain"] == lane
            )
            for lane in lanes
        },
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
