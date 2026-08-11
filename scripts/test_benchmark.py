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
            ]
        )

        with mock.patch.object(benchmark, "command_output", return_value=processes):
            active = benchmark.competing_processes(owner=20)

        self.assertEqual(
            active, ["50 cargo-nextest", "60 cargo", "70 rustc", "80 clang"]
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
        with self.assertRaises(benchmark.BenchmarkError):
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
        self.assertIn("timed samples: 192", console.getvalue())
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
