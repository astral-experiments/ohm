"""Fast, build-free correctness and security tests for real-session replays."""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "replay_sessions.py"
SPEC = importlib.util.spec_from_file_location("ohm_session_replay", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to import session replay runner: {SCRIPT}")
replay = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = replay
SPEC.loader.exec_module(replay)

from publish_benchmarks import latest_reports


class ReplayTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.fixture = self.directory / "scenario.json"
        self.fixture.write_text(
            json.dumps(
                {
                    "project": "ruff",
                    "repository": "https://github.com/astral-sh/ruff.git",
                    "base_revision": "a" * 40,
                    "fetch_refs": ["refs/heads/main"],
                    "session": {"id": "real-session"},
                    "environment": {},
                    "warmup": [
                        {
                            "kind": "command",
                            "label": "Warm semantic analysis",
                            "program": "cargo",
                            "args": ["check", "-p", "ty_python_semantic"],
                        }
                    ],
                    "steps": [
                        {
                            "kind": "command",
                            "label": "Run a focused test",
                            "program": "cargo",
                            "args": ["test", "focused"],
                        }
                    ],
                }
            )
        )

    def scenario(self, **changes: object) -> object:
        data = json.loads(self.fixture.read_text())
        data.update(changes)
        self.fixture.write_text(json.dumps(data))
        return replay.load_scenario(self.fixture)

    def runner(self, *arguments: str) -> object:
        options = replay.parser().parse_args(
            [
                "--project",
                "ruff",
                "--scenario",
                str(self.fixture),
                "--output-dir",
                str(self.directory / "output"),
                *arguments,
            ]
        )
        return replay.Replay(options)


class FixtureValidationTests(ReplayTestCase):
    def test_ty_bugfix_fixture_preserves_red_tests_and_feature_changes(self) -> None:
        scenario = replay.load_scenario(SCRIPTS / "session_replays" / "ty-29327.json")
        commands = [step for step in scenario.steps if step["kind"] == "command"]
        self.assertEqual(sum(step.get("expected_exit") == 100 for step in commands), 2)
        self.assertEqual(scenario.environment["CARGO_PROFILE_DEV_OPT_LEVEL"], "1")
        self.assertNotIn("CARGO_BUILD_WARNINGS", scenario.environment)
        self.assertEqual(commands[-1]["environment"], {"CARGO_BUILD_WARNINGS": "deny"})
        self.assertEqual(scenario.warmup[0]["args"], ["build", "--bin", "ty"])
        self.assertEqual(
            commands[-1]["args"],
            ["clippy", "-p", "ty_python_semantic", "--all-targets", "--all-features"],
        )
        for step in commands:
            if step["args"][:2] == ["nextest", "run"]:
                self.assertNotIn("--all-features", step["args"])

    def test_expected_failures_require_evidence_and_a_valid_status(self) -> None:
        step = {
            "kind": "command",
            "label": "Red test",
            "program": "cargo",
            "args": ["test"],
        }
        for extra in (
            {"expected_exit": 100},
            {"expected_exit": -9, "output_contains": ["failure"]},
            {"expected_exit": True, "output_contains": ["failure"]},
            {"expected_exit": 100, "output_contains": [""]},
        ):
            with self.subTest(extra=extra), self.assertRaises(replay.BenchmarkError):
                self.scenario(steps=[{**step, **extra}])

    def test_python_helper_cannot_escape_through_a_symlink(self) -> None:
        outside = self.directory / "outside.py"
        outside.write_text("raise SystemExit(0)\n")
        fixtures = self.directory / "fixtures"
        fixtures.mkdir()
        (fixtures / "helper.py").symlink_to(outside)
        with self.assertRaisesRegex(replay.BenchmarkError, "symlinks"):
            replay.Replay.command(
                {"program": "python", "args": ["helper.py"]}, "ohm", fixtures
            )

    def test_all_bundled_real_sessions_are_valid(self) -> None:
        for project in replay.PROJECTS:
            with self.subTest(project=project):
                scenario = replay.load_scenario(
                    SCRIPTS / "session_replays" / f"{project}-rust-1.99.json"
                )
                self.assertEqual(scenario.project, project)
                self.assertRegex(scenario.session["id"], r"^[a-z][a-z0-9-]+$")
                self.assertNotIn("recorded_at", scenario.session)
                self.assertGreaterEqual(
                    sum(step["kind"] == "edit" for step in scenario.steps), 3
                )
                self.assertGreaterEqual(
                    sum(step["kind"] == "command" for step in scenario.steps), 8
                )

    def test_feature_ablation_fixture_uses_only_public_session_metadata(self) -> None:
        scenario = replay.load_scenario(
            SCRIPTS / "session_replays" / "uv-feature-ablation.json"
        )
        self.assertRegex(scenario.session["id"], r"^[a-z][a-z0-9-]+$")
        self.assertNotIn("recorded_at", scenario.session)

    def test_default_ruff_fixture_preserves_the_historical_workload(self) -> None:
        historical = replay.load_scenario(
            SCRIPTS / "session_replays" / "ruff-historical-rust-1.99.json"
        )
        current = replay.load_scenario(
            SCRIPTS / "session_replays" / "ruff-rust-1.99.json"
        )
        self.assertEqual(current.project, "ruff")
        self.assertNotEqual(current.session["id"], historical.session["id"])
        self.assertNotEqual(current.base_revision, historical.base_revision)
        self.assertNotIn("CARGO_PROFILE_DEV_LTO", historical.environment)
        self.assertEqual(
            current.environment,
            {
                "CARGO_PROFILE_DEV_OPT_LEVEL": "1",
                "CARGO_PROFILE_DEV_LTO": "off",
                "CARGO_PROFILE_DEV_DEBUG": "line-tables-only",
                "INSTA_FORCE_PASS": "0",
                "INSTA_UPDATE": "no",
                "MDTEST_UPDATE_SNAPSHOTS": "0",
            },
        )
        revision = current.base_revision
        edits = [step for step in current.steps if step["kind"] == "edit"]
        self.assertEqual(len(edits), 3)
        for step in edits:
            self.assertEqual(step["parent"], revision)
            revision = step["commit"]
        self.assertEqual(revision, "4b00c689c3d91bb17866ec08de549479d6d8dcca")
        for step in (*current.warmup, *current.steps):
            if step["kind"] != "command":
                continue
            arguments = step["args"]
            if any("mdtest::" in argument for argument in arguments):
                target = arguments.index("--test")
                self.assertEqual(arguments[target + 1], "mdtest")

        options = replay.parser().parse_args(
            [
                "--project",
                "ruff",
                "--output-dir",
                str(self.directory / "ruff-output"),
            ]
        )
        runner = replay.Replay(options)
        self.assertEqual(runner.scenarios, [current])
        for label, selector in runner.toolchains:
            environment = runner.environment(current, label, selector, 0)
            for key, value in current.environment.items():
                self.assertEqual(environment[key], value)

    def test_codex_fixture_uses_reviewed_setup_patch(self) -> None:
        directory = SCRIPTS / "session_replays"
        fixture = directory / "codex-rust-1.99.json"
        descriptor = {
            "label": "Bound safety-retry goal accounting by elapsed wall time",
            "patch": "patches/codex-safety-retry-goal-accounting.patch",
            "sha256": (
                "af822ae0a81f239b71e5b3c0d7f947ccce96fea032571d24f809a151af98af3a"
            ),
            "paths": ["codex-rs/tui/src/app/tests/safety_buffering.rs"],
        }
        self.assertIn(descriptor, json.loads(fixture.read_text())["setup_patches"])
        self.assertEqual(replay.load_scenario(fixture).project, "codex")
        patch_path = directory / descriptor["patch"]
        patch = patch_path.read_bytes()
        self.assertEqual(hashlib.sha256(patch).hexdigest(), descriptor["sha256"])
        self.assertEqual(replay.setup_patch_bytes(directory, descriptor), patch)
        scope = replay.command_output(
            ["git", "apply", "--numstat", str(patch_path)], cwd=self.directory
        )
        self.assertEqual(
            [line.split("\t", 2)[2] for line in scope.splitlines()],
            descriptor["paths"],
        )

    def test_historical_ruff_results_match_the_rust_1_99_fixture(self) -> None:
        fixture = SCRIPTS / "session_replays" / "ruff-historical-rust-1.99.json"
        scenario = replay.load_scenario(fixture)
        baseline = latest_reports()["historical"]

        fixture_sha256 = hashlib.sha256(fixture.read_bytes()).hexdigest()
        if "failure" in baseline:
            failure = baseline["failure"]
            self.assertEqual(failure["project"], scenario.project)
            self.assertEqual(failure["source_revision"], scenario.base_revision)
            self.assertEqual(failure["accepted_comparisons"], 0)
            self.assertEqual(
                failure["fixture"], fixture.relative_to(SCRIPTS.parent).as_posix()
            )
            self.assertEqual(
                baseline["provenance"]["fixtures"], {failure["fixture"]: fixture_sha256}
            )
            self.assertIn(failure["step"], range(1, len(scenario.steps) + 1))
            step = scenario.steps[failure["step"] - 1]
            self.assertEqual(step["kind"], "command")
            self.assertEqual(failure["command"], [step["program"], *step["args"]])
            return

        self.assertEqual(baseline["order"], [["stock", "ohm"], ["ohm", "stock"]])
        self.assertTrue(baseline["methodology"]["matching_test_counts_within_pairs"])
        self.assertEqual(
            {
                Path(name).name: digest
                for name, digest in baseline["provenance"]["wrapper"]["fixtures"].items()
            },
            {fixture.name: fixture_sha256},
        )
        commands = baseline["commands"]["ruff"]
        expected = [
            (index, step)
            for index, step in enumerate(scenario.steps, start=1)
            if step["kind"] == "command"
        ]
        self.assertEqual(len(commands), len(expected))
        for command, (index, step) in zip(commands, expected, strict=True):
            self.assertEqual(command["index"], index)
            self.assertEqual(command["command"], [step["program"], *step["args"]])

    def test_current_ruff_results_match_the_fixture(self) -> None:
        fixture = SCRIPTS / "session_replays" / "ruff-rust-1.99.json"
        scenario = replay.load_scenario(fixture)
        baseline = latest_reports()["sessions"]
        self.assertEqual(
            baseline["order_by_project"]["ruff"],
            [["stock", "ohm"], ["ohm", "stock"]],
        )
        wrapper = baseline["provenance"]["wrapper"]["by_project"]["ruff"]
        self.assertEqual(
            {Path(name).name: digest for name, digest in wrapper["fixtures"].items()},
            {fixture.name: hashlib.sha256(fixture.read_bytes()).hexdigest()},
        )
        session = next(s for s in baseline["sessions"] if s["project"] == "ruff")
        self.assertEqual(session["session"], scenario.session)
        self.assertTrue(baseline["methodology"]["all_commands_succeeded"])
        self.assertEqual(baseline["methodology"]["external_compilations_observed"], 0)
        commands = baseline["commands"]["ruff"]
        expected = [
            (index, step)
            for index, step in enumerate(scenario.steps, start=1)
            if step["kind"] == "command"
        ]
        self.assertEqual(len(commands), 12)
        for command, (index, step) in zip(commands, expected, strict=True):
            self.assertEqual(command["index"], index)
            self.assertEqual(command["command"], [step["program"], *step["args"]])
            self.assertEqual(
                command["tests_started"]["stock"], command["tests_started"]["ohm"]
            )
        for toolchain in ("stock", "ohm"):
            self.assertEqual(
                len(baseline["timed_session_seconds"]["ruff"][toolchain]),
                baseline["repetitions"],
            )
            for repetition in range(baseline["repetitions"]):
                self.assertAlmostEqual(
                    sum(
                        command["wall_seconds"][toolchain][repetition]
                        for command in commands
                    ),
                    baseline["timed_command_seconds"]["ruff"][toolchain][repetition],
                )

    def test_rejects_incomplete_or_uppercase_commit_shas(self) -> None:
        for revision in ("abc123", "A" * 40, None):
            with self.subTest(revision=revision):
                with self.assertRaisesRegex(replay.BenchmarkError, "commit SHA"):
                    self.scenario(base_revision=revision)

    def test_rejects_managed_environment_overrides(self) -> None:
        for name in ("HOME", "CARGO_HOME", "CARGO_TARGET_DIR", "RUSTUP_TOOLCHAIN"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(replay.BenchmarkError, "managed"):
                    self.scenario(environment={name: "unsafe"})

    def test_rejects_unrestricted_fetch_references(self) -> None:
        for reference in ("main", "--upload-pack=unsafe", 1):
            with self.subTest(reference=reference):
                with self.assertRaisesRegex(replay.BenchmarkError, "references"):
                    self.scenario(fetch_refs=[reference])

    def test_rejects_commands_with_their_own_toolchain(self) -> None:
        with self.assertRaisesRegex(replay.BenchmarkError, "own toolchain"):
            self.scenario(
                steps=[
                    {
                        "kind": "command",
                        "label": "Attempt to override toolchain",
                        "program": "cargo",
                        "args": ["+nightly", "test"],
                    }
                ]
            )

    def test_warmups_cannot_modify_sources(self) -> None:
        with self.assertRaisesRegex(replay.BenchmarkError, "warmups cannot edit"):
            self.scenario(
                warmup=[
                    {
                        "kind": "edit",
                        "label": "Illegal untimed source edit",
                        "parent": "a" * 40,
                        "commit": "b" * 40,
                    }
                ]
            )

    def test_rejects_patch_and_command_paths_outside_owned_directories(self) -> None:
        cases = (
            {"kind": "edit", "label": "Escape via patch", "patch": "../outside"},
            {
                "kind": "edit",
                "label": "Escape via source path",
                "parent": "a" * 40,
                "commit": "b" * 40,
                "paths": ["../../private"],
            },
            {
                "kind": "command",
                "label": "Escape via command directory",
                "program": "cargo",
                "args": ["check"],
                "cwd": "/private/source",
            },
        )
        for step in cases:
            with self.subTest(step=step["label"]):
                with self.assertRaisesRegex(replay.BenchmarkError, "owned directory"):
                    self.scenario(steps=[step])


class ToolchainIsolationTests(ReplayTestCase):
    def test_cargo_selects_the_requested_toolchain(self) -> None:
        step = {"program": "cargo", "args": ["nextest", "run", "-p", "package"]}
        self.assertEqual(
            replay.Replay.command(step, "1.97.1"),
            ["cargo", "+1.97.1", "nextest", "run", "-p", "package"],
        )
        self.assertEqual(
            replay.Replay.command(step, "ohm"),
            ["cargo", "+ohm", "nextest", "run", "-p", "package"],
        )

    def test_just_uses_the_managed_rustup_environment(self) -> None:
        step = {"program": "just", "args": ["test", "-p", "codex-tui"]}
        self.assertEqual(
            replay.Replay.command(step, "ohm"),
            ["just", "test", "-p", "codex-tui"],
        )

    def test_stock_and_ohm_have_private_targets_and_trust_settings(self) -> None:
        scenario = self.scenario(environment={"CARGO_PROFILE_DEV_OPT_LEVEL": "1"})
        runner = self.runner("--jobs", "4")
        inherited = {
            "PATH": "/usr/bin",
            "RUSTUP_TOOLCHAIN": "nightly",
            "RUSTFLAGS": "--cfg=unfair",
            "CARGO_BUILD_BUILD_DIR": "/shared/unsafe",
            "CARGO_TERM_VERBOSE": "true",
            "CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST": "all",
            "CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST": "all",
        }

        with mock.patch.dict(os.environ, inherited, clear=True):
            stock = runner.environment(scenario, "stock", "1.97.1", 0)
            ohm = runner.environment(scenario, "ohm", "ohm", 0)

        self.assertEqual(stock["RUSTUP_TOOLCHAIN"], "1.97.1")
        self.assertEqual(ohm["RUSTUP_TOOLCHAIN"], "ohm")
        self.assertEqual(stock["CARGO_BUILD_JOBS"], ohm["CARGO_BUILD_JOBS"])
        self.assertEqual(stock["CARGO_PROFILE_DEV_OPT_LEVEL"], "1")
        self.assertNotEqual(stock["CARGO_TARGET_DIR"], ohm["CARGO_TARGET_DIR"])
        self.assertNotIn("RUSTFLAGS", stock)
        self.assertNotIn("RUSTFLAGS", ohm)
        self.assertNotIn("CARGO_TERM_VERBOSE", stock)
        self.assertNotIn("CARGO_TERM_VERBOSE", ohm)
        self.assertNotIn("CARGO_BUILD_BUILD_DIR", stock)
        self.assertNotIn("CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST", stock)
        self.assertNotIn("CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST", stock)
        self.assertIn("CARGO_BUILD_BUILD_DIR", ohm)
        self.assertEqual(ohm["CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST"], "all")
        paths = stock["PATH"].split(os.pathsep)
        self.assertEqual(
            paths[:2],
            [str(Path.home() / ".local/bin"), str(Path.home() / ".cargo/bin")],
        )

    def test_compiler_accounting_enables_equal_cargo_verbosity(self) -> None:
        scenario = self.scenario()
        runner = self.runner("--compiler-accounting", "verbose")

        with mock.patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True):
            stock = runner.environment(scenario, "stock", "1.97.1", 0)
            ohm = runner.environment(scenario, "ohm", "ohm", 0)

        self.assertEqual(stock["CARGO_TERM_VERBOSE"], "true")
        self.assertEqual(ohm["CARGO_TERM_VERBOSE"], "true")


class ProcessIsolationTests(unittest.TestCase):
    def test_reparented_owned_compilers_remain_in_the_benchmark_group(self) -> None:
        processes = "\n".join(
            [
                "10 1 10 bash",
                "20 10 20 python3",
                "30 20 20 cargo",
                "40 1 20 cc1",
                "50 1 50 rustc",
                "60 1 60 python3",
            ]
        )
        with mock.patch.object(replay, "command_output", return_value=processes):
            self.assertEqual(replay.competing_processes(owner=20), ["50 rustc"])

    def test_process_inspection_fails_closed_for_invalid_snapshots(self) -> None:
        for processes in ("", "20 1 python3", "wrong 1 20 python3", "30 1 30 rustc"):
            with self.subTest(processes=processes):
                with mock.patch.object(
                    replay, "command_output", return_value=processes
                ):
                    with self.assertRaises(replay.BenchmarkError):
                        replay.competing_processes(owner=20)


class FeatureMatrixTests(ReplayTestCase):
    def test_matrix_is_opt_in_and_uses_one_compiler_for_all_feature_cells(self) -> None:
        default = self.runner("--upstream", "1.97.1", "--ohm", "custom-ohm")
        self.assertFalse(default.options.feature_matrix)
        self.assertEqual(
            default.toolchains, (("stock", "1.97.1"), ("ohm", "custom-ohm"))
        )

        matrix = self.runner(
            "--feature-matrix", "--upstream", "ignored-stock", "--ohm", "custom-ohm"
        )
        self.assertTrue(matrix.options.feature_matrix)
        self.assertEqual(
            matrix.toolchains,
            (
                ("ohm-all", "custom-ohm"),
                ("ohm-no-public-api-hash", "custom-ohm"),
                ("ohm-no-proc-macro-cache", "custom-ohm"),
                ("ohm-neither", "custom-ohm"),
            ),
        )

    def test_shared_build_is_opt_out_for_the_standard_stock_and_ohm_comparison(
        self,
    ) -> None:
        scenario = self.scenario(environment={"CARGO_PROFILE_DEV_OPT_LEVEL": "1"})
        shared = self.runner("--ohm", "custom-ohm", "--jobs", "4")
        isolated = self.runner(
            "--no-shared-build", "--ohm", "custom-ohm", "--jobs", "4"
        )
        inherited = {"PATH": "/usr/bin", "CARGO_BUILD_BUILD_DIR": "/shared/unsafe"}

        self.assertFalse(shared.options.no_shared_build)
        self.assertTrue(isolated.options.no_shared_build)
        self.assertEqual(shared.toolchains, isolated.toolchains)

        with mock.patch.dict(os.environ, inherited, clear=True):
            for label, selector in shared.toolchains:
                with self.subTest(label=label):
                    enabled = shared.environment(scenario, label, selector, 3)
                    disabled = isolated.environment(scenario, label, selector, 3)
                    self.assertNotIn("CARGO_BUILD_BUILD_DIR", disabled)
                    if label == "ohm":
                        self.assertEqual(
                            enabled.pop("CARGO_BUILD_BUILD_DIR"),
                            str(shared.output / "shared-build" / "ruff" / "3"),
                        )
                        self.assertEqual(
                            disabled["CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST"], "all"
                        )
                    else:
                        self.assertNotIn("CARGO_BUILD_BUILD_DIR", enabled)
                        self.assertNotIn(
                            "CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST", disabled
                        )
                    self.assertEqual(enabled, disabled)

    def test_matrix_cells_have_isolated_artifacts_and_exact_feature_overrides(
        self,
    ) -> None:
        scenario = self.scenario(environment={"CARGO_PROFILE_DEV_OPT_LEVEL": "1"})
        runner = self.runner("--feature-matrix", "--ohm", "custom-ohm", "--jobs", "4")
        expected_flags = {
            "ohm-all": None,
            "ohm-no-public-api-hash": "-Zpublic-api-hash=no",
            "ohm-no-proc-macro-cache": "-Zcache-proc-macros=no",
            "ohm-neither": "-Zpublic-api-hash=no -Zcache-proc-macros=no",
        }
        inherited = {
            "PATH": "/usr/bin",
            "PRESERVE_ME": "yes",
            "RUSTFLAGS": "--cfg=unfair",
            "CARGO_ENCODED_RUSTFLAGS": "--cfg=also-unfair",
            "CARGO_BUILD_BUILD_DIR": "/shared/unsafe",
            "CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST": "inherited",
            "CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST": "all",
        }
        targets = set()
        shared_builds = set()

        with mock.patch.dict(os.environ, inherited, clear=True):
            for label, selector in runner.toolchains:
                with self.subTest(label=label):
                    environment = runner.environment(scenario, label, selector, 7)
                    self.assertEqual(environment["RUSTUP_TOOLCHAIN"], "custom-ohm")
                    self.assertEqual(environment["CARGO_BUILD_JOBS"], "4")
                    self.assertEqual(environment["CARGO_PROFILE_DEV_OPT_LEVEL"], "1")
                    self.assertEqual(environment["PRESERVE_ME"], "yes")
                    self.assertEqual(
                        environment["CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST"], "all"
                    )
                    self.assertNotIn(
                        "CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST", environment
                    )
                    self.assertNotIn("CARGO_ENCODED_RUSTFLAGS", environment)
                    self.assertEqual(
                        environment.get("RUSTFLAGS"), expected_flags[label]
                    )

                    target = runner.output / "targets" / "ruff" / label / "7"
                    shared = runner.output / "shared-build" / "ruff" / label / "7"
                    self.assertEqual(environment["CARGO_TARGET_DIR"], str(target))
                    self.assertEqual(environment["CARGO_BUILD_BUILD_DIR"], str(shared))
                    self.assertNotEqual(target, shared)
                    targets.add(target)
                    shared_builds.add(shared)

        self.assertEqual(len(targets), 4)
        self.assertEqual(len(shared_builds), 4)

    def test_matrix_can_disable_shared_build_without_changing_feature_cells(
        self,
    ) -> None:
        scenario = self.scenario(environment={"CARGO_PROFILE_DEV_OPT_LEVEL": "1"})
        shared = self.runner("--feature-matrix", "--ohm", "custom-ohm", "--jobs", "4")
        isolated = self.runner(
            "--feature-matrix",
            "--no-shared-build",
            "--ohm",
            "custom-ohm",
            "--jobs",
            "4",
        )
        inherited = {
            "PATH": "/usr/bin",
            "RUSTFLAGS": "--cfg=unfair",
            "CARGO_ENCODED_RUSTFLAGS": "--cfg=also-unfair",
            "CARGO_BUILD_BUILD_DIR": "/shared/unsafe",
        }
        targets = set()

        self.assertEqual(shared.toolchains, isolated.toolchains)
        with mock.patch.dict(os.environ, inherited, clear=True):
            for label, selector in shared.toolchains:
                with self.subTest(label=label):
                    enabled = shared.environment(scenario, label, selector, 5)
                    disabled = isolated.environment(scenario, label, selector, 5)

                    self.assertEqual(
                        enabled.pop("CARGO_BUILD_BUILD_DIR"),
                        str(shared.output / "shared-build" / "ruff" / label / "5"),
                    )
                    self.assertNotIn("CARGO_BUILD_BUILD_DIR", disabled)
                    self.assertNotIn("CARGO_ENCODED_RUSTFLAGS", disabled)
                    self.assertEqual(disabled["RUSTUP_TOOLCHAIN"], "custom-ohm")
                    self.assertEqual(disabled["CARGO_BUILD_JOBS"], "4")
                    self.assertEqual(disabled["CARGO_PROFILE_DEV_OPT_LEVEL"], "1")
                    self.assertEqual(
                        disabled["CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST"], "all"
                    )
                    self.assertEqual(
                        disabled["CARGO_TARGET_DIR"],
                        str(isolated.output / "targets" / "ruff" / label / "5"),
                    )
                    self.assertEqual(enabled, disabled)
                    targets.add(disabled["CARGO_TARGET_DIR"])

        self.assertEqual(len(targets), 4)

    def test_matrix_warmups_and_timed_commands_preserve_each_cells_tracked_flags(
        self,
    ) -> None:
        runner = self.runner("--feature-matrix")
        scenario = self.scenario()
        worktree = self.directory / "worktree"
        worktree.mkdir()
        step = {"program": "cargo", "args": ["check", "-p", "package"]}
        result = subprocess.CompletedProcess([], 0, stdout="Checking package\n")

        for label, selector in runner.toolchains:
            with self.subTest(label=label):
                with mock.patch.object(
                    replay.subprocess, "run", return_value=result
                ) as command:
                    warmup = runner.run_command(
                        scenario,
                        worktree,
                        step,
                        label,
                        selector,
                        0,
                        1,
                        phase="warmup",
                    )
                    timed = runner.run_command(
                        scenario, worktree, step, label, selector, 0, 1
                    )

                warmup_environment = command.call_args_list[0].kwargs["env"]
                timed_environment = command.call_args_list[1].kwargs["env"]
                self.assertEqual(warmup_environment, timed_environment)
                self.assertEqual(
                    command.call_args_list[0].args[0][:2], ["cargo", "+ohm"]
                )
                self.assertEqual(
                    command.call_args_list[1].args[0][:2], ["cargo", "+ohm"]
                )
                self.assertEqual(Path(warmup["log"]).name, "warmup-01.log")
                self.assertEqual(Path(timed["log"]).name, "01.log")
                self.assertEqual(Path(warmup["log"]).parent.name, "0")
                self.assertEqual(Path(warmup["log"]).parent.parent.name, label)

    def test_matrix_rotates_the_balanced_four_cell_execution_order(self) -> None:
        runner = self.runner("--feature-matrix", "--repetitions", "4")
        with (
            mock.patch.object(runner, "check_disk"),
            mock.patch.object(runner, "prepare_source", return_value=self.directory),
            mock.patch.object(runner, "run_session") as session,
            mock.patch.object(runner, "summarize"),
        ):
            runner.run()

        observed = [call.args[1] for call in session.call_args_list]
        self.assertEqual(
            observed,
            [
                "ohm-all",
                "ohm-no-public-api-hash",
                "ohm-neither",
                "ohm-no-proc-macro-cache",
                "ohm-no-public-api-hash",
                "ohm-no-proc-macro-cache",
                "ohm-all",
                "ohm-neither",
                "ohm-no-proc-macro-cache",
                "ohm-neither",
                "ohm-no-public-api-hash",
                "ohm-all",
                "ohm-neither",
                "ohm-all",
                "ohm-no-proc-macro-cache",
                "ohm-no-public-api-hash",
            ],
        )

    def test_matrix_metadata_and_summary_report_both_marginal_feature_effects(
        self,
    ) -> None:
        runner = self.runner("--feature-matrix", "--ohm", "custom-ohm")
        values = {
            "ohm-all": 80.0,
            "ohm-no-public-api-hash": 100.0,
            "ohm-no-proc-macro-cache": 90.0,
            "ohm-neither": 120.0,
        }
        runner.samples = [
            {"project": "ruff", "toolchain": label, "wall_seconds": seconds}
            for label, seconds in values.items()
        ]
        runner.persist()

        results = json.loads((runner.output / "results.json").read_text())
        self.assertTrue(results["feature_matrix"])
        self.assertTrue(results["shared_build_enabled"])
        self.assertEqual(
            results["toolchains"], {label: "custom-ohm" for label in values}
        )

        with mock.patch("builtins.print") as output:
            runner.summarize()
        rendered = "\n".join(str(call.args[0]) for call in output.call_args_list)
        for label in values:
            self.assertIn(label, rendered)
        self.assertIn("shared build enabled", rendered)
        self.assertIn("marginal public API hashing: +25.00s benefit (+22.7%)", rendered)
        self.assertIn("marginal proc-macro caching: +15.00s benefit (+14.3%)", rendered)

    def test_no_shared_build_is_recorded_in_metadata_and_summary(self) -> None:
        cases = (
            ("--no-shared-build",),
            ("--feature-matrix", "--no-shared-build"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                runner = self.runner(*arguments)
                runner.persist()
                results = json.loads((runner.output / "results.json").read_text())
                self.assertFalse(results["shared_build_enabled"])
                self.assertEqual(
                    results["feature_matrix"], "--feature-matrix" in arguments
                )

                with mock.patch("builtins.print") as output:
                    runner.summarize()
                self.assertIn(
                    "shared build disabled",
                    "\n".join(str(call.args[0]) for call in output.call_args_list),
                )


class ResumeTests(ReplayTestCase):
    @staticmethod
    def git(repository: Path, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repository), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        ).stdout.strip()

    def repository(self, name: str = "source") -> tuple[Path, str]:
        source = self.directory / name
        source.mkdir()
        self.git(source, "init", "--quiet")
        self.git(source, "config", "user.email", "session-replay-test@example.invalid")
        self.git(source, "config", "user.name", "Session replay test")
        self.git(source, "config", "commit.gpgsign", "false")
        (source / "README.md").write_text(f"session replay {name}\n")
        self.git(source, "add", "README.md")
        self.git(source, "commit", "--quiet", "-m", "baseline")
        return source, self.git(source, "rev-parse", "HEAD")

    def owned_worktree(self, source: Path, revision: str, label: str = "stock") -> Path:
        worktree = self.directory / "output" / "worktrees" / "ruff" / label / "0"
        worktree.parent.mkdir(parents=True, exist_ok=True)
        self.git(
            source, "worktree", "add", "--quiet", "--detach", str(worktree), revision
        )
        return worktree

    @staticmethod
    def completed_sample(label: str = "stock") -> dict[str, object]:
        return {
            "project": "ruff",
            "session_id": "real-session",
            "toolchain": label,
            "selector": "1.99.0" if label == "stock" else "ohm",
            "repetition": 0,
            "wall_seconds": 1.0,
        }

    def test_resume_requires_existing_results_and_accepts_legacy_metadata(self) -> None:
        with self.assertRaisesRegex(replay.BenchmarkError, "cannot resume"):
            self.runner("--resume")

        initial = self.runner()
        initial.samples = [self.completed_sample()]
        initial.persist()
        destination = initial.output / "results.json"
        previous = json.loads(destination.read_text())
        for key in (
            "feature_matrix",
            "shared_build_enabled",
            "compiler_accounting",
            "repetitions",
        ):
            previous.pop(key)
        destination.write_text(json.dumps(previous))

        with mock.patch("builtins.print"):
            resumed = self.runner("--resume")
        self.assertTrue(resumed.options.resume)
        self.assertEqual(resumed.samples, [self.completed_sample()])

    def test_resume_rejects_incompatible_settings_scenarios_and_samples(self) -> None:
        initial = self.runner()
        initial.samples = [self.completed_sample()]
        initial.persist()
        destination = initial.output / "results.json"
        baseline = json.loads(destination.read_text())

        cases = {
            "jobs": lambda data: data.update(jobs=99),
            "toolchain": lambda data: data["toolchains"].update(ohm="different"),
            "feature matrix": lambda data: data.update(feature_matrix=True),
            "shared build": lambda data: data.update(shared_build_enabled=False),
            "compiler accounting": lambda data: data.update(
                compiler_accounting="verbose"
            ),
            "repetitions": lambda data: data.update(repetitions=2),
            "session": lambda data: data["sessions"][0]["session"].update(
                id="different"
            ),
            "base revision": lambda data: data["sessions"][0].update(
                base_revision="b" * 40
            ),
            "command count": lambda data: data["sessions"][0].update(commands=99),
            "sample selector": lambda data: data["samples"][0].update(
                selector="different"
            ),
            "duplicate sample": lambda data: data["samples"].append(
                data["samples"][0].copy()
            ),
        }
        for description, mutate in cases.items():
            with self.subTest(reason=description):
                previous = json.loads(json.dumps(baseline))
                mutate(previous)
                destination.write_text(json.dumps(previous))
                with self.assertRaises(replay.BenchmarkError):
                    self.runner("--resume")

    def test_resume_skips_completed_samples_and_preserves_their_targets_and_logs(
        self,
    ) -> None:
        initial = self.runner()
        initial.samples = [self.completed_sample()]
        initial.persist()
        target = initial.output / "targets" / "ruff" / "stock" / "0"
        target.mkdir(parents=True)
        artifact = target / "completed-artifact"
        artifact.write_text("preserve me")
        logs = initial.output / "logs" / "ruff" / "stock" / "0"
        logs.mkdir(parents=True)
        existing_log = logs / "warmup-01.log"
        existing_log.write_text("existing warmup diagnostics")

        with mock.patch("builtins.print"):
            resumed = self.runner("--resume")
            with (
                mock.patch.object(resumed, "check_disk"),
                mock.patch.object(
                    resumed, "prepare_source", return_value=self.directory
                ),
                mock.patch.object(resumed, "run_session") as session,
                mock.patch.object(resumed, "summarize"),
            ):
                resumed.run()

        self.assertEqual(len(session.call_args_list), 1)
        self.assertEqual(session.call_args.args[1:], ("ohm", "ohm", 0))
        self.assertEqual(artifact.read_text(), "preserve me")
        self.assertEqual(existing_log.read_text(), "existing warmup diagnostics")
        persisted = json.loads((resumed.output / "results.json").read_text())
        self.assertEqual(persisted["samples"], [self.completed_sample()])

    def test_resume_archives_partial_targets_and_logs_before_restarting_cold(
        self,
    ) -> None:
        source, revision = self.repository()
        scenario = self.scenario(base_revision=revision)
        initial = self.runner()
        initial.persist()
        worktree = self.owned_worktree(source, revision)
        target = initial.output / "targets" / "ruff" / "stock" / "0"
        target.mkdir(parents=True)
        partial = target / "partially-built-artifact"
        partial.write_text("preserve me")
        logs = initial.output / "logs" / "ruff" / "stock" / "0"
        logs.mkdir(parents=True)
        (logs / "warmup-01.log").write_text("interrupted diagnostics")

        def result(*_args: object, **_kwargs: object) -> dict[str, object]:
            self.assertFalse(target.exists(), "the restarted target must begin cold")
            return {
                "kind": "command",
                "wall_seconds": 0.01,
                "cargo_reported_crates": [],
                "actual_compiler_invocations": None,
                "tests_started": 1,
            }

        with mock.patch("builtins.print"):
            resumed = self.runner("--resume")
            resumed.sources["ruff"] = source
            with mock.patch.object(
                resumed, "run_command", side_effect=result
            ) as command:
                observed = resumed.run_session(scenario, "stock", "1.99.0", 0)

        self.assertEqual(len(command.call_args_list), 2)
        self.assertEqual(command.call_args_list[0].kwargs["phase"], "warmup")
        self.assertEqual(Path(observed["worktree"]).resolve(), worktree.resolve())
        self.assertEqual(len(observed["warmup_steps"]), 1)
        archive = initial.output / "interrupted" / "ruff" / "stock" / "0" / "0"
        self.assertEqual(
            (archive / "target" / "partially-built-artifact").read_text(),
            "preserve me",
        )
        self.assertEqual(
            (archive / "logs" / "warmup-01.log").read_text(),
            "interrupted diagnostics",
        )
        self.assertEqual(self.git(archive / "worktree", "rev-parse", "HEAD"), revision)
        self.assertFalse(partial.exists())
        self.assertEqual(self.git(worktree, "status", "--porcelain"), "")

    def test_resume_archives_ohm_shared_build_without_touching_completed_stock(
        self,
    ) -> None:
        source, revision = self.repository()
        scenario = self.scenario(base_revision=revision)
        initial = self.runner()
        initial.samples = [self.completed_sample()]
        initial.persist()
        worktree = self.owned_worktree(source, revision, "ohm")
        interrupted = {
            "target": initial.output / "targets" / "ruff" / "ohm" / "0",
            "logs": initial.output / "logs" / "ruff" / "ohm" / "0",
            "shared-build": initial.output / "shared-build" / "ruff" / "0",
        }
        for name, path in interrupted.items():
            path.mkdir(parents=True)
            (path / "preserved.txt").write_text(f"interrupted {name}")
        completed = initial.output / "targets" / "ruff" / "stock" / "0"
        completed.mkdir(parents=True)
        (completed / "preserved.txt").write_text("completed stock")

        def result(*_args: object, **_kwargs: object) -> dict[str, object]:
            self.assertTrue(all(not path.exists() for path in interrupted.values()))
            return {
                "kind": "command",
                "wall_seconds": 0.01,
                "cargo_reported_crates": [],
                "actual_compiler_invocations": None,
                "tests_started": 1,
            }

        with mock.patch("builtins.print"):
            resumed = self.runner("--resume")
            resumed.sources["ruff"] = source
            with mock.patch.object(resumed, "run_command", side_effect=result):
                resumed.run_session(scenario, "ohm", "ohm", 0)

        archive = initial.output / "interrupted" / "ruff" / "ohm" / "0" / "0"
        for name in interrupted:
            self.assertEqual(
                (archive / name / "preserved.txt").read_text(), f"interrupted {name}"
            )
        self.assertEqual(self.git(archive / "worktree", "rev-parse", "HEAD"), revision)
        self.assertEqual(self.git(worktree, "rev-parse", "HEAD"), revision)
        self.assertEqual((completed / "preserved.txt").read_text(), "completed stock")
        self.assertEqual(len(resumed.samples), 2)

    def test_resume_archives_only_the_interrupted_feature_matrix_cell(self) -> None:
        source, revision = self.repository()
        scenario = self.scenario(base_revision=revision)
        initial = self.runner("--feature-matrix")
        initial.persist()
        label = "ohm-no-public-api-hash"
        self.owned_worktree(source, revision, label)
        target = initial.output / "targets" / "ruff" / label / "0"
        shared = initial.output / "shared-build" / "ruff" / label / "0"
        other_shared = initial.output / "shared-build" / "ruff" / "ohm-all" / "0"
        for path in (target, shared, other_shared):
            path.mkdir(parents=True)
            (path / "preserved.txt").write_text(path.parent.name)

        with mock.patch("builtins.print"):
            resumed = self.runner("--feature-matrix", "--resume")
            resumed.sources["ruff"] = source
            with mock.patch.object(
                resumed,
                "run_command",
                return_value={
                    "kind": "command",
                    "wall_seconds": 0.01,
                    "cargo_reported_crates": [],
                    "actual_compiler_invocations": None,
                    "tests_started": 1,
                },
            ):
                resumed.run_session(scenario, label, "ohm", 0)

        archive = initial.output / "interrupted" / "ruff" / label / "0" / "0"
        self.assertEqual((archive / "target" / "preserved.txt").read_text(), label)
        self.assertEqual(
            (archive / "shared-build" / "preserved.txt").read_text(), label
        )
        self.assertEqual((other_shared / "preserved.txt").read_text(), "ohm-all")

    def test_resume_archives_orphaned_target_before_creating_a_fresh_worktree(
        self,
    ) -> None:
        source, revision = self.repository()
        scenario = self.scenario(base_revision=revision)
        initial = self.runner()
        initial.persist()
        target = initial.output / "targets" / "ruff" / "stock" / "0"
        target.mkdir(parents=True)
        (target / "preserved.txt").write_text("orphaned partial target")

        with mock.patch("builtins.print"):
            resumed = self.runner("--resume")
            resumed.sources["ruff"] = source
            with mock.patch.object(
                resumed,
                "run_command",
                return_value={
                    "kind": "command",
                    "wall_seconds": 0.01,
                    "cargo_reported_crates": [],
                    "actual_compiler_invocations": None,
                    "tests_started": 1,
                },
            ):
                resumed.run_session(scenario, "stock", "1.99.0", 0)

        archive = initial.output / "interrupted" / "ruff" / "stock" / "0" / "0"
        self.assertEqual(
            (archive / "target" / "preserved.txt").read_text(),
            "orphaned partial target",
        )
        self.assertFalse((archive / "worktree").exists())

    def test_resume_cannot_restart_an_already_completed_sample(self) -> None:
        source, revision = self.repository()
        scenario = self.scenario(base_revision=revision)
        initial = self.runner()
        initial.samples = [self.completed_sample()]
        initial.persist()
        worktree = self.owned_worktree(source, revision)

        with mock.patch("builtins.print"):
            resumed = self.runner("--resume")
        resumed.sources["ruff"] = source
        with self.assertRaisesRegex(replay.BenchmarkError, "already completed"):
            resumed.run_session(scenario, "stock", "1.99.0", 0)

        self.assertEqual(self.git(worktree, "rev-parse", "HEAD"), revision)

    def test_resume_archives_dirty_owned_worktrees_without_losing_edits(self) -> None:
        source, revision = self.repository()
        scenario = self.scenario(base_revision=revision)
        initial = self.runner()
        initial.persist()
        worktree = self.owned_worktree(source, revision)
        dirty = worktree / "interrupted-edit.txt"
        dirty.write_text("never discard this")

        with mock.patch("builtins.print"):
            resumed = self.runner("--resume")
            resumed.sources["ruff"] = source
            with mock.patch.object(
                resumed,
                "run_command",
                return_value={
                    "kind": "command",
                    "wall_seconds": 0.01,
                    "cargo_reported_crates": [],
                    "actual_compiler_invocations": None,
                    "tests_started": 1,
                },
            ):
                resumed.run_session(scenario, "stock", "1.99.0", 0)

        archived = (
            initial.output
            / "interrupted"
            / "ruff"
            / "stock"
            / "0"
            / "0"
            / "worktree"
            / "interrupted-edit.txt"
        )
        self.assertEqual(archived.read_text(), "never discard this")
        self.assertFalse(dirty.exists())

    def test_resume_rejects_artifact_symlinks_without_moving_the_worktree(self) -> None:
        source, revision = self.repository()
        scenario = self.scenario(base_revision=revision)
        initial = self.runner()
        initial.persist()
        worktree = self.owned_worktree(source, revision)
        external = self.directory / "external-user-artifacts"
        external.mkdir()
        (external / "untouched.txt").write_text("never move user artifacts")
        target = initial.output / "targets" / "ruff" / "stock" / "0"
        target.parent.mkdir(parents=True)
        target.symlink_to(external, target_is_directory=True)

        with mock.patch("builtins.print"):
            resumed = self.runner("--resume")
        resumed.sources["ruff"] = source
        with self.assertRaisesRegex(replay.BenchmarkError, "owned artifact"):
            resumed.run_session(scenario, "stock", "1.99.0", 0)

        self.assertEqual(self.git(worktree, "rev-parse", "HEAD"), revision)
        self.assertEqual(
            (external / "untouched.txt").read_text(), "never move user artifacts"
        )

    def test_resume_rejects_wrong_revision_and_worktrees_from_other_sources(
        self,
    ) -> None:
        source, baseline = self.repository()
        scenario = self.scenario(base_revision=baseline)
        initial = self.runner()
        initial.persist()

        (source / "next.txt").write_text("next revision\n")
        self.git(source, "add", "next.txt")
        self.git(source, "commit", "--quiet", "-m", "different revision")
        next_revision = self.git(source, "rev-parse", "HEAD")
        wrong_revision = self.owned_worktree(source, next_revision, "stock")
        other_source, other_revision = self.repository("unrelated")
        wrong_source = self.owned_worktree(other_source, other_revision, "ohm")

        with mock.patch("builtins.print"):
            resumed = self.runner("--resume")
        resumed.sources["ruff"] = source

        with self.assertRaisesRegex(replay.BenchmarkError, "exact base revision"):
            resumed.run_session(scenario, "stock", "1.99.0", 0)
        with self.assertRaisesRegex(replay.BenchmarkError, "different source"):
            resumed.run_session(scenario, "ohm", "ohm", 0)

        self.assertEqual(self.git(wrong_revision, "rev-parse", "HEAD"), next_revision)
        self.assertEqual(self.git(wrong_source, "rev-parse", "HEAD"), other_revision)

    def test_existing_worktree_still_fails_without_explicit_resume(self) -> None:
        source, revision = self.repository()
        scenario = self.scenario(base_revision=revision)
        runner = self.runner()
        runner.sources["ruff"] = source
        worktree = self.owned_worktree(source, revision)

        self.assertFalse(runner.options.resume)
        with self.assertRaisesRegex(replay.BenchmarkError, "already exists"):
            runner.run_session(scenario, "stock", "1.99.0", 0)
        self.assertEqual(self.git(worktree, "rev-parse", "HEAD"), revision)


class SetupPatchTests(ReplayTestCase):
    git = staticmethod(ResumeTests.git)

    def setUp(self) -> None:
        super().setUp()
        self.source, self.revision = ResumeTests.repository(self)
        self.before = (self.source / "README.md").read_bytes()
        self.after = b"session replay prepared\n"
        (self.source / "README.md").write_bytes(self.after)
        self.patch = (self.git(self.source, "diff", "--", "README.md") + "\n").encode()
        (self.source / "README.md").write_bytes(self.before)
        self.patch_file = self.directory / "setup.patch"
        self.descriptor = self.write_patch(self.patch)
        self.scenario(base_revision=self.revision, setup_patches=[self.descriptor])

    def write_patch(self, patch: bytes, **changes: object) -> dict[str, object]:
        self.patch_file.write_bytes(patch)
        return {
            "label": "Prepare deterministic test timing",
            "patch": "setup.patch",
            "sha256": hashlib.sha256(patch).hexdigest(),
            "paths": ["README.md"],
            **changes,
        }

    @staticmethod
    def command_result() -> dict[str, object]:
        return {
            "kind": "command",
            "wall_seconds": 0.01,
            "cargo_reported_crates": [],
            "actual_compiler_invocations": None,
            "tests_started": 1,
        }

    def complete_cells(self) -> object:
        runner = self.runner()
        runner.sources["ruff"] = self.source
        with (
            mock.patch.object(
                runner,
                "run_command",
                side_effect=lambda *args, **kwargs: self.command_result(),
            ),
            mock.patch("builtins.print"),
        ):
            for label, selector in runner.toolchains:
                runner.run_session(runner.scenarios[0], label, selector, 0)
        return runner

    def test_setup_descriptors_require_exact_hashes_and_canonical_paths(self) -> None:
        invalid = [
            None,
            {},
            [None],
            [{**self.descriptor, "label": " "}],
            [{**self.descriptor, "sha256": "A" * 64}],
            [{**self.descriptor, "sha256": "0" * 64}],
            [{key: value for key, value in self.descriptor.items() if key != "sha256"}],
            [{**self.descriptor, "unexpected": True}],
            [self.descriptor, self.descriptor],
        ]
        for paths in (
            [],
            "README.md",
            [None],
            ["README.md", "README.md"],
            ["."],
            ["./README.md"],
            ["../README.md"],
            ["/README.md"],
            ["a//README.md"],
            ["a/../README.md"],
        ):
            invalid.append([{**self.descriptor, "paths": paths}])
        for patch in (
            "../setup.patch",
            "./setup.patch",
            "/setup.patch",
            "missing.patch",
            ".",
        ):
            invalid.append([{**self.descriptor, "patch": patch}])
        for descriptors in invalid:
            with self.subTest(descriptors=descriptors):
                with self.assertRaises(replay.BenchmarkError):
                    self.scenario(setup_patches=descriptors)

        empty = self.write_patch(b"")
        with self.assertRaisesRegex(replay.BenchmarkError, "empty"):
            self.scenario(setup_patches=[empty])

    def test_setup_patch_inputs_reject_symlink_files_and_directories(self) -> None:
        (self.directory / "linked.patch").symlink_to(self.patch_file)
        (self.directory / "linked-directory").symlink_to(
            self.directory, target_is_directory=True
        )
        for patch in ("linked.patch", "linked-directory/setup.patch"):
            with self.subTest(patch=patch):
                with self.assertRaisesRegex(replay.BenchmarkError, "symlinks"):
                    self.scenario(setup_patches=[{**self.descriptor, "patch": patch}])

    def test_setup_rejects_undeclared_or_structural_edits_before_application(
        self,
    ) -> None:
        patches = {
            "undeclared file": self.patch
            + self.patch.replace(b"README.md", b"other.txt"),
            "missing declared file": self.patch,
            "duplicate file": self.patch + self.patch,
            "mode change": b"diff --git a/README.md b/README.md\nold mode 100644\nnew mode 100755\n",
            "rename": b"diff --git a/README.md b/moved.md\nsimilarity index 100%\nrename from README.md\nrename to moved.md\n",
            "addition": b"diff --git a/new.txt b/new.txt\nnew file mode 100644\n--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1 @@\n+new\n",
            "deletion": b"diff --git a/README.md b/README.md\ndeleted file mode 100644\n--- a/README.md\n+++ /dev/null\n@@ -1 +0,0 @@\n-session replay source\n",
            "symlink": b"diff --git a/link b/link\nnew file mode 120000\n--- /dev/null\n+++ b/link\n@@ -0,0 +1 @@\n+README.md\n",
            "empty content edit": b"diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n session replay source\n",
        }
        (self.source / "README.md").write_bytes(b"\0binary\0\n")
        patches["binary"] = (self.git(self.source, "diff", "--binary") + "\n").encode()
        (self.source / "README.md").write_bytes(self.before)
        worktree = ResumeTests.owned_worktree(self, self.source, self.revision)
        for reason, patch in patches.items():
            with self.subTest(reason=reason):
                paths = (
                    ["README.md", "missing.txt"]
                    if reason == "missing declared file"
                    else ["README.md"]
                )
                scenario = self.scenario(
                    setup_patches=[self.write_patch(patch, paths=paths)]
                )
                with self.assertRaises(replay.BenchmarkError):
                    self.runner().apply_setup_patches(scenario, worktree)
                self.assertEqual((worktree / "README.md").read_bytes(), self.before)
                self.assertEqual(self.git(worktree, "status", "--porcelain"), "")

    def test_setup_requires_existing_regular_source_files_and_no_symlink_parents(
        self,
    ) -> None:
        worktree = ResumeTests.owned_worktree(self, self.source, self.revision)
        scenario = self.scenario()
        runner = self.runner()
        source_file = worktree / "README.md"
        source_file.unlink()
        with self.assertRaisesRegex(replay.BenchmarkError, "existing regular file"):
            runner.apply_setup_patches(scenario, worktree)
        source_file.mkdir()
        with self.assertRaisesRegex(replay.BenchmarkError, "existing regular file"):
            runner.apply_setup_patches(scenario, worktree)
        source_file.rmdir()
        source_file.symlink_to(self.source / "README.md")
        with self.assertRaisesRegex(replay.BenchmarkError, "symlinks"):
            runner.apply_setup_patches(scenario, worktree)
        (worktree / "linked").symlink_to(self.source, target_is_directory=True)
        nested = self.write_patch(
            self.patch.replace(b"README.md", b"linked/README.md"),
            paths=["linked/README.md"],
        )
        with self.assertRaisesRegex(replay.BenchmarkError, "symlinks"):
            runner.apply_setup_patches(self.scenario(setup_patches=[nested]), worktree)
        self.assertEqual((self.source / "README.md").read_bytes(), self.before)

    def test_setup_is_identical_in_all_four_cells_and_outside_every_timed_metric(
        self,
    ) -> None:
        runner = self.runner("--repetitions", "2")
        clock = 0.0
        phases = []
        apply_patch = runner.apply_patch

        def prepare(*args: object) -> float:
            nonlocal clock
            result = apply_patch(*args)
            clock += 100.0
            return result

        def command(
            scenario: object, worktree: Path, *args: object, phase: str = "step"
        ) -> dict[str, object]:
            nonlocal clock
            self.assertEqual((worktree / "README.md").read_bytes(), self.after)
            phases.append(phase)
            duration = 50.0 if phase == "warmup" else 3.0
            clock += duration
            return {**self.command_result(), "wall_seconds": duration}

        with (
            mock.patch.object(runner, "check_disk"),
            mock.patch.object(runner, "prepare_source", return_value=self.source),
            mock.patch.object(runner, "apply_patch", side_effect=prepare),
            mock.patch.object(runner, "run_command", side_effect=command),
            mock.patch.object(replay.time, "perf_counter", side_effect=lambda: clock),
            mock.patch("builtins.print"),
        ):
            runner.run()
        self.assertEqual(phases, ["warmup", "step"] * 4)
        self.assertEqual(
            [(sample["toolchain"], sample["repetition"]) for sample in runner.samples],
            [("stock", 0), ("ohm", 0), ("ohm", 1), ("stock", 1)],
        )
        for sample in runner.samples:
            self.assertEqual(sample["wall_seconds"], 3.0)
            self.assertEqual(sample["command_seconds"], 3.0)
            self.assertEqual(sample["edit_seconds"], 0)
            self.assertEqual(sample["warmup_seconds"], 50.0)
            self.assertEqual(len(sample["steps"]), 1)
            self.assertEqual(
                sample["setup_patches"], runner.samples[0]["setup_patches"]
            )
            proof = sample["setup_patches"][0]
            self.assertEqual(proof["descriptor"], self.descriptor)
            self.assertEqual(
                proof["files"]["README.md"],
                {
                    "before": {
                        "sha256": hashlib.sha256(self.before).hexdigest(),
                        "mode": "100644",
                    },
                    "after": {
                        "sha256": hashlib.sha256(self.after).hexdigest(),
                        "mode": "100644",
                    },
                },
            )
        self.assertEqual((self.source / "README.md").read_bytes(), self.before)
        data = json.loads((runner.output / "results.json").read_text())
        self.assertEqual(data["sessions"][0]["setup_patches"], [self.descriptor])
        self.assertEqual(
            (
                data["sessions"][0]["commands"],
                data["sessions"][0]["edits"],
                data["sessions"][0]["warmups"],
            ),
            (1, 0, 1),
        )

    def test_setup_applies_even_when_warmups_are_disabled(self) -> None:
        runner = self.runner("--no-warmup")
        runner.sources["ruff"] = self.source
        with (
            mock.patch.object(
                runner,
                "run_command",
                side_effect=lambda *args, **kwargs: self.command_result(),
            ) as command,
            mock.patch("builtins.print"),
        ):
            sample = runner.run_session(runner.scenarios[0], "stock", "1.99.0", 0)
        self.assertEqual(command.call_count, 1)
        self.assertEqual(sample["warmup_steps"], [])
        self.assertEqual(
            (Path(sample["worktree"]) / "README.md").read_bytes(), self.after
        )
        with self.assertRaisesRegex(replay.BenchmarkError, "different warmups"):
            self.runner("--resume")

    def test_setup_rehashes_before_apply_and_dry_run(self) -> None:
        runner = self.runner()
        runner.sources["ruff"] = self.source
        self.patch_file.write_bytes(self.patch + b"tampered\n")
        with mock.patch.object(runner, "run_command") as command:
            with self.assertRaisesRegex(replay.BenchmarkError, "SHA-256"):
                runner.run_session(runner.scenarios[0], "stock", "1.99.0", 0)
        command.assert_not_called()
        self.assertEqual(runner.samples, [])
        worktree = runner.output / "worktrees" / "ruff" / "stock" / "0"
        self.assertEqual((worktree / "README.md").read_bytes(), self.before)

        self.patch_file.write_bytes(self.patch)
        dry_run = self.runner("--dry-run")
        self.patch_file.write_bytes(b"changed after load")
        with (
            mock.patch.object(dry_run, "check_disk"),
            mock.patch.object(dry_run, "prepare_source", return_value=self.source),
            mock.patch.object(dry_run, "run_session") as session,
        ):
            with self.assertRaisesRegex(replay.BenchmarkError, "SHA-256"):
                dry_run.run()
        session.assert_not_called()

    def test_setup_check_and_apply_use_the_same_authenticated_bytes(self) -> None:
        runner = self.runner()
        worktree = ResumeTests.owned_worktree(self, self.source, self.revision)
        run = replay.subprocess.run
        inputs = []

        def capture(arguments: list[str], **kwargs: object) -> object:
            if arguments in (["git", "apply", "--check", "-"], ["git", "apply", "-"]):
                inputs.append(kwargs["input"])
                self.patch_file.write_bytes(b"changed after verification")
            return run(arguments, **kwargs)

        with mock.patch.object(replay.subprocess, "run", side_effect=capture):
            runner.apply_setup_patches(runner.scenarios[0], worktree)
        self.assertEqual(inputs, [self.patch, self.patch])
        self.assertIs(inputs[0], inputs[1])
        self.assertEqual((worktree / "README.md").read_bytes(), self.after)

    def test_setup_context_failure_does_not_apply_or_run_commands(self) -> None:
        runner = self.runner()
        worktree = ResumeTests.owned_worktree(self, self.source, self.revision)
        (worktree / "README.md").write_bytes(b"unexpected concurrent content\n")
        with self.assertRaisesRegex(replay.BenchmarkError, "does not apply cleanly"):
            runner.apply_setup_patches(runner.scenarios[0], worktree)
        self.assertEqual(
            (worktree / "README.md").read_bytes(), b"unexpected concurrent content\n"
        )
        self.assertEqual(runner.samples, [])

    def test_resume_binds_descriptors_and_complete_matching_file_proofs(self) -> None:
        runner = self.complete_cells()
        destination = runner.output / "results.json"
        baseline = json.loads(destination.read_text())
        with mock.patch("builtins.print"):
            resumed = self.runner("--resume")
        self.assertEqual(resumed.samples, runner.samples)

        mutations = {
            "missing descriptors": lambda data: data["sessions"][0].pop(
                "setup_patches"
            ),
            "changed descriptors": lambda data: data["sessions"][0]["setup_patches"][
                0
            ].update(label="changed"),
            "missing warmup mode": lambda data: data["sessions"][0].pop(
                "warmup_enabled"
            ),
            "missing proof": lambda data: data["samples"][0].pop("setup_patches"),
            "wrong proof descriptor": lambda data: data["samples"][0]["setup_patches"][
                0
            ]["descriptor"].update(sha256="0" * 64),
            "missing file": lambda data: data["samples"][0]["setup_patches"][0][
                "files"
            ].clear(),
            "invalid digest": lambda data: data["samples"][0]["setup_patches"][0][
                "files"
            ]["README.md"]["after"].update(sha256=True),
            "wrong mode": lambda data: data["samples"][0]["setup_patches"][0]["files"][
                "README.md"
            ]["after"].update(mode="120000"),
            "changed mode": lambda data: data["samples"][0]["setup_patches"][0][
                "files"
            ]["README.md"]["after"].update(mode="100755"),
            "different cell": lambda data: data["samples"][1]["setup_patches"][0][
                "files"
            ]["README.md"]["after"].update(sha256="0" * 64),
        }
        for reason, mutate in mutations.items():
            with self.subTest(reason=reason):
                data = json.loads(json.dumps(baseline))
                mutate(data)
                destination.write_text(json.dumps(data))
                with self.assertRaises(replay.BenchmarkError):
                    self.runner("--resume")
        destination.write_text(json.dumps(baseline))
        self.scenario(setup_patches=[])
        with self.assertRaisesRegex(replay.BenchmarkError, "different setup patches"):
            self.runner("--resume")

    def test_new_cell_must_match_completed_preparation_before_warmup(self) -> None:
        runner = self.complete_cells()
        runner.options.repetitions = 2
        runner.sources["ruff"] = self.source
        runner.samples[0]["setup_patches"][0]["files"]["README.md"]["after"][
            "sha256"
        ] = "0" * 64
        with mock.patch.object(runner, "run_command") as command:
            with self.assertRaisesRegex(
                replay.BenchmarkError, "different setup patch proofs"
            ):
                runner.run_session(runner.scenarios[0], "stock", "1.99.0", 1)
        command.assert_not_called()

    def test_ordered_overlapping_setup_patches_require_a_consistent_hash_chain(
        self,
    ) -> None:
        second_patch = self.patch.replace(
            self.before.strip(), self.after.strip()
        ).replace(b"+session replay prepared", b"+session replay prepared twice")
        (self.directory / "second.patch").write_bytes(second_patch)
        second = {
            **self.descriptor,
            "label": "Second setup",
            "patch": "second.patch",
            "sha256": hashlib.sha256(second_patch).hexdigest(),
        }
        self.scenario(setup_patches=[self.descriptor, second])
        runner = self.complete_cells()
        proof = runner.samples[0]["setup_patches"]
        self.assertEqual(
            proof[0]["files"]["README.md"]["after"],
            proof[1]["files"]["README.md"]["before"],
        )
        with mock.patch("builtins.print"):
            self.runner("--resume")
        data = json.loads((runner.output / "results.json").read_text())
        data["samples"][0]["setup_patches"][1]["files"]["README.md"]["before"][
            "sha256"
        ] = "0" * 64
        (runner.output / "results.json").write_text(json.dumps(data))
        with self.assertRaisesRegex(
            replay.BenchmarkError, "inconsistent setup file proofs"
        ):
            self.runner("--resume")
        runner.persist()
        self.scenario(setup_patches=[second, self.descriptor])
        with self.assertRaisesRegex(replay.BenchmarkError, "different setup patches"):
            self.runner("--resume")

    def test_resume_archives_partial_prepared_source_then_prepares_fresh_base(
        self,
    ) -> None:
        runner = self.runner()
        runner.persist()
        worktree = ResumeTests.owned_worktree(self, self.source, self.revision)
        runner.apply_setup_patches(runner.scenarios[0], worktree)
        (worktree / "README.md").write_bytes(self.after + b"interrupted edit\n")
        resumed = self.runner("--resume")
        resumed.sources["ruff"] = self.source
        with (
            mock.patch.object(
                resumed,
                "run_command",
                side_effect=lambda *args, **kwargs: self.command_result(),
            ),
            mock.patch("builtins.print"),
        ):
            sample = resumed.run_session(resumed.scenarios[0], "stock", "1.99.0", 0)
        archived = list((runner.output / "interrupted").rglob("README.md"))
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].read_bytes(), self.after + b"interrupted edit\n")
        self.assertEqual(
            (Path(sample["worktree"]) / "README.md").read_bytes(), self.after
        )

    def test_no_setup_preserves_legacy_result_shape(self) -> None:
        self.scenario(setup_patches=[])
        runner = self.complete_cells()
        data = json.loads((runner.output / "results.json").read_text())
        self.assertNotIn("setup_patches", data["sessions"][0])
        self.assertNotIn("warmup_enabled", data["sessions"][0])
        self.assertTrue(
            all("setup_patches" not in sample for sample in data["samples"])
        )
        with mock.patch("builtins.print"):
            self.runner("--resume")


class SourceAndPatchSafetyTests(ReplayTestCase):
    def test_missing_rebased_commits_are_fetched_by_exact_validated_sha(self) -> None:
        for missing_reference in (False, True):
            with self.subTest(missing_reference=missing_reference):
                runner = self.runner()
                scenario = self.scenario(fetch_refs=["refs/pull/27736/head"])
                destination = runner.output / "sources" / "ruff"
                (destination / ".git").mkdir(parents=True, exist_ok=True)
                available: set[str] = set()

                def fetch(arguments: list[str], **_kwargs: object) -> str:
                    if arguments[-1] == "refs/pull/27736/head":
                        if missing_reference:
                            raise replay.BenchmarkError(
                                "remote reference no longer exists"
                            )
                    elif arguments[-1] == scenario.base_revision:
                        available.add(scenario.base_revision)
                    else:
                        self.fail(f"unexpected Git invocation: {arguments}")
                    return ""

                with (
                    mock.patch.object(
                        runner,
                        "commit_exists",
                        side_effect=lambda _repository, revision: revision in available,
                    ),
                    mock.patch.object(replay, "command_output", side_effect=fetch),
                ):
                    self.assertEqual(runner.prepare_source(scenario), destination)

    def test_redacts_private_source_credentials_in_arguments_and_errors(self) -> None:
        secret = "never-reveal-this-token"
        arguments = ["git", "fetch", f"https://{secret}@github.com/example/private"]
        failure = subprocess.CalledProcessError(
            128,
            arguments,
            stderr=f"fatal: access denied for https://{secret}@github.com/example/private",
        )
        with mock.patch.object(replay.subprocess, "run", side_effect=failure):
            with self.assertRaises(replay.BenchmarkError) as raised:
                replay.command_output(arguments)

        self.assertNotIn(secret, str(raised.exception))
        self.assertIn("https://<redacted>@github.com", str(raised.exception))

    def test_private_source_requires_an_explicit_authorized_checkout(self) -> None:
        runner = self.runner()
        scenario = dataclasses.replace(
            self.scenario(), repository="git@github.com:example/private-repository.git"
        )
        with mock.patch.object(replay, "command_output") as command:
            with self.assertRaisesRegex(
                replay.BenchmarkError, "requires --source-path"
            ):
                runner.prepare_source(scenario)
        command.assert_not_called()

    def test_partial_public_sources_inherit_promisor_and_private_sources_fail_closed(
        self,
    ) -> None:
        source = self.directory / "partial-source"
        source.mkdir()

        def git(repository: Path, *arguments: str) -> str:
            return subprocess.run(
                ["git", "-C", str(repository), *arguments],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            ).stdout.strip()

        git(source, "init", "--quiet")
        git(source, "config", "user.email", "session-replay-test@example.invalid")
        git(source, "config", "user.name", "Session replay test")
        git(source, "config", "commit.gpgsign", "false")
        (source / "README.md").write_text("public session replay source\n")
        git(source, "add", "README.md")
        git(source, "commit", "--quiet", "-m", "baseline")
        git(source, "remote", "add", "origin", "https://github.com/astral-sh/ruff.git")
        git(source, "config", "remote.origin.promisor", "true")
        git(source, "config", "remote.origin.partialclonefilter", "blob:none")

        scenario = self.scenario(base_revision=git(source, "rev-parse", "HEAD"))
        runner = self.runner("--source-path", f"ruff={source}")
        destination = runner.prepare_source(scenario)

        self.assertEqual(
            git(destination, "config", "--get", "remote.origin.url"),
            scenario.repository,
        )
        self.assertEqual(
            git(destination, "config", "--get", "remote.origin.promisor"), "true"
        )
        self.assertEqual(
            git(destination, "config", "--get", "remote.origin.partialclonefilter"),
            "blob:none",
        )

        git(destination, "config", "remote.origin.url", str(source))
        git(destination, "config", "--unset", "remote.origin.promisor")
        git(destination, "config", "--unset", "remote.origin.partialclonefilter")
        self.assertEqual(runner.prepare_source(scenario), destination)
        self.assertEqual(
            git(destination, "config", "--get", "remote.origin.url"),
            scenario.repository,
        )
        self.assertEqual(
            git(destination, "config", "--get", "remote.origin.promisor"), "true"
        )
        self.assertEqual(
            git(destination, "config", "--get", "remote.origin.partialclonefilter"),
            "blob:none",
        )

        private_scenario = dataclasses.replace(
            scenario, repository="git@github.com:example/private-repository.git"
        )
        with self.assertRaisesRegex(
            replay.BenchmarkError, "partial private source requires"
        ):
            runner.prepare_source(private_scenario)
        self.assertEqual(
            git(destination, "config", "--get", "remote.origin.url"),
            scenario.repository,
        )

    def test_patch_symlink_cannot_escape_fixture_directory(self) -> None:
        outside = self.directory.parent / f"{self.directory.name}-outside.patch"
        outside.write_bytes(b"secret contents")
        self.addCleanup(outside.unlink)
        patches = self.directory / "patches"
        patches.mkdir()
        (patches / "escape.patch").symlink_to(outside)
        step = {
            "kind": "edit",
            "label": "Escaping patch",
            "patch": "patches/escape.patch",
        }
        scenario = self.scenario(steps=[step])

        with self.assertRaisesRegex(replay.BenchmarkError, "escapes"):
            self.runner().patch_bytes(scenario, self.directory, step)

    def test_real_commit_diffs_apply_only_the_requested_paths(self) -> None:
        source = self.directory / "source"
        source.mkdir()

        def git(*arguments: str) -> str:
            return subprocess.run(
                ["git", "-C", str(source), *arguments],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            ).stdout.strip()

        git("init", "--quiet")
        git("config", "user.email", "session-replay-test@example.invalid")
        git("config", "user.name", "Session replay test")
        git("config", "commit.gpgsign", "false")
        first = source / "first.txt"
        second = source / "second.txt"
        first.write_text("first before\n")
        second.write_text("second before\n")
        git("add", "first.txt", "second.txt")
        git("commit", "--quiet", "-m", "baseline")
        parent = git("rev-parse", "HEAD")
        first.write_text("first after\n")
        second.write_text("second after\n")
        git("add", "first.txt", "second.txt")
        git("commit", "--quiet", "-m", "actual source edit")
        commit = git("rev-parse", "HEAD")

        worktree = self.directory / "worktree"
        git("worktree", "add", "--quiet", "--detach", str(worktree), parent)
        scenario = self.scenario(base_revision=parent)
        runner = self.runner()

        for path in ("first.txt", "second.txt"):
            step = {
                "kind": "edit",
                "label": f"Apply real {path} change",
                "parent": parent,
                "commit": commit,
                "paths": [path],
            }
            observed = runner.apply_edit(scenario, source, worktree, step)
            self.assertEqual(observed["files_changed"], 1)

        self.assertEqual((worktree / "first.txt").read_text(), "first after\n")
        self.assertEqual((worktree / "second.txt").read_text(), "second after\n")


class CommandResultTests(ReplayTestCase):
    def test_command_environment_applies_only_to_that_command(self) -> None:
        runner = self.runner()
        scenario = self.scenario()
        worktree = self.directory / "worktree"
        worktree.mkdir()
        build = {"program": "cargo", "args": ["build"]}
        clippy = {
            "program": "cargo",
            "args": ["clippy"],
            "environment": {"CARGO_BUILD_WARNINGS": "deny"},
        }
        result = subprocess.CompletedProcess([], 0, stdout="Finished\n")
        with (
            mock.patch.dict(replay.os.environ, {}, clear=True),
            mock.patch.object(replay.subprocess, "run", return_value=result) as command,
        ):
            runner.run_command(scenario, worktree, clippy, "stock", "1.99.0", 0, 1)
            self.assertEqual(
                command.call_args.kwargs["env"]["CARGO_BUILD_WARNINGS"], "deny"
            )
            runner.run_command(scenario, worktree, build, "stock", "1.99.0", 0, 2)
            self.assertNotIn("CARGO_BUILD_WARNINGS", command.call_args.kwargs["env"])

    def test_expected_red_test_rejects_wrong_status_or_missing_diagnostic(self) -> None:
        runner = self.runner()
        scenario = self.scenario()
        worktree = self.directory / "worktree"
        worktree.mkdir()
        step = {
            "program": "cargo",
            "args": ["nextest", "run"],
            "expected_exit": 100,
            "output_contains": ["unexpected error: [invalid-method-override]"],
        }
        expected = "Starting 1 test\nunexpected error: [invalid-method-override]\n"
        for status, output, accepted in (
            (100, expected, True),
            (101, expected, False),
            (0, expected, False),
            (100, "Starting 1 test\nsegmentation fault\n", False),
            (100, expected.replace("Starting 1 test", "Starting 0 tests"), False),
        ):
            with (
                self.subTest(status=status, output=output),
                mock.patch.object(
                    replay.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], status, stdout=output),
                ),
            ):
                if accepted:
                    observed = runner.run_command(
                        scenario, worktree, step, "stock", "1.99.0", 0, 1
                    )
                    self.assertEqual(observed["returncode"], 100)
                else:
                    with self.assertRaises(replay.BenchmarkError) as failure:
                        runner.run_command(
                            scenario, worktree, step, "stock", "1.99.0", 0, 1
                        )
                    if status != step["expected_exit"]:
                        self.assertEqual(
                            failure.exception.command_sample["returncode"], status
                        )
                        self.assertEqual(
                            Path(failure.exception.command_sample["log"]).read_text(),
                            output,
                        )

    def test_python_helper_uses_the_selected_target_directory(self) -> None:
        (self.directory / "helper.py").write_text(
            "import os\nprint(os.environ['CARGO_TARGET_DIR'])\n"
        )
        runner = self.runner()
        scenario = self.scenario()
        worktree = self.directory / "worktree"
        worktree.mkdir()
        step = {"program": "python", "args": ["helper.py"]}
        observed = runner.run_command(scenario, worktree, step, "stock", "1.99.0", 0, 1)
        expected = runner.environment(scenario, "stock", "1.99.0", 0)[
            "CARGO_TARGET_DIR"
        ]
        self.assertEqual(Path(observed["log"]).read_text().strip(), expected)

    def test_rejects_successful_commands_that_selected_zero_tests(self) -> None:
        runner = self.runner()
        scenario = self.scenario()
        worktree = self.directory / "worktree"
        worktree.mkdir()
        commands = (
            {"program": "cargo", "args": ["test", "missing"]},
            {"program": "cargo", "args": ["nextest", "run", "missing"]},
            {"program": "just", "args": ["test", "missing"]},
        )
        for step in commands:
            with self.subTest(program=step["program"], args=step["args"]):
                result = subprocess.CompletedProcess([], 0, stdout="running 0 tests\n")
                with mock.patch.object(replay.subprocess, "run", return_value=result):
                    with self.assertRaisesRegex(replay.BenchmarkError, "zero tests"):
                        runner.run_command(
                            scenario, worktree, step, "stock", "1.97.1", 0, 1
                        )

    def test_non_test_commands_need_not_select_tests(self) -> None:
        runner = self.runner()
        scenario = self.scenario()
        worktree = self.directory / "worktree"
        worktree.mkdir()
        step = {"program": "cargo", "args": ["check", "-p", "package"]}
        result = subprocess.CompletedProcess(
            [], 0, stdout="    Checking package v1.0\n"
        )

        with mock.patch.object(replay.subprocess, "run", return_value=result):
            sample = runner.run_command(
                scenario, worktree, step, "stock", "1.97.1", 0, 1
            )

        self.assertEqual(sample["tests_started"], 0)
        self.assertEqual(sample["cargo_reported_crates"], ["package"])
        self.assertIsNone(sample["actual_compiler_invocations"])
        self.assertIsNone(sample["cargo_status_without_compiler_invocation"])

    def test_verbose_accounting_distinguishes_status_only_early_cutoff(self) -> None:
        runner = self.runner("--compiler-accounting", "verbose")
        scenario = self.scenario()
        worktree = self.directory / "worktree"
        worktree.mkdir()
        step = {"program": "cargo", "args": ["check", "-p", "package"]}
        result = subprocess.CompletedProcess(
            [],
            0,
            stdout="\n".join(
                (
                    "    Checking skipped-dependency v1.0.0",
                    "    Checking actual-dependency v1.0.0",
                    "     Running `/toolchain/bin/rustc --crate-name actual_dependency --emit=metadata`",
                    "   Compiling linted-dependency v1.0.0",
                    "     Running `/toolchain/bin/clippy-driver /toolchain/bin/rustc --crate-name=linted_dependency`",
                    "     Running `/target/debug/build/dependency/build-script-build`",
                )
            ),
        )

        with mock.patch.object(
            replay.subprocess, "run", return_value=result
        ) as command:
            sample = runner.run_command(scenario, worktree, step, "ohm", "ohm", 0, 1)

        self.assertEqual(command.call_args.kwargs["env"]["CARGO_TERM_VERBOSE"], "true")
        self.assertEqual(
            sample["cargo_reported_crates"],
            ["skipped-dependency", "actual-dependency", "linted-dependency"],
        )
        self.assertEqual(
            sample["actual_compiler_invocations"],
            [
                {"compiler": "rustc", "crate": "actual_dependency"},
                {"compiler": "clippy-driver", "crate": "linted_dependency"},
            ],
        )
        self.assertEqual(
            sample["cargo_status_without_compiler_invocation"],
            ["skipped-dependency"],
        )

    def test_compiler_accounting_distinguishes_repeated_package_statuses(self) -> None:
        invocations = replay.compiler_invocations(
            "     Running `/toolchain/bin/rustc.exe --crate-name shared_package`\n"
        )
        self.assertEqual(
            replay.status_only_crates(
                ["shared-package", "shared-package"], invocations
            ),
            ["shared-package"],
        )

    def test_malformed_verbose_commands_fail_accounting_closed(self) -> None:
        with self.assertRaisesRegex(replay.BenchmarkError, "verbose Cargo command"):
            replay.compiler_invocations("     Running `rustc 'unterminated`\n")

    def test_warmup_logs_are_separate_from_timed_logs(self) -> None:
        runner = self.runner()
        scenario = self.scenario()
        worktree = self.directory / "worktree"
        worktree.mkdir()
        step = {"program": "cargo", "args": ["check", "-p", "package"]}
        result = subprocess.CompletedProcess([], 0, stdout="Checking package\n")

        with mock.patch.object(replay.subprocess, "run", return_value=result):
            warmup = runner.run_command(
                scenario, worktree, step, "stock", "1.97.1", 0, 1, phase="warmup"
            )
            timed = runner.run_command(
                scenario, worktree, step, "stock", "1.97.1", 0, 1
            )

        self.assertEqual(Path(warmup["log"]).name, "warmup-01.log")
        self.assertEqual(Path(timed["log"]).name, "01.log")


class BackgroundExecutionTests(ReplayTestCase):
    def test_background_execution_rejects_hosts_without_fork(self) -> None:
        runner = self.runner("--background")
        self.assertTrue(runner.options.background)

        with mock.patch.object(replay, "os", new=mock.Mock(spec=[])):
            with self.assertRaisesRegex(replay.BenchmarkError, "Unix-like host"):
                replay.run_in_background(runner)

    def test_background_dry_run_persists_success_status_and_output(self) -> None:
        source = self.directory / "source"
        source.mkdir()

        def git(*arguments: str) -> str:
            return subprocess.run(
                ["git", "-C", str(source), *arguments],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            ).stdout.strip()

        git("init", "--quiet")
        git("config", "user.email", "session-replay-test@example.invalid")
        git("config", "user.name", "Session replay test")
        git("config", "commit.gpgsign", "false")
        (source / "README.md").write_text("background replay source\n")
        git("add", "README.md")
        git("commit", "--quiet", "-m", "baseline")
        self.scenario(base_revision=git("rev-parse", "HEAD"))

        output = self.directory / "background-output"
        process = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--project",
                "ruff",
                "--scenario",
                str(self.fixture),
                "--source-path",
                f"ruff={source}",
                "--output-dir",
                str(output),
                "--minimum-free-gb",
                "0",
                "--dry-run",
                "--background",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            timeout=10,
        )
        self.assertIn("Background replay process:", process.stdout)

        status_path = output / "status.json"
        deadline = time.monotonic() + 5
        status: dict[str, object] | None = None
        log = ""
        while time.monotonic() < deadline:
            if status_path.exists():
                status = json.loads(status_path.read_text())
                if status["state"] == "failed":
                    break
                if status["state"] == "succeeded":
                    # The child can publish status before stdout finishes flushing.
                    log = (output / "run.log").read_text()
                    if "ruff: real-session" in log:
                        break
            time.sleep(0.02)

        self.assertIsNotNone(status, "background replay never wrote its status")
        self.assertEqual(status["state"], "succeeded")
        self.assertIn("ruff: real-session", log)
        self.assertTrue((output / "results.json").is_file())


if __name__ == "__main__":
    unittest.main()
