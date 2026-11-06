"""Check workflow state boundaries, source edits, and interference accounting."""

import dataclasses
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import benchmark_workflows as workflows


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.git("init", "-q")
        (self.source / "lib.rs").write_text("before\n")
        self.git("add", "lib.rs")
        self.git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "baseline",
        )
        self.study = workflows.WorkflowStudy(
            workflows.parser().parse_args(
                [
                    "--project",
                    "uv",
                    "--ohm",
                    "test-ohm",
                    "--output-dir",
                    str(self.root / "results"),
                    "--minimum-free-gb",
                    "0",
                ]
            )
        )
        self.scenario = dataclasses.replace(
            self.study.scenarios[0], base_revision=self.git("rev-parse", "HEAD")
        )
        self.study.scenarios = [self.scenario]
        self.study.sources["uv"] = self.source
        self.study.definitions["uv"]["edits"]["direct"] = {
            "path": "lib.rs",
            "before": "before",
            "after": "after",
            "crate": "uv",
        }
        self.observed = []
        self.study.run_command = self.fake_command

    def git(self, *arguments):
        return subprocess.check_output(
            ["git", *arguments], cwd=self.source, text=True
        ).strip()

    def fake_command(
        self, scenario, worktree, step, label, selector, cell, index, *, phase="session"
    ):
        target = Path(
            self.study.environment(scenario, label, selector, cell)["CARGO_TARGET_DIR"]
        )
        target.mkdir(parents=True, exist_ok=True)
        self.observed.append(
            (
                phase,
                step["label"],
                (worktree / "lib.rs").read_text(),
                target,
                (target / "built").exists(),
            )
        )
        if step["label"] == "build":
            (target / "built").touch()
        log = (
            self.study.output
            / "logs"
            / scenario.project
            / label
            / cell
            / f"{phase}-{index}.log"
        )
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("ok\n")
        started = time.perf_counter()
        time.sleep(0.001)
        return {
            "wall_seconds": time.perf_counter() - started,
            "returncode": 0,
            "external_compilation": [],
            "tests_started": int(step["label"] == "test"),
            "log": str(log),
        }

    def test_edit_sequence_keeps_one_target_and_excludes_warmup(self):
        def after_warmup():
            self.assertEqual(
                [row[1] for row in self.observed], ["fmt", "check", "test", "check"]
            )
            return []

        self.study.preflight = after_warmup
        elapsed = 0

        def command(*args, phase="session", **kwargs):
            nonlocal elapsed
            result = self.fake_command(*args, phase=phase, **kwargs)
            seconds = 100 if phase == "warmup" else 1
            elapsed += seconds
            return result | {"wall_seconds": seconds}

        self.study.run_command = command
        with mock.patch.object(workflows.time, "perf_counter", lambda: elapsed):
            sample = self.study.run_case(
                self.scenario, "edit-check-test-check", "stock", "1.99.0", 0, 0
            )
        timed = [row for row in self.observed if row[0] == "session"]
        self.assertEqual([row[1] for row in timed], ["check", "test", "check"])
        self.assertTrue(
            all(row[2] == "before\n" for row in self.observed if row[0] == "warmup")
        )
        self.assertTrue(all(row[2] == "after\n" for row in timed))
        self.assertEqual(len({row[3] for row in self.observed}), 1)
        self.assertEqual(len(sample["commands"]), 3)
        self.assertEqual(sample["wall_seconds"], 3)
        self.assertEqual(sample["command_seconds"], 3)
        self.assertEqual((self.source / "lib.rs").read_text(), "before\n")

    def test_build_transition_starts_without_build_artifacts_each_repetition(self):
        for repetition in range(2):
            self.observed.clear()
            self.study.run_case(
                self.scenario, "check-build-check", "stock", "1.99.0", repetition, 0
            )
            timed = [row for row in self.observed if row[0] == "session"]
            self.assertEqual([row[1] for row in timed], ["check", "build", "check"])
            self.assertEqual([row[4] for row in timed], [False, False, True])
        self.assertNotEqual(
            self.study.samples[0]["target_directory"],
            self.study.samples[1]["target_directory"],
        )

    def test_formatting_rewrites_the_edit_before_lint_and_test(self):
        mutate_after_format = False

        def command(*args, phase="session", **kwargs):
            sample = self.fake_command(*args, phase=phase, **kwargs)
            if phase == "session":
                path = args[1] / "lib.rs"
                if args[2]["label"] == "fmt":
                    path.write_text("formatted\n")
                elif mutate_after_format and args[2]["label"] == "clippy":
                    path.write_text("unexpected\n")
            return sample

        self.study.run_command = command
        self.study.run_case(
            self.scenario, "edit-fmt-clippy-test", "stock", "1.99.0", 0, 0
        )
        timed = [row for row in self.observed if row[0] == "session"]
        self.assertEqual(
            [(row[1], row[2]) for row in timed],
            [("fmt", "after\n"), ("clippy", "formatted\n"), ("test", "formatted\n")],
        )
        mutate_after_format = True
        with self.assertRaisesRegex(workflows.BenchmarkError, "edited source"):
            self.study.run_case(
                self.scenario, "edit-fmt-clippy-test", "stock", "1.99.0", 0, 1
            )

    def test_resume_rejects_changed_commands(self):
        self.study.persist()
        saved = self.study.configuration()
        result = json.loads((self.study.output / "results.json").read_text())
        result["configuration"]["jobs"] += 1
        (self.study.output / "results.json").write_text(json.dumps(result))
        with self.assertRaisesRegex(workflows.BenchmarkError, "different sources"):
            self.study.restore_results()
        self.assertEqual(saved, self.study.configuration())

    def test_failed_commands_are_retained_and_not_retried_as_successes(self):
        self.study.workflows = ["edit-test", "check-build-check"]
        self.study.toolchains = [("stock", "1.99.0")]
        self.study.options.repetitions = 1
        metadata = {
            "host": "unit-test",
            "platform": "unit-test",
            "logical_cpus": 1,
            "cpu_model": "unit-test",
            "toolchains": {},
            "helpers": {},
            "started_at": 1,
        }
        self.study.collect_metadata = lambda: setattr(
            self.study, "metadata", metadata.copy()
        )
        self.study.prepare_source = lambda scenario: self.source
        self.study.run_command = workflows.WorkflowStudy.run_command.__get__(self.study)

        def command(*args, **kwargs):
            sample = self.fake_command(*args, **kwargs)
            if args[2]["label"] == "test" and kwargs.get("phase") != "warmup":
                Path(sample["log"]).write_text("compiler failed\n")
                error = workflows.BenchmarkError("compiler failed")
                error.command_sample = sample | {"returncode": 101}
                raise error
            return sample

        with mock.patch.object(
            workflows.replay.Replay, "run_command", side_effect=command
        ):
            self.study.run()
            self.assertEqual(len(self.study.failures), 1)
            self.assertEqual(len(self.study.samples), 1)
            self.assertEqual(
                self.study.failures[0]["failed_command"]["returncode"], 101
            )
            saved = json.loads((self.study.output / "results.json").read_text())
            self.assertEqual(len(saved["failures"]), 1)
            self.assertIn("finished_at", saved["metadata"])
            self.observed.clear()
            self.study.options.resume = True
            self.study.run()
            self.assertEqual(self.observed, [])

    def test_cpu_monitor_excludes_own_compilers_and_counts_other_work(self):
        owner = os.getpid()
        processes = {
            owner: {"parent": 1, "ticks": 10, "start": 1, "name": "python"},
            101: {"parent": owner, "ticks": 10, "start": 1, "name": "cargo"},
            102: {"parent": 101, "ticks": 10, "start": 1, "name": "rustc"},
            103: {"parent": 1, "ticks": 10, "start": 1, "name": "unrelated"},
        }
        newer = {pid: value | {"ticks": 30} for pid, value in processes.items()}
        sample = workflows.cpu_interval(
            ([0] * 8, processes), ([60, 0, 20, 20, 0, 0, 0, 0], newer), owner
        )
        self.assertEqual(sample["external_percent"], 20)
        self.assertEqual([row["pid"] for row in sample["external_processes"]], [103])

    def test_cpu_monitor_counts_exited_work_without_counting_reaped_children_twice(
        self,
    ):
        owner = os.getpid()
        parent = {
            "parent": 1,
            "ticks": 100,
            "children_ticks": 0,
            "start": 1,
            "name": "python",
        }
        child = {"parent": owner, "ticks": 40, "start": 2, "name": "cargo"}
        sample = workflows.cpu_interval(
            ([0] * 8, {owner: parent, 101: child}),
            (
                [60, 0, 0, 40, 0, 0, 0, 0],
                {owner: parent | {"ticks": 110, "children_ticks": 80}},
            ),
            owner,
        )
        self.assertEqual(sample["owned_percent"], 50)
        self.assertEqual(sample["external_percent"], 10)
        self.assertEqual(sample["external_processes"], [])

    def test_cpu_monitor_records_workflows_shorter_than_its_interval(self):
        path = self.root / "cpu.jsonl"
        with mock.patch.object(
            workflows,
            "cpu_snapshot",
            side_effect=[([0] * 8, {}), ([0, 0, 0, 100, 0, 0, 0, 0], {})],
        ):
            with workflows.HostMonitor(path, True) as monitor:
                pass
        self.assertIsNone(monitor.failure)
        self.assertEqual(len(monitor.samples), 1)
        self.assertEqual(json.loads(path.read_text())["idle_percent"], 100)


if __name__ == "__main__":
    unittest.main()
