"""Verify the published matrix keeps both arms comparable."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import benchmark
import benchmark_clippy_codegen as campaign
import benchmark_clippy_codegen_matrix as matrix
import replay_sessions


class MatrixTests(unittest.TestCase):
    def test_factorial_has_all_eight_arm_feature_pairs(self):
        with tempfile.TemporaryDirectory() as directory:
            options = replay_sessions.parser().parse_args(
                ["--output-dir", directory, "--project", "uv"]
            )
            study = matrix.AblationMatrix(options)
            self.assertEqual(len(study.toolchains), 8)
            self.assertTrue(study.options.feature_matrix)
            study.active_step = {"args": ["test"]}
            scenario = study.scenarios[0]
            for feature, flags in replay_sessions.FEATURE_MATRIX:
                default = study.environment(scenario, f"default:{feature}", "ohm", 0)
                combined = study.environment(scenario, f"combined:{feature}", "ohm", 0)
                self.assertEqual(default.get("RUSTFLAGS", ""), " ".join(flags))
                self.assertEqual(
                    default.get("RUSTFLAGS", ""), combined.get("RUSTFLAGS", "")
                )
                self.assertEqual(default[campaign.OPT_IN], "false")
                self.assertEqual(combined[campaign.OPT_IN], "true")
                self.assertNotEqual(
                    default["CARGO_BUILD_BUILD_DIR"], combined["CARGO_BUILD_BUILD_DIR"]
                )
                for environment in (default, combined):
                    for name in ("CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR"):
                        self.assertNotIn(os.pathsep, environment[name])

    def test_standalone_clippy_and_formatting_are_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            options = benchmark.parser().parse_args(
                ["--output-dir", directory, "--project", "uv"]
            )
            study = matrix.WorkflowMatrix(options)

            def execute(instance, workload, workflow, label, selector, **kwargs):
                expected = "false" if workflow in ("clippy", "fmt") else "true"
                self.assertEqual(kwargs["extra_environment"][campaign.OPT_IN], expected)

            with patch.object(benchmark.Study, "execute", execute):
                for workflow in (
                    "clippy",
                    "fmt",
                    "check",
                    "test",
                    "build-check",
                    "shared-build",
                ):
                    study.execute(
                        benchmark.WORKLOADS["uv"],
                        workflow,
                        "combined",
                        "ohm",
                        record=False,
                    )

    def test_shared_build_uses_one_shared_directory_in_each_arm(self):
        with tempfile.TemporaryDirectory() as directory:
            options = benchmark.parser().parse_args(
                ["--output-dir", directory, "--project", "uv"]
            )
            study = matrix.WorkflowMatrix(options)
            calls = []

            def execute(workload, workflow, label, selector, **kwargs):
                shared = Path(kwargs["extra_environment"]["CARGO_BUILD_BUILD_DIR"])
                shared.mkdir(parents=True, exist_ok=True)
                (shared / ".ohm-shared-registry-cache-v1").touch()
                (shared / "debug/build/registries").mkdir(parents=True, exist_ok=True)
                calls.append((label, kwargs["phase"], shared))

            from contextlib import contextmanager

            @contextmanager
            def worktrees(workload):
                yield {label: Path(directory) / label for label, _ in study.toolchains}

            @contextmanager
            def edit(*args):
                yield lambda changed: None

            study.execute = execute
            study.managed_shared_worktrees = worktrees
            with patch.object(benchmark, "reversible_edit", edit):
                study.run_shared_build(benchmark.WORKLOADS["uv"], 0)
            for label, _ in study.toolchains:
                paths = [path for arm, _, path in calls if arm == label]
                self.assertEqual(len(paths), 2)
                self.assertEqual(paths[0], paths[1])
                self.assertEqual(paths[0].name, "shared-build")
            self.assertNotEqual(calls[0][2], calls[1][2])

    def test_both_arms_require_formatter_cache_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            options = benchmark.parser().parse_args(["--output-dir", directory])
            study = matrix.WorkflowMatrix(options)
            for label, _ in study.toolchains:
                cache = Path(directory) / label
                cache.mkdir()
                arguments = {
                    "phase": "warmup",
                    "record": False,
                    "extra_environment": {"OHM_INCREMENTAL_FMT_CACHE_DIR": str(cache)},
                }
                with patch.object(benchmark.Study, "execute"):
                    with self.assertRaisesRegex(
                        benchmark.BenchmarkError, "did not publish a cache snapshot"
                    ):
                        study.execute(
                            benchmark.WORKLOADS["uv"], "fmt", label, "ohm", **arguments
                        )
                    (cache / "snapshot.json").write_text("{}")
                    study.execute(
                        benchmark.WORKLOADS["uv"], "fmt", label, "ohm", **arguments
                    )

    def test_both_arms_record_build_to_check_registry_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            options = benchmark.parser().parse_args(["--output-dir", directory])
            study = matrix.WorkflowMatrix(options)
            for label, _ in study.toolchains:
                target = Path(directory) / label
                target.mkdir()
                for ready in (False, True):
                    if ready:
                        (target / ".ohm-built-registry-ready").touch()
                    study.samples.append({})
                    with (
                        patch.object(benchmark.Study, "execute"),
                        patch.object(study, "write_results"),
                    ):
                        study.execute(
                            benchmark.WORKLOADS["uv"],
                            "build-check",
                            label,
                            "ohm",
                            target_directory=target,
                        )
                    self.assertIs(study.samples[-1]["registry_build_ready"], ready)


if __name__ == "__main__":
    unittest.main()
