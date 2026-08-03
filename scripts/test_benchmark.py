"""Fast, build-free regression tests for the Ohm benchmark runner."""

from __future__ import annotations

import importlib.util
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
        (self.repository / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
        self.workload = benchmark.WORKLOADS["uv"]
        for edit in (self.workload.dependency, self.workload.direct):
            source = self.repository / edit.path
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(edit.before, encoding="utf-8")

    def test_rejects_dirty_benchmark_sources_before_detaching_worktrees(self) -> None:
        arguments = benchmark.parser().parse_args(
            ["--project", "uv", "--uv-path", str(self.repository)]
        )

        def git_output(command: list[str], *, cwd: Path) -> str:
            if command[1] == "rev-parse":
                return str(self.repository)
            if command[1] == "status":
                return f" M {self.workload.dependency.path}"
            self.fail(f"unexpected Git command: {command}")

        with mock.patch.object(benchmark, "command_output", side_effect=git_output):
            with self.assertRaisesRegex(benchmark.BenchmarkError, "uncommitted"):
                benchmark.Study(arguments)

    def test_ignores_unrelated_dirty_repository_files(self) -> None:
        (self.repository / "unrelated.txt").write_text("dirty", encoding="utf-8")
        arguments = benchmark.parser().parse_args(
            ["--project", "uv", "--uv-path", str(self.repository)]
        )
        status_commands: list[list[str]] = []

        def git_output(command: list[str], *, cwd: Path) -> str:
            if command[1] == "rev-parse":
                return str(self.repository)
            if command[1] == "status":
                status_commands.append(command)
                return ""
            self.fail(f"unexpected Git command: {command}")

        with mock.patch.object(benchmark, "command_output", side_effect=git_output):
            study = benchmark.Study(arguments)

        self.assertEqual(study.sources["uv"], self.repository)
        self.assertEqual(
            status_commands,
            [
                [
                    "git",
                    "status",
                    "--porcelain",
                    "--",
                    self.workload.dependency.path,
                    self.workload.direct.path,
                ]
            ],
        )


class CommandLineTests(unittest.TestCase):
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
