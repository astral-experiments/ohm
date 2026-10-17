#!/usr/bin/env python3
"""Measure worktree creation and its first focused validation after a warm parent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import statistics
import subprocess
import time

import replay_sessions as replay
from benchmark import BenchmarkError

VALIDATION = {
    "kind": "command",
    "label": "Run the first focused mdtest in the new worktree",
    "program": "cargo",
    "args": [
        "nextest",
        "run",
        "-p",
        "ty_python_semantic",
        "--test",
        "mdtest",
        "--",
        "mdtest::liskov.md",
    ],
    "output_contains": ["1 test run: 1 passed"],
}


def creation_command(
    label: str, selector: str, child: Path, target: Path, revision: str
) -> list[str]:
    if label == "stock":
        return ["git", "worktree", "add", "--detach", str(child), revision]
    return [
        "cargo",
        f"+{selector}",
        "worktree",
        "add",
        "--detach",
        str(child),
        "--target-dir",
        str(target),
        revision,
    ]


class WorktreeStart(replay.Replay):
    def __init__(self, options: argparse.Namespace):
        arguments = [
            "--project",
            "ruff",
            "--scenario",
            str(options.scenario),
            "--output-dir",
            str(options.output_dir),
            "--upstream",
            options.upstream,
            "--ohm",
            options.ohm,
            "--jobs",
            str(options.jobs),
            "--repetitions",
            str(options.repetitions),
            "--timeout",
            str(options.timeout),
            "--minimum-free-gb",
            str(options.minimum_free_gb),
            "--compiler-accounting",
            options.compiler_accounting,
        ]
        if options.source_path:
            arguments += ["--source-path", f"ruff={options.source_path}"]
        if options.require_idle:
            arguments += ["--require-idle"]
        if options.offline:
            arguments += ["--offline"]
        super().__init__(replay.parser().parse_args(arguments))
        self.toolchains = (
            ("stock", options.upstream),
            ("ohm", options.ohm),
            ("ohm-trusted", options.ohm),
        )
        self.phase = "parent"

    def environment(self, scenario, label, selector, repetition):
        base_label = "stock" if label == "stock" else "ohm"
        environment = super().environment(scenario, base_label, selector, repetition)
        environment["CARGO_TARGET_DIR"] = str(
            self.output / "targets" / label / str(repetition) / self.phase
        )
        environment.pop("CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST", None)
        environment.pop("CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST", None)
        if label != "stock":
            environment["CARGO_BUILD_BUILD_DIR"] = str(
                self.output / "shared-build" / label / str(repetition)
            )
        if label == "ohm-trusted":
            environment["CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST"] = "all"
            environment["CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST"] = "all"
        return environment

    def run_session(self, scenario, label, selector, repetition):
        self.check_disk()
        source = self.sources[scenario.project]
        cell = self.output / "worktrees" / label / str(repetition)
        parent, child = cell / "parent", cell / "child"
        cell.mkdir(parents=True, exist_ok=False)
        replay.command_output(
            ["git", "worktree", "add", "--detach", str(parent), scenario.base_revision],
            cwd=source,
        )
        self.apply_setup_patches(scenario, parent)
        print(f"\n{label} / repetition {repetition + 1}: warming parent", flush=True)
        self.phase = "parent"
        warmup = self.run_command(
            scenario, parent, VALIDATION, label, selector, repetition, 1, phase="warmup"
        )
        parent_environment = self.environment(scenario, label, selector, repetition)
        self.phase = "child"
        child_environment = self.environment(scenario, label, selector, repetition)
        child_target = Path(child_environment["CARGO_TARGET_DIR"])
        if child_target.exists():
            raise BenchmarkError("new worktree target already exists")
        arguments = creation_command(
            label, selector, child, child_target, scenario.base_revision
        )
        self.wait_until_idle()
        started = time.perf_counter()
        with replay.InterferenceMonitor(enabled=self.options.require_idle) as monitor:
            result = subprocess.run(
                arguments,
                cwd=parent,
                env=parent_environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=self.options.timeout,
                check=False,
            )
        creation_seconds = time.perf_counter() - started
        log = (
            self.output
            / "logs"
            / scenario.project
            / label
            / str(repetition)
            / "create.log"
        )
        log.write_text(result.stdout)
        if result.returncode or monitor.failure or monitor.observed:
            raise BenchmarkError(
                f"worktree creation failed or overlapped unrelated builds; inspect {log}"
            )
        if (
            replay.command_output(["git", "rev-parse", "HEAD"], cwd=child)
            != scenario.base_revision
        ):
            raise BenchmarkError("new worktree is not at the pinned revision")
        if replay.command_output(["git", "status", "--porcelain"], cwd=child):
            raise BenchmarkError("new worktree has unexpected source changes")
        self.apply_setup_patches(scenario, child)
        print(
            f"  Created in {creation_seconds:.2f}s; running first validation",
            flush=True,
        )
        validation = self.run_command(
            scenario, child, VALIDATION, label, selector, repetition, 1
        )
        sample = {
            "project": scenario.project,
            "toolchain": label,
            "selector": selector,
            "repetition": repetition,
            "base_revision": scenario.base_revision,
            "parent_warmup": warmup,
            "creation": {
                "command": arguments,
                "wall_seconds": creation_seconds,
                "log": str(log),
            },
            "first_validation": validation,
            "wall_seconds": creation_seconds + validation["wall_seconds"],
            "target_directories": {
                "parent": parent_environment["CARGO_TARGET_DIR"],
                "child": str(child_target),
            },
            "shared_build_directory": child_environment.get("CARGO_BUILD_BUILD_DIR"),
            "proc_macro_trust": child_environment.get(
                "CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST", "none"
            ),
            "native_tool_trust": child_environment.get(
                "CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST", "none"
            ),
        }
        self.samples.append(sample)
        self.persist()
        print(f"  Create + first validation: {sample['wall_seconds']:.2f}s", flush=True)
        return sample

    def persist(self):
        self.output.mkdir(parents=True, exist_ok=True)
        result = {
            "benchmark": "worktree-start",
            "host": platform.node(),
            "platform": platform.platform(),
            "jobs": self.options.jobs,
            "repetitions": self.options.repetitions,
            "toolchains": dict(self.toolchains),
            "compiler_accounting": self.options.compiler_accounting,
            "fixture": str(self.scenarios[0].path),
            "base_revision": self.scenarios[0].base_revision,
            "validation": VALIDATION,
            "samples": self.samples,
        }
        temporary = self.output / ".results.json.tmp"
        temporary.write_text(json.dumps(result, indent=2) + "\n")
        temporary.replace(self.output / "results.json")

    def run(self):
        self.check_disk()
        if self.output.exists() and any(self.output.iterdir()):
            raise BenchmarkError("worktree-start output must be a new, empty directory")
        scenario = self.scenarios[0]
        self.sources[scenario.project] = self.prepare_source(scenario)
        self.persist()
        for repetition in range(self.options.repetitions):
            for offset in range(len(self.toolchains)):
                label, selector = self.toolchains[
                    (repetition + offset) % len(self.toolchains)
                ]
                self.run_session(scenario, label, selector, repetition)
        for label, _ in self.toolchains:
            values = [
                sample["wall_seconds"]
                for sample in self.samples
                if sample["toolchain"] == label
            ]
            print(f"{label}: {statistics.median(values):.2f}s median", flush=True)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--scenario", type=Path, default=replay.SCENARIO_DIRECTORY / "ty-29327.json"
    )
    result.add_argument("--source-path", type=Path)
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument("--upstream", default="1.99.0")
    result.add_argument("--ohm", default="ohm-1.99.0-5")
    result.add_argument("--jobs", type=int, default=8)
    result.add_argument("--repetitions", type=int, default=3)
    result.add_argument("--timeout", type=int, default=1800)
    result.add_argument("--minimum-free-gb", type=int, default=60)
    result.add_argument(
        "--compiler-accounting", choices=("status", "verbose"), default="status"
    )
    result.add_argument("--offline", action="store_true")
    result.add_argument("--require-idle", action="store_true")
    return result


if __name__ == "__main__":
    try:
        WorktreeStart(parser().parse_args()).run()
    except (BenchmarkError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from error
