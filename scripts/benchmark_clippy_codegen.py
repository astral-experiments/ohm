#!/usr/bin/env python3
"""Measure opt-in Clippy codegen against the same released Ohm toolchain.

The workflow study compares tests alone, Clippy followed by the same tests, and
combined Clippy/tests. The replay study keeps every recorded command, including
standalone Clippy, and measures the cost of enabling the option during builds.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import platform
import shutil
import statistics
import sys
import time
from pathlib import Path

import benchmark
import replay_sessions

# Match the replay monitor, which recognizes reparented helpers in our process group.
benchmark.competing_processes = replay_sessions.competing_processes

ARMS = ("tests-only", "separate", "combined")
OPT_IN = "CARGO_UNSTABLE_OHM_CLIPPY_CODEGEN"
benchmark.COMPILER_PROCESSES.update(
    {
        "ld.bfd",
        "ld.lld",
        "wild",
        "mold",
        "gcc",
        "g++",
        "cc",
        "ninja",
        "make",
        "SMHasher3",
        "SMHasher",
    }
)


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def toolchain_identity(selector: str) -> dict:
    sysroot = Path(
        benchmark.command_output(["rustc", f"+{selector}", "--print", "sysroot"])
    )
    return {
        "selector": selector,
        "rustc": benchmark.command_output(["rustc", f"+{selector}", "-vV"]),
        "cargo": benchmark.command_output(["cargo", f"+{selector}", "-vV"]),
        "clippy": benchmark.command_output(
            [str(sysroot / "bin/clippy-driver"), "--version"]
        ),
        "executables": {
            name: file_digest(sysroot / "bin" / name)
            for name in ("rustc", "cargo", "clippy-driver", "cargo-clippy")
        },
    }


def quiet_preflight(output: Path) -> list[dict]:
    """Require six consecutive quiet Linux intervals before a measured suite."""
    observations = []
    if platform.system() != "Linux":
        raise benchmark.BenchmarkError("this campaign's CPU quiet gate requires Linux")

    def counters():
        return [
            int(value)
            for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]
        ]

    for _ in range(6):
        before = counters()
        time.sleep(5)
        after = counters()
        delta = [b - a for a, b in zip(before, after)]
        total = sum(delta)
        active = replay_sessions.competing_processes()
        row = {
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "idle_percent": 100 * delta[3] / total,
            "iowait_percent": 100 * delta[4] / total,
            "steal_percent": 100 * delta[7] / total,
            "unrelated_compilers": active,
        }
        observations.append(row)
        output.mkdir(parents=True, exist_ok=True)
        (output / "preflight.json").write_text(
            json.dumps(observations, indent=2) + "\n"
        )
        if (
            row["idle_percent"] < 95
            or row["iowait_percent"] > 0.5
            or row["steal_percent"] > 0.1
            or active
        ):
            raise benchmark.BenchmarkError(f"quiet preflight failed: {row}")
    return observations


def footprint(root: Path) -> dict:
    """Count private cache files once per inode; this is not physical COW usage."""
    seen = set()
    logical = allocated = 0
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        stat = path.stat()
        key = stat.st_dev, stat.st_ino
        if key not in seen:
            seen.add(key)
            logical += stat.st_size
            allocated += stat.st_blocks * 512
    return {
        "logical_bytes": logical,
        "stat_allocated_bytes": allocated,
        "files": len(seen),
    }


def sanitize_environment() -> None:
    for name in list(os.environ):
        if name.startswith(
            ("CARGO_UNSTABLE_", "CARGO_OHM_", "CARGO_INHERITED_")
        ) or name in {
            "RUSTFLAGS",
            "CARGO_ENCODED_RUSTFLAGS",
            "RUSTC_WRAPPER",
            "RUSTC_WORKSPACE_WRAPPER",
            "RUSTC",
            "CLIPPY_ARGS",
            "CLIPPY_CODEGEN",
            "CARGO_BUILD_BUILD_DIR",
        }:
            os.environ.pop(name, None)


def discard_artifacts(output: Path, paths: list[Path]) -> None:
    for path in paths:
        if (
            path.is_symlink()
            or not path.is_dir()
            or not path.resolve().is_relative_to(output.resolve())
            or path.resolve() == output.resolve()
        ):
            raise benchmark.BenchmarkError(
                f"refusing to discard an unsafe target: {path}"
            )
    for path in paths:
        shutil.rmtree(path)


class WorkflowStudy(benchmark.Study):
    def __init__(self, options):
        super().__init__(options)
        self.toolchains = tuple((arm, options.ohm) for arm in ARMS)
        self.cycles = []
        self.footprints = []
        self.discard_targets = options.discard_targets
        options.discard_targets = False

    def ordered_toolchains(self, index):
        orders = ((1, 2, 0), (0, 2, 1), (2, 0, 1), (1, 0, 2), (0, 1, 2), (2, 1, 0))
        return tuple(self.toolchains[i] for i in orders[index % len(orders)])

    def execute(self, workload, workflow, label, selector, *, record=True, **kwargs):
        target = self.target(workload, "test", label)
        environment = {
            OPT_IN: "true" if label == "combined" else "false",
            "CARGO_OHM_CLIPPY_ARGS": "",
        }
        first = len(self.samples)
        if label == "separate":
            targets = ["--test", "it"] if workload.repository == "uv" else ["--lib"]
            super().execute(
                workload,
                "clippy",
                label,
                selector,
                arguments=[
                    "cargo",
                    f"+{selector}",
                    "clippy",
                    "-p",
                    workload.package,
                    *targets,
                    "--profile",
                    "test",
                    "--locked",
                    "--offline",
                ],
                target_directory=target,
                extra_environment=environment,
                record=True,
                **kwargs,
            )
        super().execute(
            workload,
            "test",
            label,
            selector,
            target_directory=target,
            extra_environment=environment,
            record=True,
            **kwargs,
        )
        components = self.samples[first:]
        cycle = {
            "project": workload.name,
            "arm": label,
            "phase": kwargs["phase"],
            "repetition": kwargs["repetition"],
            "measured": record,
            "wall_seconds": sum(sample["wall_seconds"] for sample in components),
            "components": components,
        }
        self.cycles.append(cycle)
        self.write_results()

    def comparisons(self):
        rows = []
        for workload in self.workloads:
            for phase in ("cold", "noop", "dependency", "direct"):
                values = {
                    arm: [
                        cycle["wall_seconds"]
                        for cycle in self.cycles
                        if cycle["project"] == workload.name
                        and cycle["phase"] == phase
                        and cycle["arm"] == arm
                        and cycle["measured"]
                        and all(sample["valid"] for sample in cycle["components"])
                    ]
                    for arm in ARMS
                }
                if all(values.values()):
                    medians = {
                        arm: statistics.median(samples)
                        for arm, samples in values.items()
                    }
                    rows.append(
                        {
                            "project": workload.name,
                            "phase": phase,
                            "seconds": medians,
                            "samples": {
                                arm: len(samples) for arm, samples in values.items()
                            },
                            "combined_reduction_vs_separate_percent": 100
                            * (1 - medians["combined"] / medians["separate"]),
                            "combined_overhead_vs_tests_percent": 100
                            * (medians["combined"] / medians["tests-only"] - 1),
                        }
                    )
        return rows

    def write_results(self):
        self.output.mkdir(parents=True, exist_ok=True)
        payload = {
            "metadata": self.metadata,
            "cycles": self.cycles,
            "commands": self.samples,
            "comparisons": self.comparisons(),
            "private_cache_footprints": self.footprints,
        }
        (self.output / "results.json").write_text(json.dumps(payload, indent=2) + "\n")

    def run(self):
        if self.options.dry_run:
            print(
                json.dumps(
                    {
                        "toolchain": self.options.ohm,
                        "arms": ARMS,
                        "revisions": self.revisions,
                        "projects": [w.name for w in self.workloads],
                    },
                    indent=2,
                )
            )
            return
        self.check_disk()
        if self.output.exists() and any(self.output.iterdir()):
            raise benchmark.BenchmarkError(f"output must be empty: {self.output}")
        (self.output / "logs").mkdir(parents=True)
        self.prepare_sources()
        self.metadata = {
            "study": "same-release Clippy and test validation",
            "host": platform.node(),
            "platform": platform.platform(),
            "jobs": self.options.jobs,
            "toolchain": toolchain_identity(self.options.ohm),
            "repositories": self.revisions,
            "lint_levels": "workspace defaults in both linting arms",
            "target_scope": {
                "uv": "it integration-test target, test profile",
                "codex-core": "library test target, test profile; clippy --lib --profile test",
            },
            "settings": "private target directories; Ohm defaults; no shared build directory or trust overrides",
            "discard_completed_targets": self.discard_targets,
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        with self.managed_worktrees():
            self.metadata["quiet_preflight"] = quiet_preflight(self.output)
            for index, workload in enumerate(self.workloads):
                self.run_workflow_with_retries(workload, "test", index)
                for arm in ARMS:
                    self.footprints.append(
                        {
                            "project": workload.name,
                            "arm": arm,
                            **footprint(self.target(workload, "test", arm)),
                        }
                    )
                self.write_results()
                if self.discard_targets:
                    discard_artifacts(
                        self.output,
                        [self.target(workload, "test", arm) for arm in ARMS],
                    )
        self.metadata["finished_at"] = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
        self.write_results()


class SessionStudy(replay_sessions.Replay):
    def __init__(self, options):
        resume = options.resume
        options.resume = False
        super().__init__(options)
        self.toolchains = (("default", options.ohm), ("combined", options.ohm))
        options.resume = resume
        self.active_step = None
        if resume:
            self.restore_results()

    def environment(self, scenario, label, selector, repetition):
        env = super().environment(scenario, "ohm", selector, repetition)
        env["CARGO_TARGET_DIR"] = str(
            self.output / "targets" / scenario.project / label / str(repetition)
        )
        if not self.options.no_shared_build:
            env["CARGO_BUILD_BUILD_DIR"] = str(
                self.output
                / "shared-build"
                / scenario.project
                / label
                / str(repetition)
            )
        args = self.active_step["args"] if self.active_step else []
        applicable = args and args[0] not in ("clippy", "fmt")
        env[OPT_IN] = "true" if label == "combined" and applicable else "false"
        env["CARGO_OHM_CLIPPY_ARGS"] = ""
        return env

    def run_command(
        self, scenario, worktree, step, label, selector, repetition, index, **kwargs
    ):
        self.active_step = step
        try:
            observed = super().run_command(
                scenario, worktree, step, label, selector, repetition, index, **kwargs
            )
            observed["clippy_codegen"] = self.environment(
                scenario, label, selector, repetition
            )[OPT_IN]
            return observed
        finally:
            self.active_step = None

    def run_session(self, scenario, label, selector, repetition):
        sample = super().run_session(scenario, label, selector, repetition)
        env = self.environment(scenario, label, selector, repetition)
        paths = [Path(env["CARGO_TARGET_DIR"])]
        if shared := env.get("CARGO_BUILD_BUILD_DIR"):
            paths.append(Path(shared))
        sample["private_cache_footprints"] = {
            str(path.relative_to(self.output)): footprint(path) for path in paths
        }
        self.persist()
        if (
            getattr(self.options, "discard_targets", False)
            and scenario.project != "codex"
        ):
            discard_artifacts(self.output, paths)
        return sample

    def persist(self):
        super().persist()
        destination = self.output / "results.json"
        result = json.loads(destination.read_text())
        result["discard_completed_targets"] = getattr(
            self.options, "discard_targets", False
        )
        result["study"] = (
            "unchanged recorded sessions, same Ohm release, default versus opt-in"
        )
        result["lint_coverage"] = (
            "all recorded standalone Clippy steps retained; opt-in adds linting to compilation"
        )
        destination.write_text(json.dumps(result, indent=2) + "\n")

    def summarize(self):
        for scenario in self.scenarios:
            values = {
                label: [
                    s["wall_seconds"]
                    for s in self.samples
                    if s["project"] == scenario.project and s["toolchain"] == label
                ]
                for label, _ in self.toolchains
            }
            if all(values.values()):
                print(
                    scenario.project,
                    {key: statistics.median(value) for key, value in values.items()},
                    flush=True,
                )


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("workflows", "replay"):
        raise SystemExit(
            "usage: benchmark_clippy_codegen.py {workflows,replay} [runner options]"
        )
    mode = sys.argv.pop(1)
    sanitize_environment()
    if mode == "workflows":
        options = benchmark.parser().parse_args()
        study = WorkflowStudy(options)
    else:
        parser = replay_sessions.parser()
        parser.add_argument(
            "--discard-targets",
            action="store_true",
            help="discard completed owned targets after recording footprint inventories",
        )
        options = parser.parse_args()
        if options.feature_matrix or options.background:
            raise benchmark.BenchmarkError(
                "use a foreground process in a persistent remote session; feature matrix is a separate experiment"
            )
        study = SessionStudy(options)
        if not options.resume and not options.dry_run:
            identity = toolchain_identity(options.ohm)
            quiet_preflight(options.output_dir)
            (options.output_dir / "toolchain.json").write_text(
                json.dumps(identity, indent=2) + "\n"
            )
    study.run()


if __name__ == "__main__":
    try:
        main()
    except benchmark.BenchmarkError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
