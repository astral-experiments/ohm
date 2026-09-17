#!/usr/bin/env python3
"""Measure ordinary warm Cargo checks after the same pinned Ruff parser edits."""

import argparse
import json
import os
import random
import subprocess
import time
from pathlib import Path

from measure import CASES, DEFAULT_CASES, machine, source_edits, write_json
from run_edits import diagnostic, normalized
from run_tests import REVISION, archive_ruff


def summarize(values):
    ordered = sorted(values)

    def quantile(fraction):
        position = (len(ordered) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        return round(
            (ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower))
            / 1e6,
            3,
        )

    return {
        "samples": len(ordered),
        "minimum_ms": quantile(0),
        "median_ms": quantile(0.5),
        "p95_ms": quantile(0.95),
        "maximum_ms": quantile(1),
    }


def invoke(args, name, operation):
    env = dict(
        os.environ,
        CARGO_TARGET_DIR=str(args.target),
        CARGO_BUILD_BUILD_DIR=str(args.target / "build"),
        CARGO_INCREMENTAL="1",
        CARGO_TERM_COLOR="never",
        RUSTC=str(args.stage / "bin/rustc"),
    )
    for option in (
        "RUSTC_WRAPPER",
        "RUSTC_WORKSPACE_WRAPPER",
        "RUSTFLAGS",
        "CARGO_ENCODED_RUSTFLAGS",
    ):
        env.pop(option, None)
    command = [
        "cargo",
        "+ohm",
        "check",
        "--locked",
        "-p",
        "ruff_python_parser",
        "--lib",
        "--message-format=json",
    ]
    if args.offline:
        command.append("--offline")
    start = time.perf_counter_ns()
    result = subprocess.run(
        command, cwd=args.checkout, env=env, capture_output=True, text=True, check=False
    )
    elapsed = time.perf_counter_ns() - start
    prefix = args.output / "logs" / name
    prefix.with_suffix(".stdout").write_text(result.stdout)
    prefix.with_suffix(".stderr").write_text(result.stderr)
    items = []
    errors = []
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        items.append(item)
        if item_error := diagnostic(line):
            errors.append(normalized(item_error, False))
    package_artifacts = [
        item["fresh"]
        for item in items
        if item.get("reason") == "compiler-artifact"
        and item.get("target", {}).get("name") == "ruff_python_parser"
    ]
    expected_code = 101 if operation == "apply" else 0
    if result.returncode != expected_code:
        raise RuntimeError(
            f"{name}: expected Cargo exit {expected_code}, got {result.returncode}; inspect {prefix}.stderr"
        )
    if operation == "apply":
        if len(errors) != 1 or errors[0]["code"] != "E0308":
            raise RuntimeError(f"{name}: expected exactly one E0308, got {errors!r}")
    elif errors:
        raise RuntimeError(f"{name}: unexpected errors {errors!r}")
    elif operation == "restore" and package_artifacts != [False]:
        raise RuntimeError(
            f"{name}: Cargo did not recheck the parser after a restore: {package_artifacts}"
        )
    elif operation == "noop" and package_artifacts != [True]:
        raise RuntimeError(
            f"{name}: Cargo no-op did not mark the parser fresh: {package_artifacts}"
        )
    return {
        "external_ns": elapsed,
        "returncode": result.returncode,
        "errors": errors,
        "parser_artifact_fresh": package_artifacts,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "checkout", "target", "stage", "output"):
        parser.add_argument(
            f"--{name}", type=lambda value: Path(value).resolve(), required=True
        )
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--compiler-revision", help="exact Git revision of the patched compiler source"
    )
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if args.rounds < 1 or args.warmups < 0:
        parser.error("rounds must be positive and warmups nonnegative")
    archive_ruff(args.repo, args.checkout)
    edits = source_edits(args.checkout, DEFAULT_CASES)
    (args.output / "logs").mkdir(parents=True, exist_ok=True)
    args.target.mkdir(parents=True, exist_ok=True)
    baseline = invoke(args, "initial", "initial")
    noops = [invoke(args, f"noop-{number}", "noop") for number in range(args.rounds)]
    rng = random.Random(args.seed)
    raw = []
    try:
        for index in range(args.warmups + args.rounds):
            order = list(DEFAULT_CASES)
            rng.shuffle(order)
            for case in order:
                path, clean, changed = edits[case]
                if path.read_bytes() != clean:
                    raise RuntimeError(f"{case}: baseline source unexpectedly changed")
                for operation, source in (("apply", changed), ("restore", clean)):
                    path.write_bytes(source)
                    sample = invoke(
                        args, f"round-{index:02d}-{case}-{operation}", operation
                    )
                    if operation == "apply":
                        actual_file = sample["errors"][0]["primary_spans"][0][0]
                        if actual_file != CASES[case]["file"]:
                            raise RuntimeError(
                                f"{case}: diagnostic came from unexpected {actual_file}"
                            )
                    raw.append(
                        {
                            "warmup": index < args.warmups,
                            "round": index,
                            "case": case,
                            "operation": operation,
                            **sample,
                        }
                    )
    finally:
        for path, clean, _changed in edits.values():
            if path.read_bytes() != clean:
                path.write_bytes(clean)
    measured = [sample for sample in raw if not sample["warmup"]]
    summary = {
        "ruff_revision": REVISION,
        "measurement": "normal cargo +ohm check, incremental on and resident query graph off, end-to-end process start to exit; source file write excluded; dependencies and filesystem warm after initial check",
        "command": "cargo +ohm check --locked -p ruff_python_parser --lib --message-format=json",
        "compiler_source_revision": args.compiler_revision,
        "offline": args.offline,
        "cargo_defaults": "Ohm defaults enabled; disk incremental on; resident query graph off",
        "percentile_method": "linearly interpolated between closest ranks",
        "compiler": subprocess.run(
            [str(args.stage / "bin/rustc"), "--version"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip(),
        "machine": machine(),
        "warmup_rounds": args.warmups,
        "measured_rounds": args.rounds,
        "seed": args.seed,
        "initial_seconds": round(baseline["external_ns"] / 1e9, 3),
        "warm_noop": summarize([sample["external_ns"] for sample in noops]),
        "by_operation": {
            operation: summarize(
                [
                    sample["external_ns"]
                    for sample in measured
                    if sample["operation"] == operation
                ]
            )
            for operation in ("apply", "restore")
        },
        "by_case": {
            case: {
                operation: summarize(
                    [
                        sample["external_ns"]
                        for sample in measured
                        if sample["case"] == case and sample["operation"] == operation
                    ]
                )
                for operation in ("apply", "restore")
            }
            for case in DEFAULT_CASES
        },
        "validation": {
            "all_applies_reported_exactly_one_E0308": True,
            "all_restores_were_clean_and_recompiled_the_parser": True,
            "all_warm_noops_marked_the_parser_fresh": True,
            "measured_transitions": len(measured),
        },
    }
    write_json(
        args.output / "samples.json",
        {"initial": baseline, "noops": noops, "transitions": raw},
    )
    write_json(args.output / "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
