#!/usr/bin/env python3
"""Run the published workflow and feature matrices with Clippy/codegen on or off."""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import shutil
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import benchmark
import benchmark_clippy_codegen as campaign
import replay_sessions


class WorkflowMatrix(benchmark.Study):
    def __init__(self, options):
        super().__init__(options)
        self.toolchains = (("default", options.ohm), ("combined", options.ohm))

    @contextlib.contextmanager
    def managed_worktrees(self):
        with super().managed_worktrees():
            self.metadata["quiet_preflight"] = campaign.quiet_preflight(self.output)
            yield

    def execute(
        self, workload, workflow, label, selector, *, extra_environment=None, **kwargs
    ):
        env = dict(extra_environment or {})
        env[campaign.OPT_IN] = (
            "true"
            if label == "combined" and workflow not in ("clippy", "fmt")
            else "false"
        )
        env["CARGO_OHM_CLIPPY_ARGS"] = ""
        super().execute(
            workload, workflow, label, selector, extra_environment=env, **kwargs
        )
        if workflow == "fmt" and kwargs.get("phase") == "warmup":
            cache = Path(env["OHM_INCREMENTAL_FMT_CACHE_DIR"])
            if not any(path.is_file() for path in cache.glob("*.json")):
                raise benchmark.BenchmarkError(
                    "Ohm incremental formatting did not publish a cache snapshot: "
                    f"{cache}"
                )
        if kwargs.get("record", True):
            self.samples[-1]["clippy_codegen"] = env[campaign.OPT_IN]
            if workflow == "build-check":
                target = kwargs.get("target_directory") or self.target(
                    workload, workflow, label
                )
                self.samples[-1]["registry_build_ready"] = (
                    target / ".ohm-built-registry-ready"
                ).is_file()
            self.write_results()

    def run_shared_build(self, workload, index):
        # Both arms run Ohm, so both share registry artifacts between worktrees.
        workload = dataclasses.replace(
            workload, package=workload.dependency.crate, direct=workload.dependency
        )
        workflow = "shared-build"
        cargo = shutil.which("cargo")
        if cargo is None or not Path(cargo).is_absolute():
            raise benchmark.BenchmarkError(
                "shared builds require an absolute Cargo executable"
            )
        executable_path = os.pathsep.join(
            dict.fromkeys((str(Path(cargo).parent), "/usr/bin", "/bin"))
        )
        with self.managed_shared_worktrees(workload) as worktrees:
            for label, selector in self.ordered_toolchains(index):
                root = self.target(workload, workflow, label)
                shared = root / "shared-build"
                self.execute(
                    workload,
                    workflow,
                    label,
                    selector,
                    phase="seed",
                    repetition=0,
                    expected_crate=workload.package,
                    record=False,
                    target_directory=root / "primary-target",
                    extra_environment={
                        "CARGO_BUILD_BUILD_DIR": str(shared),
                        "PATH": executable_path,
                    },
                )
                if (
                    not (shared / ".ohm-shared-registry-cache-v1").is_file()
                    or not (shared / "debug/build/registries").is_dir()
                ):
                    raise benchmark.BenchmarkError(
                        f"Ohm registry artifacts were not shared: {shared}"
                    )
            with contextlib.ExitStack() as cleanup:
                for label, _ in self.toolchains:
                    edit = cleanup.enter_context(
                        benchmark.reversible_edit(worktrees[label], workload.direct)
                    )
                    edit(True)
                for label, selector in self.ordered_toolchains(index):
                    root = self.target(workload, workflow, label)
                    self.execute(
                        workload,
                        workflow,
                        label,
                        selector,
                        phase="reuse",
                        repetition=0,
                        expected_crate=workload.package,
                        worktree=worktrees[label],
                        target_directory=root / "secondary-target",
                        extra_environment={
                            "CARGO_BUILD_BUILD_DIR": str(root / "shared-build"),
                            "PATH": executable_path,
                        },
                    )

    def comparisons(self):
        grouped = defaultdict(list)
        for sample in self.samples:
            if sample["valid"]:
                grouped[
                    sample["project"],
                    sample["workflow"],
                    sample["phase"],
                    sample["toolchain"],
                ].append(sample["wall_seconds"])
        rows = []
        for workload in self.workloads:
            for workflow in (*benchmark.WORKFLOWS, *self.feature_workflows(workload)):
                for phase in benchmark.WORKFLOW_PHASES[workflow]:
                    values = {
                        label: grouped[workload.name, workflow, phase, label]
                        for label, _ in self.toolchains
                    }
                    if all(values.values()):
                        medians = {
                            label: statistics.median(samples)
                            for label, samples in values.items()
                        }
                        rows.append(
                            {
                                "project": workload.name,
                                "workflow": workflow,
                                "phase": phase,
                                "seconds": medians,
                                "samples": {
                                    label: len(samples)
                                    for label, samples in values.items()
                                },
                                "control": workflow in ("clippy", "fmt"),
                                "combined_reduction_percent": 100
                                * (1 - medians["combined"] / medians["default"]),
                            }
                        )
        return rows

    def write_results(self):
        rows = self.comparisons()
        metadata = dict(
            self.metadata,
            study="published workflow matrix, same Ohm release with opt-in on or off",
            shared_build="enabled identically for both arms in the shared-worktree workflow",
            controls=["standalone Clippy", "formatting"],
        )
        (self.output / "results.json").write_text(
            json.dumps(
                {"metadata": metadata, "samples": self.samples, "comparisons": rows},
                indent=2,
            )
            + "\n"
        )
        lines = [
            "# Ohm Clippy/codegen workflow matrix",
            "",
            "| Project | Workflow | Phase | Default | Opt-in |",
            "| --- | --- | --- | ---: | ---: |",
        ]
        for row in rows:
            lines.append(
                f"| {row['project']} | {row['workflow']} | {row['phase']} | {row['seconds']['default']:.3f}s | {row['seconds']['combined']:.3f}s |"
            )
        (self.output / "summary.md").write_text("\n".join(lines) + "\n")


class AblationMatrix(campaign.SessionStudy):
    def __init__(self, options):
        super().__init__(options)
        self.options.feature_matrix = True
        self.toolchains = tuple(
            (f"{arm}:{feature}", options.ohm)
            for feature, _ in replay_sessions.FEATURE_MATRIX
            for arm in ("default", "combined")
        )

    def environment(self, scenario, label, selector, repetition):
        arm, feature = label.split(":", 1)
        env = super().environment(scenario, arm, selector, repetition)
        env["CARGO_TARGET_DIR"] = str(
            self.output / "targets" / scenario.project / arm / feature / str(repetition)
        )
        if not self.options.no_shared_build:
            env["CARGO_BUILD_BUILD_DIR"] = str(
                self.output
                / "shared-build"
                / scenario.project
                / arm
                / feature
                / str(repetition)
            )
        if overrides := replay_sessions.FEATURE_OVERRIDES[feature]:
            env["RUSTFLAGS"] = " ".join(overrides)
        return env

    def persist(self):
        super().persist()
        path = self.output / "results.json"
        data = json.loads(path.read_text())
        data["study"] = (
            "uv feature factorial crossed with Clippy/codegen opt-in, same Ohm release"
        )
        data["feature_factorial"] = {
            name: list(flags) for name, flags in replay_sessions.FEATURE_MATRIX
        }
        path.write_text(json.dumps(data, indent=2) + "\n")

    def run(self):
        self.check_disk()
        if self.output.exists() and any(self.output.iterdir()):
            raise benchmark.BenchmarkError(f"output must be empty: {self.output}")
        for scenario in self.scenarios:
            self.sources[scenario.project] = self.prepare_source(scenario)
        campaign.quiet_preflight(self.output)
        self.persist()
        features = [name for name, _ in replay_sessions.FEATURE_MATRIX]
        for repetition in range(self.options.repetitions):
            order = [
                features[(index + repetition) % len(features)] for index in (0, 1, 3, 2)
            ]
            arms = (
                ("default", "combined")
                if repetition % 2 == 0
                else ("combined", "default")
            )
            for scenario in self.scenarios:
                for feature in order:
                    for arm in arms:
                        self.run_session(
                            scenario, f"{arm}:{feature}", self.options.ohm, repetition
                        )
        self.summarize()


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("workflows", "ablation"):
        raise SystemExit(
            "usage: benchmark_clippy_codegen_matrix.py {workflows,ablation} [runner options]"
        )
    mode = sys.argv.pop(1)
    campaign.sanitize_environment()
    if mode == "workflows":
        options = benchmark.parser().parse_args()
        study = WorkflowMatrix(options)
        if options.dry_run:
            print(
                json.dumps(
                    {
                        "toolchains": study.toolchains,
                        "expected_cells": 216,
                        "shared_build": "both arms",
                    },
                    indent=2,
                )
            )
            return
    else:
        parser = replay_sessions.parser()
        parser.add_argument("--discard-targets", action="store_true")
        options = parser.parse_args()
        if options.resume or options.background or options.feature_matrix:
            raise benchmark.BenchmarkError(
                "the crossed factorial uses its own complete schedule"
            )
        study = AblationMatrix(options)
        if options.dry_run:
            print(
                json.dumps(
                    {
                        "toolchains": study.toolchains,
                        "repetitions": options.repetitions,
                    },
                    indent=2,
                )
            )
            return
    study.run()


if __name__ == "__main__":
    try:
        main()
    except benchmark.BenchmarkError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
