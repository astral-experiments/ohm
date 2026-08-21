"""Fast, build-free correctness and security tests for real-session replays."""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import os
import statistics
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
    def test_all_bundled_real_sessions_are_valid(self) -> None:
        for project in replay.PROJECTS:
            with self.subTest(project=project):
                scenario = replay.load_scenario(
                    SCRIPTS / "session_replays" / f"{project}.json"
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
            SCRIPTS / "session_replays" / "ruff-historical.json"
        )
        current = replay.load_scenario(SCRIPTS / "session_replays" / "ruff.json")
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

    def test_rust_1_98_ruff_fixtures_only_allow_the_new_clippy_lint(self) -> None:
        for original_name, compatible_name in (
            ("ruff.json", "ruff-rust-1.98.json"),
            ("ruff-historical.json", "ruff-historical-rust-1.98.json"),
        ):
            with self.subTest(fixture=original_name):
                original_path = SCRIPTS / "session_replays" / original_name
                compatible_path = SCRIPTS / "session_replays" / compatible_name
                expected = json.loads(original_path.read_text())
                for step in expected["steps"]:
                    if (
                        step["kind"] == "command"
                        and step["program"] == "cargo"
                        and step["args"][0] == "clippy"
                    ):
                        step["args"].extend(["-A", "clippy::format_push_string"])

                self.assertEqual(json.loads(compatible_path.read_text()), expected)
                self.assertEqual(replay.load_scenario(compatible_path).project, "ruff")

    def test_historical_ruff_results_match_the_rust_1_98_fixture(self) -> None:
        fixture = SCRIPTS / "session_replays" / "ruff-historical-rust-1.98.json"
        published_fixture = SCRIPTS / "session_replays" / "ruff-historical.json"
        scenario = replay.load_scenario(fixture)
        baseline = json.loads(
            (
                SCRIPTS / "session_replays" / "release-1.98.0-1-ruff-historical.json"
            ).read_text()
        )

        self.assertEqual(baseline["rust_version"], "1.98.0")
        self.assertEqual(baseline["ohm_release"], "ohm-1.98.0-1")
        self.assertEqual(baseline["order"], [["stock", "ohm"], ["ohm", "stock"]])
        self.assertTrue(baseline["methodology"]["matching_test_counts_within_pairs"])
        self.assertEqual(
            baseline["provenance"]["published_fixture_sha256"],
            hashlib.sha256(published_fixture.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            baseline["provenance"]["effective_fixture_sha256"]["ruff"],
            hashlib.sha256(fixture.read_bytes()).hexdigest(),
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

    def test_current_ruff_results_match_the_fixture_and_tables(self) -> None:
        fixture = SCRIPTS / "session_replays" / "ruff-rust-1.98.json"
        published_fixture = SCRIPTS / "session_replays" / "ruff.json"
        scenario = replay.load_scenario(fixture)
        baseline = json.loads(
            (SCRIPTS / "session_replays" / "release-1.98.0-1-ruff.json").read_text()
        )
        self.assertEqual(baseline["ohm_release"], "ohm-1.98.0-1")
        self.assertEqual(baseline["order"], [["stock", "ohm"], ["ohm", "stock"]])
        self.assertEqual(baseline["environment"], scenario.environment)
        self.assertEqual(
            baseline["provenance"]["published_fixture_sha256"],
            hashlib.sha256(published_fixture.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            baseline["provenance"]["effective_fixture_sha256"]["ruff"],
            hashlib.sha256(fixture.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            baseline["methodology"]["ruff_rust_1_98_clippy_allow"],
            ["clippy::format_push_string"],
        )
        self.assertEqual(baseline["sessions"][0]["session_id"], scenario.session["id"])
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
                len(baseline["timed_session_seconds"]["ruff"][toolchain]), 2
            )
            for repetition in range(2):
                self.assertAlmostEqual(
                    sum(
                        command["wall_seconds"][toolchain][repetition]
                        for command in commands
                    ),
                    baseline["timed_command_seconds"]["ruff"][toolchain][repetition],
                )

        def rows(document: Path) -> list[list[str]]:
            return [
                [cell.strip() for cell in line.strip("|").split("|")]
                for line in document.read_text().splitlines()
                if line.startswith("|")
            ]

        main_rows = rows(SCRIPTS.parent / "README.md")
        detailed_rows = rows(SCRIPTS / "session_replays" / "README.md")

        def assert_row(
            table: list[list[str]], label: str, stock: float, ohm: float
        ) -> None:
            saved = stock - ohm
            sign = "−" if saved < 0 else ""
            self.assertIn(
                [
                    label,
                    f"{stock:,.2f} s",
                    f"{ohm:,.2f} s",
                    f"{sign}{abs(saved):,.2f} s",
                    f"{sign}{abs(100 * saved / stock):.2f}%",
                ],
                table,
            )

        session = baseline["timed_session_seconds"]["ruff"]
        stock = statistics.fmean(session["stock"])
        ohm = statistics.fmean(session["ohm"])
        assert_row(main_rows, "Ruff session", stock, ohm)
        assert_row(detailed_rows, "Complete session", stock, ohm)
        timed = baseline["timed_command_seconds"]["ruff"]
        assert_row(
            detailed_rows,
            "All recorded commands",
            statistics.fmean(timed["stock"]),
            statistics.fmean(timed["ohm"]),
        )

        def command_seconds(toolchain: str, indices: set[int]) -> float:
            return sum(
                statistics.fmean(command["wall_seconds"][toolchain])
                for command in commands
                if command["index"] in indices
            )

        for label, indices in (
            (
                "Checks and tests (`nextest`)",
                {
                    command["index"]
                    for command in commands
                    if command["category"] == "test"
                },
            ),
            (
                "`cargo clippy`",
                {
                    command["index"]
                    for command in commands
                    if command["category"] == "clippy"
                },
            ),
            (
                "`cargo fmt`",
                {
                    command["index"]
                    for command in commands
                    if command["category"] == "formatting"
                },
            ),
            ("Unchanged focused baseline", {1}),
            ("Simplification", {3, 4}),
            ("Dependency indexing", {7, 8}),
            ("Component fixed points", {11, 12, 13}),
        ):
            assert_row(
                detailed_rows,
                label,
                command_seconds("stock", indices),
                command_seconds("ohm", indices),
            )

    def test_checked_in_release_baseline_contains_paired_real_sessions(self) -> None:
        baseline = json.loads(
            (
                SCRIPTS / "session_replays" / "release-1.97.1-17-baseline.json"
            ).read_text()
        )
        self.assertEqual(baseline["rust_version"], "1.97.1")
        self.assertEqual(baseline["ohm_release"], "ohm-1.97.1-17")
        self.assertEqual(baseline["order"], [["stock", "ohm"], ["ohm", "stock"]])
        self.assertEqual(baseline["jobs"], replay.parser().get_default("jobs"))
        self.assertIn(
            f"--jobs {baseline['jobs']} \\",
            (SCRIPTS / "session_replays" / "README.md").read_text(),
        )
        for project in replay.PROJECTS:
            samples = baseline["timed_session_seconds"][project]
            self.assertEqual(len(samples["stock"]), baseline["repetitions"])
            self.assertEqual(len(samples["ohm"]), baseline["repetitions"])
            self.assertTrue(all(seconds > 0 for seconds in samples["stock"]))
            self.assertTrue(all(seconds > 0 for seconds in samples["ohm"]))
        self.assertIsNone(baseline["untimed_warmup_seconds"]["uv"]["stock"][0])
        self.assertFalse(
            baseline["methodology"]["cargo_status_messages_prove_compiler_invocations"]
        )

    def test_historical_ruff_fixture_matches_release_baseline_warmups(self) -> None:
        baseline = json.loads(
            (
                SCRIPTS / "session_replays" / "release-1.97.1-17-baseline.json"
            ).read_text()
        )
        scenario = replay.load_scenario(
            SCRIPTS / "session_replays" / "ruff-historical.json"
        )

        self.assertEqual(len(scenario.warmup), 2)
        self.assertEqual(
            [step["args"][0] for step in scenario.warmup], ["check", "nextest"]
        )
        self.assertFalse(baseline["methodology"]["ruff_warmup_included_formatting"])
        self.assertFalse(any(step["args"][0] == "fmt" for step in scenario.warmup))

    def test_revision_18_results_preserve_every_recorded_command(self) -> None:
        baseline = json.loads(
            (
                SCRIPTS / "session_replays" / "release-1.97.1-18-baseline.json"
            ).read_text()
        )
        self.assertEqual(baseline["ohm_release"], "ohm-1.97.1-18")
        self.assertEqual(baseline["order"], [["stock", "ohm"], ["ohm", "stock"]])
        self.assertTrue(baseline["methodology"]["all_commands_succeeded"])
        self.assertEqual(baseline["methodology"]["external_compilations_observed"], 0)
        self.assertFalse(
            baseline["methodology"]["cargo_status_messages_prove_compiler_invocations"]
        )

        for project in replay.PROJECTS:
            with self.subTest(project=project):
                fixture = "ruff-historical" if project == "ruff" else project
                scenario = replay.load_scenario(
                    SCRIPTS / "session_replays" / f"{fixture}.json"
                )
                commands = baseline["commands"][project]
                expected = [
                    (index, step)
                    for index, step in enumerate(scenario.steps, start=1)
                    if step["kind"] == "command"
                ]
                self.assertEqual(len(commands), len(expected))
                for command, (index, step) in zip(commands, expected, strict=True):
                    self.assertEqual(command["index"], index)
                    self.assertEqual(command["label"], step["label"])
                    original = [step["program"], *step["args"]]
                    if project == "codex" and index == len(scenario.steps):
                        self.assertEqual(command["command"][: len(original)], original)
                        self.assertEqual(command["command"][len(original)], "-E")
                        self.assertEqual(len(command["command"]), len(original) + 2)
                    else:
                        self.assertEqual(command["command"], original)
                    category = {
                        "check": "check",
                        "test": "test",
                        "nextest": "test",
                        "clippy": "clippy",
                        "fmt": "formatting",
                    }[original[1]]
                    self.assertEqual(command["category"], category)

                for toolchain in ("stock", "ohm"):
                    for repetition in range(baseline["repetitions"]):
                        total = sum(
                            command["wall_seconds"][toolchain][repetition]
                            for command in commands
                        )
                        self.assertAlmostEqual(
                            total,
                            baseline["timed_command_seconds"][project][toolchain][
                                repetition
                            ],
                        )
                        self.assertGreaterEqual(
                            baseline["timed_session_seconds"][project][toolchain][
                                repetition
                            ],
                            total
                            + baseline["timed_edit_seconds"][project][toolchain][
                                repetition
                            ],
                        )

    def test_readme_selected_session_table_matches_recorded_results(self) -> None:
        baseline = json.loads(
            (SCRIPTS / "session_replays" / "release-1.98.0-1-baseline.json").read_text()
        )
        baselines = {project: baseline for project in replay.PROJECTS}
        rows = [
            [cell.strip() for cell in line.strip("|").split("|")]
            for line in (SCRIPTS.parent / "README.md").read_text().splitlines()
            if line.startswith("|")
        ]
        self.assertEqual(sum(row[0] == "Ruff session" for row in rows), 1)

        def assert_row(label: str, stock: float, ohm: float) -> None:
            saved = stock - ohm
            sign = "−" if saved < 0 else ""
            self.assertIn(
                [
                    label,
                    f"{stock:,.2f} s",
                    f"{ohm:,.2f} s",
                    f"{sign}{abs(saved):,.2f} s",
                    f"{sign}{abs(100 * saved / stock):.2f}%",
                ],
                rows,
            )

        def command_seconds(
            project: str, toolchain: str, categories: set[str]
        ) -> float:
            return sum(
                statistics.fmean(command["wall_seconds"][toolchain])
                for command in baselines[project]["commands"][project]
                if command["category"] in categories
            )

        for project, label in (
            ("ruff", "Ruff session"),
            ("uv", "uv session"),
            ("codex", "Codex session"),
        ):
            assert_row(
                label,
                statistics.fmean(
                    baselines[project]["timed_session_seconds"][project]["stock"]
                ),
                statistics.fmean(
                    baselines[project]["timed_session_seconds"][project]["ohm"]
                ),
            )

        for category, label in (
            ("check", "`cargo check`"),
            ("test", "`cargo test`, `cargo nextest`, `just test`"),
            ("clippy", "`cargo clippy`"),
            ("formatting", "`cargo fmt`"),
        ):
            assert_row(
                label,
                sum(command_seconds(p, "stock", {category}) for p in replay.PROJECTS),
                sum(command_seconds(p, "ohm", {category}) for p in replay.PROJECTS),
            )

        for field, label in (
            ("timed_session_seconds", "All sessions"),
            ("timed_command_seconds", "All commands"),
        ):
            assert_row(
                label,
                sum(
                    statistics.fmean(baselines[p][field][p]["stock"])
                    for p in replay.PROJECTS
                ),
                sum(
                    statistics.fmean(baselines[p][field][p]["ohm"])
                    for p in replay.PROJECTS
                ),
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
            "selector": "1.98.0" if label == "stock" else "ohm",
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
                observed = resumed.run_session(scenario, "stock", "1.98.0", 0)

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
                resumed.run_session(scenario, "stock", "1.98.0", 0)

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
            resumed.run_session(scenario, "stock", "1.98.0", 0)

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
                resumed.run_session(scenario, "stock", "1.98.0", 0)

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
            resumed.run_session(scenario, "stock", "1.98.0", 0)

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
            resumed.run_session(scenario, "stock", "1.98.0", 0)
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
            runner.run_session(scenario, "stock", "1.98.0", 0)
        self.assertEqual(self.git(worktree, "rev-parse", "HEAD"), revision)


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
        while time.monotonic() < deadline:
            if status_path.exists():
                status = json.loads(status_path.read_text())
                if status["state"] in ("succeeded", "failed"):
                    break
            time.sleep(0.02)

        self.assertIsNotNone(status, "background replay never wrote its status")
        self.assertEqual(status["state"], "succeeded")
        self.assertIn("ruff: real-session", (output / "run.log").read_text())
        self.assertTrue((output / "results.json").is_file())


if __name__ == "__main__":
    unittest.main()
