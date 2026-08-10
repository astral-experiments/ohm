"""Fast, build-free regression tests for the Ohm benchmark runner."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("benchmark.py")
SPEC = importlib.util.spec_from_file_location("ohm_benchmark", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to import benchmark runner: {SCRIPT}")
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


class CommandOutputTests(unittest.TestCase):
    def test_reports_captured_error_without_exposing_url_credentials(self) -> None:
        command = ["git", "clone", "https://github.com/astral-sh/uv.git"]
        failure = subprocess.CalledProcessError(
            128,
            command,
            stderr="fatal: unable to access https://secret-token@github.com/astral-sh/uv.git: TLS handshake timeout",
        )

        with mock.patch.object(benchmark.subprocess, "run", side_effect=failure):
            with self.assertRaises(benchmark.BenchmarkError) as raised:
                benchmark.command_output(command)

        message = str(raised.exception)
        self.assertIn("TLS handshake timeout", message)
        self.assertIn("https://<redacted>@github.com/astral-sh/uv.git", message)
        self.assertNotIn("secret-token", message)


class CompilerInterferenceTests(unittest.TestCase):
    def test_ignores_only_compilers_in_the_benchmark_process_tree(self) -> None:
        processes = "\n".join(
            [
                "10 1 uv",
                "20 10 python3",
                "30 20 cargo",
                "40 30 rustc",
                "50 1 cargo-nextest",
                "60 50 cargo",
                "70 60 rustc",
                "80 1 clang",
                "90 1 unrelated",
                "100 1 rustfmt",
                "110 1 cargo-fmt",
            ]
        )

        with mock.patch.object(benchmark, "command_output", return_value=processes):
            active = benchmark.competing_processes(owner=20)

        self.assertEqual(
            active,
            [
                "50 cargo-nextest",
                "60 cargo",
                "70 rustc",
                "80 clang",
                "100 rustfmt",
                "110 cargo-fmt",
            ],
        )

    def test_process_inspection_fails_closed(self) -> None:
        with mock.patch.object(
            benchmark,
            "command_output",
            side_effect=benchmark.BenchmarkError("process visibility denied"),
        ):
            with self.assertRaisesRegex(benchmark.BenchmarkError, "visibility denied"):
                benchmark.competing_processes(owner=20)

        for output in ("", "invalid process"):
            with self.subTest(output=output):
                with mock.patch.object(
                    benchmark, "command_output", return_value=output
                ):
                    with self.assertRaises(benchmark.BenchmarkError):
                        benchmark.competing_processes(owner=20)

    def test_idle_machine_starts_without_waiting(self) -> None:
        study = object.__new__(benchmark.Study)
        study.options = benchmark.parser().parse_args(["--require-idle"])

        with (
            mock.patch.object(benchmark, "competing_processes", return_value=[]),
            mock.patch.object(benchmark.time, "sleep") as sleep,
        ):
            study.wait_until_idle()

        sleep.assert_not_called()

    def test_busy_machine_times_out_without_modifying_processes(self) -> None:
        study = object.__new__(benchmark.Study)
        study.options = benchmark.parser().parse_args(
            ["--require-idle", "--idle-timeout", "600"]
        )

        with (
            mock.patch.object(
                benchmark, "competing_processes", return_value=["100 cargo"]
            ),
            mock.patch.object(benchmark.time, "monotonic", side_effect=[0, 601]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            with self.assertRaisesRegex(benchmark.BenchmarkError, "timed out"):
                study.wait_until_idle()

    def test_overlapping_compiler_invalidates_and_persists_the_sample(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results"
            (output / "logs").mkdir(parents=True)
            worktree = Path(directory) / "source"
            worktree.mkdir()
            workload = benchmark.WORKLOADS["uv"]
            study = object.__new__(benchmark.Study)
            study.options = benchmark.parser().parse_args(
                ["--require-idle", "--output-dir", str(output)]
            )
            study.output = output
            study.workloads = [workload]
            study.toolchains = (("stock", "1.97.1"), ("ohm", "ohm"))
            study.worktrees = {("uv", "stock"): worktree}
            study.samples = []
            study.metadata = {}
            result = subprocess.CompletedProcess(
                [], 0, stdout="    Finished dev profile\n"
            )

            with (
                mock.patch.object(study, "wait_until_idle"),
                mock.patch.object(
                    benchmark, "competing_processes", return_value=["100 cargo"]
                ),
                mock.patch.object(benchmark.subprocess, "run", return_value=result),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                with self.assertRaisesRegex(
                    benchmark.ContaminatedBenchmarkError, "overlapped"
                ):
                    study.execute(
                        workload,
                        "check",
                        "stock",
                        "1.97.1",
                        phase="noop",
                        repetition=0,
                        expected_crate=None,
                    )

            self.assertFalse(study.samples[0]["valid"])
            self.assertEqual(study.samples[0]["external_compilation"], ["100 cargo"])
            self.assertTrue((output / "results.json").is_file())

    def test_real_failures_remain_terminal_when_a_compiler_also_overlaps(self) -> None:
        for returncode, standard_output, expected in (
            (101, "compilation failed\n", "exited 101"),
            (0, "    Finished dev profile\n", "was not rebuilt"),
        ):
            with self.subTest(returncode=returncode):
                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / "results"
                    (output / "logs").mkdir(parents=True)
                    worktree = Path(directory) / "source"
                    worktree.mkdir()
                    workload = benchmark.WORKLOADS["uv"]
                    study = object.__new__(benchmark.Study)
                    study.options = benchmark.parser().parse_args(
                        ["--require-idle", "--output-dir", str(output)]
                    )
                    study.output = output
                    study.workloads = [workload]
                    study.toolchains = (("stock", "1.97.1"), ("ohm", "ohm"))
                    study.worktrees = {("uv", "stock"): worktree}
                    study.samples = []
                    study.metadata = {}
                    result = subprocess.CompletedProcess(
                        [], returncode, stdout=standard_output
                    )

                    with (
                        mock.patch.object(study, "wait_until_idle"),
                        mock.patch.object(
                            benchmark,
                            "competing_processes",
                            return_value=["100 cargo"],
                        ),
                        mock.patch.object(
                            benchmark.subprocess, "run", return_value=result
                        ),
                        contextlib.redirect_stdout(io.StringIO()),
                        self.assertRaisesRegex(
                            benchmark.BenchmarkError, expected
                        ) as raised,
                    ):
                        study.execute(
                            workload,
                            "check",
                            "stock",
                            "1.97.1",
                            phase="dependency",
                            repetition=0,
                            expected_crate="uv-normalize",
                        )

                    self.assertNotIsInstance(
                        raised.exception, benchmark.ContaminatedBenchmarkError
                    )
                    self.assertFalse(study.samples[0]["valid"])
                    self.assertEqual(
                        study.samples[0]["external_compilation"], ["100 cargo"]
                    )

    def test_package_cache_contention_invalidates_and_retries_as_contamination(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results"
            (output / "logs").mkdir(parents=True)
            worktree = Path(directory) / "source"
            worktree.mkdir()
            workload = benchmark.WORKLOADS["uv"]
            arguments = benchmark.parser().parse_args(
                ["--project", "uv", "--output-dir", str(output)]
            )
            study = benchmark.Study(arguments)
            study.worktrees["uv", "stock"] = worktree
            result = subprocess.CompletedProcess(
                [], 0, stdout="Blocking waiting for file lock on package cache\n"
            )

            with (
                mock.patch.object(benchmark.subprocess, "run", return_value=result),
                contextlib.redirect_stdout(io.StringIO()),
                self.assertRaisesRegex(
                    benchmark.ContaminatedBenchmarkError, "cache contention"
                ),
            ):
                study.execute(
                    workload,
                    "check",
                    "stock",
                    "1.97.1",
                    phase="noop",
                    repetition=0,
                    expected_crate=None,
                )

            self.assertEqual(len(study.samples), 1)
            self.assertFalse(study.samples[0]["valid"])

    def test_nonzero_package_cache_contention_retries_the_entire_workflow(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results"
            (output / "logs").mkdir(parents=True)
            worktree = Path(directory) / "source"
            worktree.mkdir()
            workload = benchmark.WORKLOADS["uv"]
            arguments = benchmark.parser().parse_args(
                ["--project", "uv", "--output-dir", str(output)]
            )
            study = benchmark.Study(arguments)
            study.worktrees["uv", "stock"] = worktree
            result = subprocess.CompletedProcess(
                [], 101, stdout="Blocking waiting for file lock on package cache\n"
            )

            with (
                mock.patch.object(benchmark.subprocess, "run", return_value=result),
                contextlib.redirect_stdout(io.StringIO()),
                self.assertRaisesRegex(
                    benchmark.ContaminatedBenchmarkError, "cache contention"
                ),
            ):
                study.execute(
                    workload,
                    "check",
                    "stock",
                    "1.97.1",
                    phase="noop",
                    repetition=0,
                    expected_crate=None,
                )

            self.assertEqual(study.samples[0]["returncode"], 101)
            self.assertFalse(study.samples[0]["valid"])

    def test_real_failure_after_a_lock_warning_remains_terminal(self) -> None:
        for diagnostic in (
            "error[E0308]: mismatched types",
            "error[E0425]: cannot find value `lock` in this scope",
            "error: could not compile `uv`",
            "Diff in /workspace/src/lib.rs:1:",
        ):
            with self.subTest(diagnostic=diagnostic):
                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / "results"
                    (output / "logs").mkdir(parents=True)
                    worktree = Path(directory) / "source"
                    worktree.mkdir()
                    workload = benchmark.WORKLOADS["uv"]
                    arguments = benchmark.parser().parse_args(
                        ["--project", "uv", "--output-dir", str(output)]
                    )
                    study = benchmark.Study(arguments)
                    study.worktrees["uv", "stock"] = worktree
                    result = subprocess.CompletedProcess(
                        [],
                        101,
                        stdout=(
                            "Blocking waiting for file lock on package cache\n"
                            f"{diagnostic}\n"
                        ),
                    )

                    with (
                        mock.patch.object(
                            benchmark.subprocess, "run", return_value=result
                        ),
                        contextlib.redirect_stdout(io.StringIO()),
                        self.assertRaisesRegex(
                            benchmark.BenchmarkError, "exited 101"
                        ) as raised,
                    ):
                        study.execute(
                            workload,
                            "check",
                            "stock",
                            "1.97.1",
                            phase="noop",
                            repetition=0,
                            expected_crate=None,
                        )

                    self.assertNotIsInstance(
                        raised.exception, benchmark.ContaminatedBenchmarkError
                    )

    def test_package_cache_lock_timeout_is_contamination_but_real_timeout_is_not(
        self,
    ) -> None:
        for captured, exception in (
            (
                b"Blocking waiting for file lock on package cache\n",
                benchmark.ContaminatedBenchmarkError,
            ),
            (b"Compiling uv v0.0.0\n", benchmark.BenchmarkError),
            (
                b"Blocking waiting for file lock on package cache\n"
                b"error[E0308]: mismatched types\n",
                benchmark.BenchmarkError,
            ),
        ):
            with self.subTest(captured=captured):
                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / "results"
                    (output / "logs").mkdir(parents=True)
                    worktree = Path(directory) / "source"
                    worktree.mkdir()
                    workload = benchmark.WORKLOADS["uv"]
                    arguments = benchmark.parser().parse_args(
                        ["--project", "uv", "--output-dir", str(output)]
                    )
                    study = benchmark.Study(arguments)
                    study.worktrees["uv", "stock"] = worktree
                    timeout = subprocess.TimeoutExpired(
                        ["cargo"], timeout=1, output=captured
                    )

                    with (
                        mock.patch.object(
                            benchmark.subprocess, "run", side_effect=timeout
                        ),
                        contextlib.redirect_stdout(io.StringIO()),
                        self.assertRaises(exception) as raised,
                    ):
                        study.execute(
                            workload,
                            "check",
                            "stock",
                            "1.97.1",
                            phase="noop",
                            repetition=0,
                            expected_crate=None,
                        )

                    if exception is benchmark.BenchmarkError:
                        self.assertNotIsInstance(
                            raised.exception, benchmark.ContaminatedBenchmarkError
                        )

    def test_cache_lock_diagnostics_do_not_match_unrelated_lock_identifiers(
        self,
    ) -> None:
        blocked = "Blocking waiting for file lock on package cache\n"
        self.assertTrue(benchmark.cache_contention_only(blocked))
        self.assertTrue(
            benchmark.cache_contention_only(
                blocked + "error: failed to lock package cache\n"
            )
        )
        for diagnostic in (
            "error[E0425]: cannot find value `lock` in this scope",
            "error: function `lock` returned the wrong type",
            "Diff in /workspace/lock.rs:1:",
        ):
            with self.subTest(diagnostic=diagnostic):
                self.assertFalse(
                    benchmark.cache_contention_only(blocked + diagnostic + "\n")
                )


class WorkflowRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.output = Path(temporary_directory.name) / "results"
        self.output.mkdir()
        arguments = benchmark.parser().parse_args(
            [
                "--project",
                "uv",
                "--require-idle",
                "--contention-retries",
                "2",
                "--quiet-seconds",
                "10",
                "--output-dir",
                str(self.output),
            ]
        )
        self.study = benchmark.Study(arguments)
        self.workload = benchmark.WORKLOADS["uv"]
        self.calls = 0

    def sample(self, *, valid: bool, label: str = "stock") -> dict[str, object]:
        return {
            "project": self.workload.name,
            "workflow": "check",
            "phase": "cold",
            "toolchain": label,
            "wall_seconds": 1.0,
            "valid": valid,
        }

    def test_discards_full_attempt_and_restarts_both_targets_from_cold(self) -> None:
        stock = self.study.target(self.workload, "check", "stock")
        ohm = self.study.target(self.workload, "check", "ohm")
        unrelated = self.study.target(self.workload, "clippy", "stock")
        unrelated.mkdir(parents=True)
        sentinel = unrelated / "preserve"
        sentinel.write_text("unrelated workflow", encoding="utf-8")

        def execute_attempt(*_: object) -> None:
            self.calls += 1
            if self.calls == 1:
                stock.mkdir(parents=True)
                ohm.mkdir(parents=True)
                self.study.samples.extend(
                    [self.sample(valid=True), self.sample(valid=False, label="ohm")]
                )
                raise benchmark.ContaminatedBenchmarkError("overlapped: 123 cargo")
            self.assertFalse(stock.exists())
            self.assertFalse(ohm.exists())
            self.study.samples.extend(
                [self.sample(valid=True), self.sample(valid=True, label="ohm")]
            )

        with (
            mock.patch.object(self.study, "run_workflow", side_effect=execute_attempt),
            mock.patch.object(self.study, "wait_until_idle") as wait,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.study.run_workflow_with_retries(self.workload, "check", 0)

        self.assertEqual(self.calls, 2)
        self.assertEqual(
            [sample["valid"] for sample in self.study.samples],
            [False, False, True, True],
        )
        for sample in self.study.samples[:2]:
            self.assertIn("entire workflow", str(sample["discard_reason"]))
        self.assertNotIn("discard_reason", self.study.samples[2])
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "unrelated workflow")
        self.assertEqual(
            wait.call_args_list,
            [mock.call(quiet_seconds=10), mock.call(quiet_seconds=10)],
        )
        self.assertEqual(self.study.comparisons()[0]["samples"], 1)

    def test_stops_after_bounded_contamination_retries(self) -> None:
        def contaminated(*_: object) -> None:
            self.calls += 1
            self.study.samples.append(self.sample(valid=False))
            raise benchmark.ContaminatedBenchmarkError("persistent overlap")

        with (
            mock.patch.object(self.study, "run_workflow", side_effect=contaminated),
            mock.patch.object(self.study, "wait_until_idle"),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(
                benchmark.ContaminatedBenchmarkError, "persistent overlap"
            ),
        ):
            self.study.run_workflow_with_retries(self.workload, "check", 0)

        self.assertEqual(self.calls, 3)
        self.assertTrue(all(not sample["valid"] for sample in self.study.samples))

    def test_real_build_failures_never_retry_or_remove_artifacts(self) -> None:
        target = self.study.target(self.workload, "check", "stock")
        target.mkdir(parents=True)
        artifact = target / "preserve"
        artifact.write_text("diagnostic artifact", encoding="utf-8")

        with (
            mock.patch.object(
                self.study,
                "run_workflow",
                side_effect=benchmark.BenchmarkError("real compilation failure"),
            ) as workflow,
            mock.patch.object(self.study, "wait_until_idle"),
            self.assertRaisesRegex(benchmark.BenchmarkError, "real compilation"),
        ):
            self.study.run_workflow_with_retries(self.workload, "check", 0)

        workflow.assert_called_once()
        self.assertEqual(artifact.read_text(encoding="utf-8"), "diagnostic artifact")

    def test_retry_rejects_symlinked_target_without_touching_destination(self) -> None:
        target = self.study.target(self.workload, "check", "stock")
        outside = self.output.parent / "outside"
        outside.mkdir()
        sentinel = outside / "preserve"
        sentinel.write_text("user artifact", encoding="utf-8")
        target.parent.mkdir(parents=True)
        target.symlink_to(outside, target_is_directory=True)

        with (
            mock.patch.object(
                self.study,
                "run_workflow",
                side_effect=benchmark.ContaminatedBenchmarkError("overlap"),
            ),
            mock.patch.object(self.study, "wait_until_idle"),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(benchmark.BenchmarkError, "unsafe"),
        ):
            self.study.run_workflow_with_retries(self.workload, "check", 0)

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "user artifact")

    def test_discards_only_completed_workflow_targets_when_requested(self) -> None:
        self.study.options.discard_targets = True
        stock = self.study.target(self.workload, "check", "stock")
        ohm = self.study.target(self.workload, "check", "ohm")
        unrelated = self.study.target(self.workload, "clippy", "stock")
        unrelated.mkdir(parents=True)
        sentinel = unrelated / "preserve"
        sentinel.write_text("unrelated workflow", encoding="utf-8")

        def complete(*_: object) -> None:
            stock.mkdir(parents=True)
            ohm.mkdir(parents=True)
            self.study.samples.extend(
                [self.sample(valid=True), self.sample(valid=True, label="ohm")]
            )
            self.study.write_results()

        with (
            mock.patch.object(self.study, "run_workflow", side_effect=complete),
            mock.patch.object(self.study, "wait_until_idle"),
        ):
            self.study.run_workflow_with_retries(self.workload, "check", 0)

        self.assertFalse(stock.exists())
        self.assertFalse(ohm.exists())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "unrelated workflow")
        self.assertTrue((self.output / "results.json").is_file())
        self.assertTrue((self.output / "summary.md").is_file())
        self.assertEqual(self.study.comparisons()[0]["samples"], 1)

    def test_retains_completed_targets_by_default(self) -> None:
        stock = self.study.target(self.workload, "check", "stock")
        ohm = self.study.target(self.workload, "check", "ohm")

        def complete(*_: object) -> None:
            stock.mkdir(parents=True)
            ohm.mkdir(parents=True)

        with (
            mock.patch.object(self.study, "run_workflow", side_effect=complete),
            mock.patch.object(self.study, "wait_until_idle"),
        ):
            self.study.run_workflow_with_retries(self.workload, "check", 0)

        self.assertTrue(stock.is_dir())
        self.assertTrue(ohm.is_dir())

    def test_completed_workflow_refuses_to_discard_symlinked_target(self) -> None:
        self.study.options.discard_targets = True
        stock = self.study.target(self.workload, "check", "stock")
        outside = self.output.parent / "outside"
        outside.mkdir()
        sentinel = outside / "preserve"
        sentinel.write_text("user artifact", encoding="utf-8")

        def complete(*_: object) -> None:
            stock.parent.mkdir(parents=True)
            stock.symlink_to(outside, target_is_directory=True)

        with (
            mock.patch.object(self.study, "run_workflow", side_effect=complete),
            mock.patch.object(self.study, "wait_until_idle"),
            self.assertRaisesRegex(benchmark.BenchmarkError, "unsafe"),
        ):
            self.study.run_workflow_with_retries(self.workload, "check", 0)

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "user artifact")


class FeatureWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.directory = Path(temporary_directory.name)
        arguments = benchmark.parser().parse_args(
            [
                "--output-dir",
                str(self.directory / "results"),
                "--noop-runs",
                "2",
                "--direct-runs",
                "2",
            ]
        )
        self.study = benchmark.Study(arguments)
        for workload in self.study.workloads:
            repository = self.directory / "sources" / workload.repository
            repository.mkdir(parents=True, exist_ok=True)
            self.study.sources[workload.repository] = repository
            for label, _ in self.study.toolchains:
                worktree = self.study.output / "worktrees" / workload.repository / label
                worktree.mkdir(parents=True)
                source = worktree / workload.direct.path
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text(workload.direct.before, encoding="utf-8")
                self.study.worktrees[workload.repository, label] = worktree

    def test_only_codex_includes_the_actual_formatter_workflow(self) -> None:
        self.assertEqual(
            self.study.feature_workflows(benchmark.WORKLOADS["uv"]),
            ("build-check", "shared-build"),
        )
        self.assertEqual(
            self.study.feature_workflows(benchmark.WORKLOADS["codex-core"]),
            ("build-check", "fmt", "shared-build"),
        )
        self.assertEqual(
            self.study.command(benchmark.WORKLOADS["codex-core"], "fmt", "1.97.1"),
            [
                "cargo",
                "+1.97.1",
                "fmt",
                "--",
                "--config",
                "imports_granularity=Item",
                "--check",
            ],
        )

    def test_formatter_and_build_arms_ignore_ambient_unowned_tool_overrides(
        self,
    ) -> None:
        (self.study.output / "logs").mkdir(parents=True)
        ambient = {
            "CARGO_BUILD_BUILD_DIR": str(self.directory / "unowned-cache"),
            "RUSTFMT": "/unowned/ohm-rustfmt",
            "RUSTFMT_WRAPPER": "/unowned/formatter-wrapper",
        }
        for workflow, workload in (
            ("check", benchmark.WORKLOADS["uv"]),
            ("build-check", benchmark.WORKLOADS["uv"]),
            ("fmt", benchmark.WORKLOADS["codex-core"]),
        ):
            with self.subTest(workflow=workflow):
                result = subprocess.CompletedProcess([], 0, stdout="")
                with (
                    mock.patch.dict(benchmark.os.environ, ambient),
                    mock.patch.object(
                        benchmark.subprocess, "run", return_value=result
                    ) as command,
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    self.study.execute(
                        workload,
                        workflow,
                        "stock",
                        "1.97.1",
                        phase="noop",
                        repetition=0,
                        expected_crate=None,
                    )

                environment = command.call_args.kwargs["env"]
                self.assertNotIn("CARGO_BUILD_BUILD_DIR", environment)
                if workflow == "fmt":
                    self.assertNotIn("RUSTFMT", environment)
                    self.assertNotIn("RUSTFMT_WRAPPER", environment)
                else:
                    self.assertEqual(environment["RUSTFMT"], ambient["RUSTFMT"])
                    self.assertEqual(
                        environment["RUSTFMT_WRAPPER"], ambient["RUSTFMT_WRAPPER"]
                    )

    def test_build_check_seeds_both_toolchains_before_timed_checks(self) -> None:
        workload = benchmark.WORKLOADS["uv"]

        with mock.patch.object(self.study, "execute") as execute:
            self.study.run_build_check(workload, 1)

        self.assertEqual(
            [call.kwargs["phase"] for call in execute.call_args_list],
            ["seed", "seed", "transition", "transition"],
        )
        self.assertEqual(
            [call.args[2] for call in execute.call_args_list],
            ["ohm", "stock", "ohm", "stock"],
        )
        for call in execute.call_args_list[:2]:
            self.assertFalse(call.kwargs["record"])
            self.assertEqual(call.kwargs["arguments"][2], "build")
            self.assertIn("--offline", call.kwargs["arguments"])
        for call in execute.call_args_list:
            self.assertEqual(call.args[1], "build-check")
            self.assertEqual(call.kwargs["expected_crate"], workload.package)

    def test_formatter_uses_real_reversible_edit_and_isolated_offline_cache(
        self,
    ) -> None:
        workload = benchmark.WORKLOADS["codex-core"]
        observations: list[tuple[str, str, int, str]] = []

        def record(*arguments: object, **options: object) -> None:
            label = str(arguments[2])
            source = (
                self.study.worktrees[workload.repository, label] / workload.direct.path
            )
            observations.append(
                (
                    str(options["phase"]),
                    label,
                    int(options["repetition"]),
                    source.read_text(encoding="utf-8"),
                )
            )
            environment = options["extra_environment"]
            self.assertEqual(environment["CARGO_NET_OFFLINE"], "true")
            self.assertEqual(
                environment["OHM_INCREMENTAL_FMT_CACHE_DIR"],
                str(self.study.target(workload, "fmt", label) / "formatter-cache"),
            )
            if label == "ohm" and options["phase"] == "warmup":
                cache = Path(environment["OHM_INCREMENTAL_FMT_CACHE_DIR"])
                cache.mkdir(parents=True)
                (cache / "published.json").write_text("{}", encoding="utf-8")

        with mock.patch.object(self.study, "execute", side_effect=record):
            self.study.run_format(workload, 0)

        self.assertEqual(
            [phase for phase, _, _, _ in observations],
            ["warmup"] * 2 + ["noop"] * 4 + ["direct"] * 4,
        )
        for phase, _, repetition, contents in observations:
            if phase == "direct":
                expected = (
                    workload.direct.after if repetition == 0 else workload.direct.before
                )
                self.assertEqual(contents, expected)
        for label, _ in self.study.toolchains:
            source = (
                self.study.worktrees[workload.repository, label] / workload.direct.path
            )
            self.assertEqual(source.read_text(encoding="utf-8"), workload.direct.before)

    def test_formatter_rejects_fallback_without_a_published_snapshot(self) -> None:
        workload = benchmark.WORKLOADS["codex-core"]

        def leave_only_lock(*arguments: object, **options: object) -> None:
            if arguments[2] == "ohm" and options["phase"] == "warmup":
                cache = Path(
                    options["extra_environment"]["OHM_INCREMENTAL_FMT_CACHE_DIR"]
                )
                cache.mkdir(parents=True)
                (cache / ".lock").write_text("", encoding="utf-8")

        with (
            mock.patch.object(self.study, "execute", side_effect=leave_only_lock),
            self.assertRaisesRegex(benchmark.BenchmarkError, "cache snapshot"),
        ):
            self.study.run_format(workload, 0)

    def test_shared_worktrees_detach_and_clean_exact_pinned_revision(self) -> None:
        workload = benchmark.WORKLOADS["uv"]

        with mock.patch.object(benchmark, "command_output", return_value="") as git:
            with self.study.managed_shared_worktrees(workload) as worktrees:
                self.assertEqual(set(worktrees), {"stock", "ohm"})
                for label, path in worktrees.items():
                    self.assertEqual(path.name, f"{label}-shared")

        additions = [
            call.args[0]
            for call in git.call_args_list
            if call.args[0][1:3] == ["worktree", "add"]
        ]
        removals = [
            call.args[0]
            for call in git.call_args_list
            if call.args[0][1:3] == ["worktree", "remove"]
        ]
        self.assertEqual(len(additions), 2)
        self.assertEqual(len(removals), 2)
        self.assertTrue(
            all(command[-1] == self.study.revisions["uv"] for command in additions)
        )

    def test_shared_worktree_creation_failure_cleans_only_completed_peer(
        self,
    ) -> None:
        workload = benchmark.WORKLOADS["uv"]

        def run_git(arguments: list[str], *, cwd: Path) -> str:
            if arguments[1:3] == ["worktree", "add"] and "ohm-shared" in arguments[-2]:
                raise benchmark.BenchmarkError("unable to detach peer")
            return ""

        with (
            mock.patch.object(benchmark, "command_output", side_effect=run_git) as git,
            self.assertRaisesRegex(benchmark.BenchmarkError, "detach peer"),
        ):
            with self.study.managed_shared_worktrees(workload):
                self.fail("peer creation unexpectedly succeeded")

        removals = [
            call.args[0]
            for call in git.call_args_list
            if call.args[0][1:3] == ["worktree", "remove"]
        ]
        self.assertEqual(len(removals), 1)
        self.assertEqual(Path(removals[0][-1]).name, "stock-shared")

    def test_shared_build_has_private_targets_and_identical_per_arm_build_root(
        self,
    ) -> None:
        workload = benchmark.WORKLOADS["uv"]
        peers = {
            label: self.directory / f"{label}-peer"
            for label, _ in self.study.toolchains
        }
        for peer in peers.values():
            source = peer / workload.direct.path
            source.parent.mkdir(parents=True)
            source.write_text(workload.direct.before, encoding="utf-8")

        def publish(*arguments: object, **options: object) -> None:
            label = str(arguments[2])
            if label == "ohm" and options["phase"] == "seed":
                root = Path(options["extra_environment"]["CARGO_BUILD_BUILD_DIR"])
                (root / "debug" / "build" / "registries").mkdir(parents=True)
                (root / ".ohm-shared-registry-cache-v1").write_text(
                    "", encoding="utf-8"
                )
            if options["phase"] == "reuse":
                for peer in peers.values():
                    source = peer / workload.direct.path
                    self.assertEqual(
                        source.read_text(encoding="utf-8"), workload.direct.after
                    )

        with (
            mock.patch.object(
                benchmark.shutil, "which", return_value="/trusted/rustup/bin/cargo"
            ),
            mock.patch.dict(
                benchmark.os.environ,
                {"PATH": "/opaque/virtualenv/bin:/trusted/rustup/bin:/usr/bin"},
            ),
            mock.patch.object(
                self.study,
                "managed_shared_worktrees",
                return_value=contextlib.nullcontext(peers),
            ),
            mock.patch.object(self.study, "execute", side_effect=publish) as execute,
        ):
            self.study.run_shared_build(workload, 0)

        self.assertEqual(
            [call.kwargs["phase"] for call in execute.call_args_list],
            ["seed", "seed", "reuse", "reuse"],
        )
        build_roots: dict[str, set[str]] = {"stock": set(), "ohm": set()}
        executable_paths: dict[str, set[str]] = {"stock": set(), "ohm": set()}
        targets: dict[str, list[Path]] = {"stock": [], "ohm": []}
        for call in execute.call_args_list:
            label = str(call.args[2])
            build_root = call.kwargs["extra_environment"]["CARGO_BUILD_BUILD_DIR"]
            executable_paths[label].add(call.kwargs["extra_environment"]["PATH"])
            target = call.kwargs["target_directory"]
            build_roots[label].add(build_root)
            targets[label].append(target)
            self.assertFalse(target.is_relative_to(build_root))
            self.assertFalse(Path(build_root).is_relative_to(target))
            self.assertEqual(call.kwargs["expected_crate"], workload.package)
            if call.kwargs["phase"] == "reuse":
                self.assertEqual(call.kwargs["worktree"], peers[label])
        self.assertEqual(len(build_roots["stock"]), 1)
        self.assertEqual(len(build_roots["ohm"]), 1)
        expected_path = {"/trusted/rustup/bin:/usr/bin:/bin"}
        self.assertEqual(executable_paths["stock"], expected_path)
        self.assertEqual(executable_paths["ohm"], expected_path)
        self.assertNotEqual(build_roots["stock"], build_roots["ohm"])
        self.assertNotEqual(targets["stock"][0], targets["stock"][1])
        self.assertNotEqual(targets["ohm"][0], targets["ohm"][1])
        for peer in peers.values():
            source = peer / workload.direct.path
            self.assertEqual(source.read_text(encoding="utf-8"), workload.direct.before)

    def test_shared_build_rejects_missing_or_relative_cargo_proxy(self) -> None:
        workload = benchmark.WORKLOADS["uv"]
        for cargo in (None, "relative/cargo"):
            with self.subTest(cargo=cargo):
                with (
                    mock.patch.object(benchmark.shutil, "which", return_value=cargo),
                    mock.patch.object(self.study, "managed_shared_worktrees") as peers,
                    self.assertRaisesRegex(
                        benchmark.BenchmarkError, "absolute Cargo executable"
                    ),
                ):
                    self.study.run_shared_build(workload, 0)

                peers.assert_not_called()

    def test_shared_build_rejects_marker_without_immutable_registry_artifacts(
        self,
    ) -> None:
        workload = benchmark.WORKLOADS["uv"]
        peers = {
            label: self.directory / f"{label}-peer"
            for label, _ in self.study.toolchains
        }

        def publish_marker_only(*arguments: object, **options: object) -> None:
            if arguments[2] == "ohm" and options["phase"] == "seed":
                root = Path(options["extra_environment"]["CARGO_BUILD_BUILD_DIR"])
                root.mkdir(parents=True)
                (root / ".ohm-shared-registry-cache-v1").write_text(
                    "", encoding="utf-8"
                )

        with (
            mock.patch.object(
                self.study,
                "managed_shared_worktrees",
                return_value=contextlib.nullcontext(peers),
            ),
            mock.patch.object(self.study, "execute", side_effect=publish_marker_only),
            self.assertRaisesRegex(benchmark.BenchmarkError, "immutable artifacts"),
        ):
            self.study.run_shared_build(workload, 0)

    def test_shared_sample_records_actual_peer_build_root_and_private_target(
        self,
    ) -> None:
        workload = benchmark.WORKLOADS["uv"]
        (self.study.output / "logs").mkdir(parents=True)
        peer = self.directory / "peer"
        peer.mkdir()
        root = self.study.target(workload, "shared-build", "stock")
        target = root / "secondary-target"
        build_directory = root / "shared-build"
        result = subprocess.CompletedProcess(
            [], 0, stdout="   Compiling uv v0.0.0 (/workspace/uv)\n"
        )

        with (
            mock.patch.dict(
                benchmark.os.environ,
                {"CARGO_BUILD_BUILD_DIR": str(self.directory / "unowned-cache")},
            ),
            mock.patch.object(
                benchmark.subprocess, "run", return_value=result
            ) as command,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.study.execute(
                workload,
                "shared-build",
                "stock",
                "1.97.1",
                phase="reuse",
                repetition=0,
                expected_crate="uv",
                worktree=peer,
                target_directory=target,
                extra_environment={"CARGO_BUILD_BUILD_DIR": str(build_directory)},
            )

        self.assertEqual(command.call_args.kwargs["cwd"], peer)
        environment = command.call_args.kwargs["env"]
        self.assertEqual(environment["CARGO_TARGET_DIR"], str(target))
        self.assertEqual(environment["CARGO_BUILD_BUILD_DIR"], str(build_directory))
        sample = self.study.samples[0]
        self.assertEqual(sample["worktree"], str(peer))
        self.assertEqual(sample["target_directory"], str(target))
        self.assertEqual(sample["shared_build_directory"], str(build_directory))

    def test_build_check_readiness_marker_is_optional_for_released_ohm(self) -> None:
        workload = benchmark.WORKLOADS["uv"]
        (self.study.output / "logs").mkdir(parents=True)
        result = subprocess.CompletedProcess(
            [], 0, stdout="   Checking uv v0.0.0 (/workspace/uv)\n"
        )

        with (
            mock.patch.object(benchmark.subprocess, "run", return_value=result),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.study.execute(
                workload,
                "build-check",
                "ohm",
                "ohm",
                phase="transition",
                repetition=0,
                expected_crate="uv",
            )
            marker = (
                self.study.target(workload, "build-check", "ohm")
                / ".ohm-built-registry-ready"
            )
            marker.write_text("", encoding="utf-8")
            self.study.execute(
                workload,
                "build-check",
                "ohm",
                "ohm",
                phase="transition",
                repetition=1,
                expected_crate="uv",
            )

        self.assertEqual(
            [sample["registry_build_ready"] for sample in self.study.samples],
            [False, True],
        )

    def test_feature_comparisons_preserve_core_rows_and_include_new_phases(
        self,
    ) -> None:
        workload = benchmark.WORKLOADS["codex-core"]
        for workflow, phase in (
            ("check", "noop"),
            ("build-check", "transition"),
            ("fmt", "noop"),
            ("fmt", "direct"),
            ("shared-build", "reuse"),
        ):
            for label, duration in (("stock", 2.0), ("ohm", 1.0)):
                self.study.samples.append(
                    {
                        "project": workload.name,
                        "workflow": workflow,
                        "phase": phase,
                        "toolchain": label,
                        "wall_seconds": duration,
                        "valid": True,
                    }
                )

        comparisons = self.study.comparisons()

        self.assertEqual(
            [(row["workflow"], row["phase"]) for row in comparisons],
            [
                ("check", "noop"),
                ("build-check", "transition"),
                ("fmt", "noop"),
                ("fmt", "direct"),
                ("shared-build", "reuse"),
            ],
        )
        self.assertTrue(all(row["speedup"] == 2.0 for row in comparisons))

    def test_run_keeps_all_historical_workflows_before_feature_workflows(self) -> None:
        output = self.directory / "ordered-results"
        options = benchmark.parser().parse_args(["--output-dir", str(output)])
        study = benchmark.Study(options)

        with (
            mock.patch.object(study, "prepare_sources"),
            mock.patch.object(
                study, "managed_worktrees", return_value=contextlib.nullcontext()
            ),
            mock.patch.object(study, "write_results"),
            mock.patch.object(study, "run_workflow_with_retries") as workflow,
            mock.patch.object(benchmark, "command_output", return_value="version"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            study.run()

        self.assertEqual(
            [(call.args[0].name, call.args[1]) for call in workflow.call_args_list],
            [
                ("uv", "check"),
                ("uv", "clippy"),
                ("uv", "test"),
                ("codex-core", "check"),
                ("codex-core", "clippy"),
                ("codex-core", "test"),
                ("uv", "build-check"),
                ("uv", "shared-build"),
                ("codex-core", "build-check"),
                ("codex-core", "fmt"),
                ("codex-core", "shared-build"),
            ],
        )
        self.assertEqual(
            study.metadata["feature_workflows"]["codex-core"],
            ("build-check", "fmt", "shared-build"),
        )


class ReversibleEditTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.directory = Path(temporary_directory.name)
        self.worktree = self.directory / "worktree"
        self.worktree.mkdir()
        self.source = self.worktree / "source.rs"
        self.original = b"fn answer() -> u8 { 41 + 1 }\n"
        self.source.write_bytes(self.original)

    def edit(self, **overrides: str) -> object:
        arguments = {
            "path": "source.rs",
            "before": "41 + 1",
            "after": "1 + 41",
            "crate": "example",
        }
        arguments.update(overrides)
        return benchmark.Edit(**arguments)

    def test_switches_between_exact_source_versions(self) -> None:
        with benchmark.reversible_edit(self.worktree, self.edit()) as activate:
            activate(True)
            self.assertEqual(
                self.source.read_bytes(), b"fn answer() -> u8 { 1 + 41 }\n"
            )

            activate(False)
            self.assertEqual(self.source.read_bytes(), self.original)

    def test_restores_source_after_interrupted_measurement(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            with benchmark.reversible_edit(self.worktree, self.edit()) as activate:
                activate(True)
                raise RuntimeError("interrupted")

        self.assertEqual(self.source.read_bytes(), self.original)

    def test_rejects_missing_or_ambiguous_edit_markers(self) -> None:
        for before in ("missing", "1"):
            with self.subTest(before=before):
                with self.assertRaises(benchmark.BenchmarkError):
                    with benchmark.reversible_edit(
                        self.worktree, self.edit(before=before)
                    ):
                        self.fail("invalid edit unexpectedly activated")

                self.assertEqual(self.source.read_bytes(), self.original)

    def test_rejects_paths_outside_the_worktree(self) -> None:
        outside = self.directory / "outside.rs"
        outside.write_bytes(self.original)

        with self.assertRaises(benchmark.BenchmarkError):
            with benchmark.reversible_edit(
                self.worktree, self.edit(path="../outside.rs")
            ):
                self.fail("escaping edit unexpectedly activated")

        self.assertEqual(outside.read_bytes(), self.original)

    def test_rejects_symlinks_outside_the_worktree(self) -> None:
        outside = self.directory / "outside.rs"
        outside.write_bytes(self.original)
        (self.worktree / "link.rs").symlink_to(outside)

        with self.assertRaises(benchmark.BenchmarkError):
            with benchmark.reversible_edit(self.worktree, self.edit(path="link.rs")):
                self.fail("escaping symlink unexpectedly activated")

        self.assertEqual(outside.read_bytes(), self.original)


class OutputValidationTests(unittest.TestCase):
    def test_accepts_compiled_expected_crate(self) -> None:
        benchmark.validate_output(
            "   Compiling codex-core v0.0.0 (/workspace/core)\n",
            expected_crate="codex-core",
            selected_test=None,
        )

    def test_rejects_package_cache_lock_contention(self) -> None:
        with self.assertRaises(benchmark.ContaminatedBenchmarkError):
            benchmark.validate_output(
                "Blocking waiting for file lock on package cache\n",
                expected_crate=None,
                selected_test=None,
            )

    def test_rejects_missing_or_prefix_matched_crate(self) -> None:
        for output in (
            "    Finished dev profile\n",
            "   Compiling codex-core-extra v0.0.0\n",
        ):
            with self.subTest(output=output):
                with self.assertRaises(benchmark.BenchmarkError):
                    benchmark.validate_output(
                        output, expected_crate="codex-core", selected_test=None
                    )

    def test_accepts_selected_test_from_cargo_and_nextest(self) -> None:
        selected = "audio_preparation::tests::selected_test"
        for output in (
            f"running 1 test\ntest {selected} ... ok\n",
            f"Starting 1 test across 1 binary\nPASS [0.001s] codex-core {selected}\n",
        ):
            with self.subTest(output=output):
                benchmark.validate_output(
                    output, expected_crate=None, selected_test=selected
                )

    def test_rejects_zero_missing_and_prefix_matched_tests(self) -> None:
        selected = "audio_preparation::tests::selected_test"
        for output in (
            "running 0 tests\n",
            "running 1 test\ntest another_test ... ok\n",
            f"running 1 test\ntest {selected}_variant ... ok\n",
        ):
            with self.subTest(output=output):
                with self.assertRaises(benchmark.BenchmarkError):
                    benchmark.validate_output(
                        output, expected_crate=None, selected_test=selected
                    )


class TargetIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.directory = Path(temporary_directory.name)
        self.study = object.__new__(benchmark.Study)
        self.study.output = self.directory / "output"
        self.workload = benchmark.WORKLOADS["uv"]

    def test_repeated_cold_run_removes_only_its_owned_target(self) -> None:
        target = self.study.target(self.workload, "check", "stock")
        sibling = self.study.target(self.workload, "check", "ohm")
        target.mkdir(parents=True)
        sibling.mkdir(parents=True)
        (target / "artifact").write_text("remove", encoding="utf-8")
        (sibling / "artifact").write_text("preserve", encoding="utf-8")

        self.study.reset_target(self.workload, "check", "stock")

        self.assertFalse(target.exists())
        self.assertEqual((sibling / "artifact").read_text(encoding="utf-8"), "preserve")

    def test_rejects_symlinked_target_before_removal(self) -> None:
        target = self.study.target(self.workload, "check", "stock")
        outside = self.directory / "outside"
        outside.mkdir()
        (outside / "artifact").write_text("preserve", encoding="utf-8")
        target.parent.mkdir(parents=True)
        target.symlink_to(outside, target_is_directory=True)

        with self.assertRaises(benchmark.BenchmarkError):
            self.study.reset_target(self.workload, "check", "stock")

        self.assertEqual((outside / "artifact").read_text(encoding="utf-8"), "preserve")

    def test_cold_repetitions_reset_each_toolchains_target(self) -> None:
        self.study.options = benchmark.parser().parse_args(["--cold-runs", "2"])
        self.study.toolchains = (("stock", "1.97.1"), ("ohm", "ohm"))

        with (
            mock.patch.object(self.study, "execute"),
            mock.patch.object(self.study, "run_edits"),
            mock.patch.object(self.study, "reset_target") as reset_target,
        ):
            self.study.run_workflow(self.workload, "check", 0)

        self.assertEqual(
            reset_target.call_args_list,
            [
                mock.call(self.workload, "check", "ohm"),
                mock.call(self.workload, "check", "stock"),
            ],
        )


class SourcePreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.repository = Path(temporary_directory.name).resolve()
        self.revision = "a" * 40
        self.workload = benchmark.WORKLOADS["uv"]
        self.blobs = {"Cargo.toml": "[workspace]\n"}
        (self.repository / "Cargo.toml").write_text(
            self.blobs["Cargo.toml"], encoding="utf-8"
        )
        for edit in (self.workload.dependency, self.workload.direct):
            source = self.repository / edit.path
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(edit.before, encoding="utf-8")
            self.blobs[edit.path] = edit.before

    def options(self) -> object:
        return benchmark.parser().parse_args(
            [
                "--project",
                "uv",
                "--uv-path",
                str(self.repository),
                "--uv-rev",
                self.revision,
            ]
        )

    def git_output(self, command: list[str], *, cwd: Path) -> str:
        if command[1:3] == ["rev-parse", "--show-toplevel"]:
            return str(self.repository)
        if command[1:3] == ["rev-parse", "--verify"]:
            return self.revision
        if command[1] == "show":
            revision, _, relative = command[-1].partition(":")
            self.assertEqual(revision, self.revision)
            return self.blobs[Path(relative).as_posix()]
        self.fail(f"unexpected Git command: {command}")

    def test_validates_pinned_commit_without_mutating_dirty_checkout(self) -> None:
        dependency = self.repository / self.workload.dependency.path
        dirty_source = "// unrelated local changes\n"
        dependency.write_text(dirty_source, encoding="utf-8")

        with mock.patch.object(
            benchmark, "command_output", side_effect=self.git_output
        ) as command_output:
            study = benchmark.Study(self.options())

        self.assertEqual(study.sources["uv"], self.repository)
        self.assertEqual(study.revisions["uv"], self.revision)
        self.assertEqual(dependency.read_text(encoding="utf-8"), dirty_source)
        self.assertFalse(
            any(call.args[0][1] == "status" for call in command_output.call_args_list)
        )

    def test_rejects_markers_missing_from_the_pinned_commit(self) -> None:
        self.blobs[self.workload.dependency.path] = "// marker changed upstream\n"

        with mock.patch.object(
            benchmark, "command_output", side_effect=self.git_output
        ):
            with self.assertRaises(benchmark.BenchmarkError):
                benchmark.Study(self.options())

    def test_rejects_revision_that_resolves_to_a_different_commit(self) -> None:
        def mismatched_revision(command: list[str], *, cwd: Path) -> str:
            if command[1:3] == ["rev-parse", "--verify"]:
                return "b" * 40
            return self.git_output(command, cwd=cwd)

        with mock.patch.object(
            benchmark, "command_output", side_effect=mismatched_revision
        ):
            with self.assertRaisesRegex(benchmark.BenchmarkError, "exactly"):
                benchmark.Study(self.options())

    def test_detaches_both_toolchains_from_the_same_exact_revision(self) -> None:
        with mock.patch.object(
            benchmark, "command_output", side_effect=self.git_output
        ):
            study = benchmark.Study(self.options())
        study.output = self.repository / "output"

        with mock.patch.object(benchmark, "command_output", return_value="") as git:
            with study.managed_worktrees():
                self.assertEqual(set(study.worktrees), {("uv", "stock"), ("uv", "ohm")})

        additions = [
            call.args[0]
            for call in git.call_args_list
            if call.args[0][1:3] == ["worktree", "add"]
        ]
        self.assertEqual(len(additions), 2)
        self.assertTrue(all(command[-1] == self.revision for command in additions))


class PublicRepositoryTests(unittest.TestCase):
    def test_uv_direct_edit_expands_homebrew_formula_detection(self) -> None:
        edit = benchmark.WORKLOADS["uv"].direct

        self.assertEqual(edit.before, "component == cellar && next == formula")
        self.assertIn('next == OsStr::new("uv-preview")', edit.after)
        self.assertIn("\n", edit.after)

    def test_default_repositories_use_exact_public_pinned_revisions(self) -> None:
        self.assertEqual(
            benchmark.REPOSITORIES,
            {
                "uv": {
                    "url": "https://github.com/astral-sh/uv.git",
                    "revision": "c22e6b71933443e9cd299d4b6ac8de035ed4825b",
                },
                "codex": {
                    "url": "https://github.com/openai/codex.git",
                    "revision": "5157493c23713ac12034cf250ffb0a8ce0670277",
                },
            },
        )
        arguments = benchmark.parser().parse_args([])
        self.assertIsNone(arguments.uv_path)
        self.assertIsNone(arguments.codex_path)
        self.assertEqual(arguments.uv_rev, benchmark.REPOSITORIES["uv"]["revision"])
        self.assertEqual(
            arguments.codex_rev, benchmark.REPOSITORIES["codex"]["revision"]
        )

    def test_omitted_paths_dry_run_never_accesses_git_or_creates_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "benchmark-output"
            arguments = benchmark.parser().parse_args(
                ["--project", "uv", "--output-dir", str(output), "--dry-run"]
            )

            with (
                mock.patch.object(benchmark, "command_output") as git,
                contextlib.redirect_stdout(io.StringIO()) as console,
            ):
                study = benchmark.Study(arguments)
                study.describe()

            git.assert_not_called()
            self.assertFalse(output.exists())
            self.assertEqual(study.sources, {})
            self.assertIn(benchmark.REPOSITORIES["uv"]["url"], console.getvalue())
            self.assertIn(benchmark.REPOSITORIES["uv"]["revision"], console.getvalue())

    def test_rejects_branches_and_abbreviated_source_revisions(self) -> None:
        for revision in ("main", "abcdef123456", "a" * 39):
            with self.subTest(revision=revision):
                arguments = benchmark.parser().parse_args(
                    ["--project", "uv", "--uv-rev", revision]
                )

                with mock.patch.object(benchmark, "command_output") as git:
                    with self.assertRaisesRegex(benchmark.BenchmarkError, "full Git"):
                        benchmark.Study(arguments)

                git.assert_not_called()


class RepositoryCloneTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.directory = Path(temporary_directory.name).resolve()
        self.output = self.directory / "output"
        self.revision = "a" * 40
        self.workload = benchmark.WORKLOADS["uv"]
        arguments = benchmark.parser().parse_args(
            [
                "--project",
                "uv",
                "--uv-rev",
                self.revision,
                "--output-dir",
                str(self.output),
            ]
        )
        self.study = benchmark.Study(arguments)

    def git_output(self, command: list[str], *, cwd: Path | None = None) -> str:
        if "clone" in command:
            Path(command[-1]).mkdir(parents=True)
            return ""
        if "fetch" in command:
            self.assertEqual(command[-1], self.revision)
            return ""
        if command[1:3] == ["rev-parse", "--verify"]:
            return self.revision
        if command[1] == "show":
            _, _, relative = command[-1].partition(":")
            if Path(relative).name == "Cargo.toml":
                return "[workspace]\n"
            for edit in (self.workload.dependency, self.workload.direct):
                if relative == edit.path:
                    return edit.before
        self.fail(f"unexpected Git command: {command}")

    def assert_preserves_public_https(self, command: list[str], url: str) -> None:
        prefix = url.rsplit("/", 1)[0] + "/"
        configuration = f"url.{prefix}.insteadOf={prefix}"
        self.assertEqual(command[:4], ["git", "-c", configuration, "clone"])
        self.assertEqual(command[command.index("--config") + 1], configuration)
        self.assertIn(url, command)

    def test_clones_public_source_and_fetches_exact_pinned_revision(self) -> None:
        with (
            mock.patch.object(
                benchmark, "command_output", side_effect=self.git_output
            ) as git,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.study.prepare_sources()

        destination = self.output / "sources" / "uv"
        self.assertEqual(self.study.sources, {"uv": destination})
        self.assertTrue(destination.is_dir())
        self.assertEqual(list(destination.parent.iterdir()), [destination])
        clone = next(
            call.args[0] for call in git.call_args_list if "clone" in call.args[0]
        )
        self.assert_preserves_public_https(clone, benchmark.REPOSITORIES["uv"]["url"])
        fetch = next(
            call.args[0] for call in git.call_args_list if "fetch" in call.args[0]
        )
        self.assertEqual(fetch[-1], self.revision)

    def test_public_codex_clone_persists_its_owner_specific_https_override(
        self,
    ) -> None:
        self.workload = benchmark.WORKLOADS["codex-core"]
        arguments = benchmark.parser().parse_args(
            [
                "--project",
                "codex-core",
                "--codex-rev",
                self.revision,
                "--output-dir",
                str(self.output),
            ]
        )
        study = benchmark.Study(arguments)

        with (
            mock.patch.object(
                benchmark, "command_output", side_effect=self.git_output
            ) as git,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            study.prepare_sources()

        clone = next(
            call.args[0] for call in git.call_args_list if "clone" in call.args[0]
        )
        self.assert_preserves_public_https(
            clone, benchmark.REPOSITORIES["codex"]["url"]
        )
        self.assertEqual(study.sources["codex"], self.output / "sources" / "codex")

    def test_failed_fetch_removes_only_the_owned_partial_checkout(self) -> None:
        user_source = self.directory / "user-source"
        user_source.mkdir()
        sentinel = user_source / "uncommitted.rs"
        sentinel.write_text("preserve local edits", encoding="utf-8")

        def fail_fetch(command: list[str], *, cwd: Path | None = None) -> str:
            if "fetch" in command:
                raise benchmark.BenchmarkError("pinned revision fetch failed")
            return self.git_output(command, cwd=cwd)

        with (
            mock.patch.object(benchmark, "command_output", side_effect=fail_fetch),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(benchmark.BenchmarkError, "fetch failed"),
        ):
            self.study.prepare_sources()

        self.assertEqual(self.study.sources, {})
        self.assertEqual(list((self.output / "sources").iterdir()), [])
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve local edits")

    def test_failed_clone_removes_its_partially_created_checkout(self) -> None:
        def fail_clone(command: list[str], *, cwd: Path | None = None) -> str:
            if "clone" in command:
                Path(command[-1]).mkdir(parents=True)
                raise benchmark.BenchmarkError("public repository clone failed")
            return self.git_output(command, cwd=cwd)

        with (
            mock.patch.object(benchmark, "command_output", side_effect=fail_clone),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(benchmark.BenchmarkError, "clone failed"),
        ):
            self.study.prepare_sources()

        self.assertEqual(self.study.sources, {})
        self.assertEqual(list((self.output / "sources").iterdir()), [])


class CommandLineTests(unittest.TestCase):
    def test_uv_test_workflow_runs_a_real_integration_test(self) -> None:
        study = object.__new__(benchmark.Study)
        workload = benchmark.WORKLOADS["uv"]

        self.assertEqual(
            study.command(workload, "test", "1.97.1"),
            [
                "cargo",
                "+1.97.1",
                "test",
                "-p",
                "uv",
                "--test",
                "it",
                "--locked",
                "--offline",
                "help::help",
                "--",
                "--exact",
            ],
        )
        for workflow in ("check", "clippy"):
            with self.subTest(workflow=workflow):
                self.assertIn("--lib", study.command(workload, workflow, "1.97.1"))

    def test_default_matrix_contains_only_uv_and_codex_core(self) -> None:
        arguments = benchmark.parser().parse_args([])

        with (
            mock.patch.object(benchmark, "command_output") as command_output,
            contextlib.redirect_stdout(io.StringIO()) as console,
        ):
            study = benchmark.Study(arguments)
            study.describe()

        command_output.assert_not_called()
        self.assertEqual(
            [workload.name for workload in study.workloads], ["uv", "codex-core"]
        )
        self.assertIn("core timed samples: 192", console.getvalue())
        self.assertIn("feature timed samples: 24", console.getvalue())
        self.assertIn("timed samples: 216", console.getvalue())
        self.assertIn(
            "feature workflows: build-check, fmt, shared-build", console.getvalue()
        )
        self.assertNotIn("codex-tools", console.getvalue())

    def test_rejects_duplicate_projects_before_accessing_repositories(self) -> None:
        arguments = benchmark.parser().parse_args(
            ["--project", "uv", "--project", "uv", "--uv-path", "/does/not/exist"]
        )

        with mock.patch.object(benchmark, "command_output") as command_output:
            with self.assertRaisesRegex(benchmark.BenchmarkError, "repeated"):
                benchmark.Study(arguments)

        command_output.assert_not_called()

    def test_dry_run_and_project_selection_parse_without_building(self) -> None:
        arguments = benchmark.parser().parse_args(
            [
                "--uv-path",
                "/work/uv",
                "--codex-path",
                "/work/codex",
                "--project",
                "codex-core",
                "--upstream",
                "1.97.1",
                "--ohm",
                "ohm-1.97.1-5",
                "--dry-run",
            ]
        )

        self.assertTrue(arguments.dry_run)


if __name__ == "__main__":
    unittest.main()
