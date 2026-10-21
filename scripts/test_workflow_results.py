"""Reject misleading workflow summaries and keep complete-sequence medians."""

import copy
import dataclasses
import json
import statistics
import unittest

from benchmark_workflows import WORKFLOWS, project_definitions
import workflow_results


def synthetic_runs():
    """Small artificial measurements for exercising report validation only."""
    runs = []
    selectors = {"stock": "1.99.0", "ohm": "ohm-1.99.0-5"}
    for project, definition in project_definitions().items():
        run = {
            "configuration": {
                "projects": {project: definition},
                "workflows": {
                    name: dataclasses.asdict(value) for name, value in WORKFLOWS.items()
                },
                "toolchains": selectors,
                "jobs": 8,
                "repetitions": 3,
                "require_idle": True,
                "quiet_seconds": 30,
                "idle_preflight": "after_warmup",
                "source_normalization": "ohm_rustfmt_before_warmup",
                "cpu_accounting": "host_busy_minus_process_tree",
                "failure_policy": "record_and_continue",
                "runner_sha256": {"benchmark_workflows.py": "a" * 64},
            },
            "metadata": {
                "host": project,
                "started_at": 1,
                "finished_at": 2,
                "toolchains": {
                    lane: {
                        name: {"sha256": "b" * 64, "version": f"synthetic {selector}"}
                        | (
                            {
                                "libraries": {
                                    "librustc_driver.so": "c" * 64,
                                    "libLLVM.so": "d" * 64,
                                }
                            }
                            if name == "rustc"
                            else {}
                        )
                        for name in ("cargo", "rustc", "rustfmt", "clippy-driver")
                    }
                    for lane, selector in selectors.items()
                },
            },
            "samples": [],
            "discarded": [],
            "failures": [],
        }
        for workflow_id, workflow in WORKFLOWS.items():
            for repetition in range(3):
                for lane, selector in selectors.items():
                    durations = ((1, 20, 2), (20, 1, 2), (2, 2, 20))[repetition]
                    factor = 1 if lane == "stock" else 0.5

                    def command(name, seconds):
                        return {
                            "name": name,
                            "command": [
                                "cargo",
                                f"+{selector}",
                                *definition["commands"][name],
                            ],
                            "wall_seconds": seconds,
                            "returncode": 0,
                            "tests_started": int(name == "test"),
                            "external_compilation": [],
                            "log": "/tmp/logs/test.log",
                            "log_sha256": "a" * 64,
                        }

                    commands = [
                        command(name, durations[index] * factor)
                        for index, name in enumerate(workflow.commands)
                    ]
                    command_total = sum(row["wall_seconds"] for row in commands)
                    run["samples"].append(
                        {
                            "project": project,
                            "workflow": workflow_id,
                            "toolchain": lane,
                            "selector": selector,
                            "repetition": repetition,
                            "wall_seconds": command_total + 0.5,
                            "command_seconds": command_total,
                            "edit_seconds": 0.1 if workflow.edit else 0,
                            "commands": commands,
                            "warmups": [command(name, 100) for name in workflow.warmup],
                            "normalization": command("fmt", 1)
                            | {
                                "command": [
                                    "cargo",
                                    "+ohm-1.99.0-5",
                                    *definition["commands"]["fmt"],
                                ]
                            },
                            "baseline_diff_sha256": "b" * 64,
                            "edited_diff_sha256": ("c" if workflow.edit else "b") * 64,
                            "target_directory": f"/tmp/{project}/{workflow_id}/{lane}/{repetition}",
                            "preflight": [
                                {
                                    "idle_percent": 99,
                                    "iowait_percent": 0,
                                    "steal_percent": 0,
                                }
                            ],
                            "cpu": {
                                "path": "/tmp/logs/cpu.jsonl",
                                "sha256": "d" * 64,
                                "intervals": 20,
                            },
                        }
                    )
        # JSON roundtrip mirrors the runner's on-disk tuple representation.
        runs.append(json.loads(json.dumps(run)))
    return runs


class WorkflowReportTests(unittest.TestCase):
    def setUp(self):
        self.report = workflow_results.build_report(synthetic_runs())

    def test_uses_median_of_complete_sequences(self):
        row = next(
            row
            for row in self.report["comparisons"]
            if row["project"] == "ruff" and row["workflow"] == "check-build-check"
        )
        self.assertEqual(row["stock_seconds"], statistics.median([23.5, 23.5, 24.5]))
        self.assertEqual(len(workflow_results.table_rows(self.report)), 15)

    def test_rejects_incomplete_unpaired_or_misreported_results(self):
        changes = [
            lambda r: r["runs"][0]["samples"].pop(),
            lambda r: r["runs"][0]["samples"].append(
                copy.deepcopy(r["runs"][0]["samples"][0])
            ),
            lambda r: r["runs"][0]["samples"][0].update(wall_seconds=0.1),
            lambda r: r["runs"][0]["samples"][0].update(wall_seconds=float("nan")),
            lambda r: r["runs"][0]["samples"][0].update(edited_diff_sha256="e" * 64),
            lambda r: r["runs"][0]["samples"][0]["commands"][0].update(tests_started=0),
            lambda r: r["runs"][0]["samples"][0]["commands"][0].update(
                external_compilation=["rustc"]
            ),
            lambda r: r["runs"][0]["configuration"].update(require_idle=False),
            lambda r: r["runs"][0]["configuration"].pop("idle_preflight"),
            lambda r: r["runs"][0]["configuration"].pop("source_normalization"),
            lambda r: r["runs"][0]["metadata"].pop("finished_at"),
            lambda r: r["runs"][0]["metadata"]["toolchains"]["ohm"]["rustc"].pop(
                "libraries"
            ),
            lambda r: r["comparisons"][0].update(stock_seconds=1),
        ]
        for change in changes:
            with self.subTest(change=change):
                report = copy.deepcopy(self.report)
                change(report)
                with self.assertRaises(ValueError):
                    workflow_results.validate(report)

    def test_unreleased_build_must_match_its_source_revision(self):
        for build, label, cargo_revision in (
            ("workflow-cache-fix", "fix", None),
            ("workflow-overhead", "fixes", None),
            ("workflow-overhead", "fixes", "3" * 40),
            ("edited-check-compact2", "fixes", "3" * 40),
            ("edited-check-sso", "fixes", "3" * 40),
            ("uv-fmt", "fixes", "3" * 40),
        ):
            with self.subTest(build=build, cargo_revision=cargo_revision):
                runs = synthetic_runs()
                revision = "a" * 40
                compiler_release = f"ohm-1.99.0-5-{build}-{revision[:12]}"
                selector = compiler_release
                if cargo_revision:
                    selector += f"-cargo-{cargo_revision[:12]}"
                measured_release = compiler_release.replace(
                    "uv-fmt", "edited-check-sso"
                )
                for run in runs:
                    run["configuration"]["toolchains"]["ohm"] = selector
                    run["metadata"]["toolchains"]["ohm"]["rustc"]["version"] = (
                        f"rustc ({measured_release})\ncommit-hash: {revision}"
                    )
                    if cargo_revision:
                        run["metadata"]["toolchains"]["ohm"]["cargo"]["version"] = (
                            f"cargo\ncommit-hash: {cargo_revision}"
                        )
                    if measured_release != compiler_release:
                        tools = run["metadata"]["toolchains"]["ohm"]
                        tools["rustc"]["build_provenance"] = {
                            "toolchain": selector,
                            "rustc_version": tools["rustc"]["version"],
                            "cargo_version": tools["cargo"]["version"],
                            "sources": {"rust": revision, "cargo": cargo_revision},
                            "binaries_sha256": {
                                **{
                                    "bin/" + name: tool["sha256"]
                                    for name, tool in tools.items()
                                },
                                **{
                                    "lib/" + name: digest
                                    for name, digest in tools["rustc"][
                                        "libraries"
                                    ].items()
                                },
                            },
                        }
                    for sample in run["samples"]:
                        sample["normalization"]["command"][1] = f"+{selector}"
                        if sample["toolchain"] == "ohm":
                            sample["selector"] = selector
                            for command in [*sample["commands"], *sample["warmups"]]:
                                command["command"][1] = f"+{selector}"
                report = workflow_results.build_report(runs)
                self.assertEqual(report["ohm_source_revision"], revision)
                self.assertEqual(
                    workflow_results.toolchain_label(report), f"1.99.0-5 + {label}"
                )
                if measured_release != compiler_release:
                    for field, value in (
                        ("toolchain", "ohm-1.99.0-5"),
                        ("rustc_version", "different compiler"),
                        ("cargo_version", "different Cargo"),
                        ("sources", {}),
                        ("binaries_sha256", {}),
                    ):
                        changed = copy.deepcopy(report)
                        for run in changed["runs"]:
                            run["metadata"]["toolchains"]["ohm"]["rustc"][
                                "build_provenance"
                            ][field] = value
                        with self.assertRaises(ValueError):
                            workflow_results.validate(changed)
                if cargo_revision:
                    self.assertEqual(
                        report["ohm_cargo_source_revision"], cargo_revision
                    )
                    changed = copy.deepcopy(report)
                    changed["ohm_cargo_source_revision"] = "4" * 40
                    with self.assertRaises(ValueError):
                        workflow_results.validate(changed)
                    changed = copy.deepcopy(report)
                    changed["runs"][0]["metadata"]["toolchains"]["ohm"]["cargo"][
                        "version"
                    ] = "cargo\ncommit-hash: " + "4" * 40
                    with self.assertRaises(ValueError):
                        workflow_results.validate(changed)
                report["ohm_source_revision"] = "2" * 40
                with self.assertRaises(ValueError):
                    workflow_results.validate(report)

    def test_failed_execution_prevents_a_success_only_speedup(self):
        runs = synthetic_runs()
        sample = runs[0]["samples"].pop(1)
        failure = {
            key: sample[key]
            for key in (
                "project",
                "workflow",
                "toolchain",
                "selector",
                "repetition",
                "baseline_diff_sha256",
                "edited_diff_sha256",
                "target_directory",
                "preflight",
                "cpu",
            )
        }
        failure.update(
            failed_command=sample["commands"][0]
            | {
                "returncode": 101,
                "tests_started": 0,
                "phase": "session",
                "index": 1,
            },
            diagnostics=[],
        )
        runs[0]["failures"].append(failure)
        report = workflow_results.build_report(runs)
        row = report["comparisons"][0]
        self.assertEqual(row["ohm_failures"], 1)
        self.assertIsNone(row["ohm_seconds"])
        self.assertIsNone(row["percent_saved"])
        self.assertEqual(
            workflow_results.table_rows(report)[0][3:], ["Failed (1/3)", "—"]
        )
        for change in (
            lambda r: r["runs"][0]["failures"].clear(),
            lambda r: r["runs"][0]["failures"][0]["failed_command"].update(
                returncode=0
            ),
            lambda r: r["runs"][0]["failures"][0]["failed_command"].update(
                phase="warmup", index=0
            ),
            lambda r: r["comparisons"][0].update(ohm_seconds=1),
        ):
            changed = copy.deepcopy(report)
            change(changed)
            with self.assertRaises(ValueError):
                workflow_results.validate(changed)


if __name__ == "__main__":
    unittest.main()
