"""Check report arithmetic, compaction, and publication."""

import copy
from pathlib import Path
import re
import shutil
import statistics
import tempfile
import unittest
from unittest import mock

import publish_benchmarks as publish


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.reports = publish.latest_reports()
        self.ty_worktree = publish.load(publish.RESULTS / publish.TY_WORKTREE_REPORT)
        self.ty_scenario = publish.load(publish.ROOT / publish.TY_SCENARIO)

    def copy_supplemental_reports(self, root):
        destination = root / "scripts/benchmark_results" / publish.TY_WORKTREE_REPORT
        destination.parent.mkdir(parents=True, exist_ok=True)
        publish.write_json(destination, self.ty_worktree)
        fixture = root / publish.TY_SCENARIO
        fixture.parent.mkdir(parents=True, exist_ok=True)
        publish.write_json(fixture, self.ty_scenario)
        shutil.copyfile(
            publish.RESULTS / publish.DEVELOPER_WORKFLOW_REPORT,
            root / "scripts/benchmark_results" / publish.DEVELOPER_WORKFLOW_REPORT,
        )

    def partial_disk(self, *, forks=True):
        disk = copy.deepcopy(self.reports["disk"])
        release, rust = (
            self.reports["sessions"]["ohm_release"],
            self.reports["sessions"]["rust_version"],
        )
        disk["release"] = release
        if "stock-" + rust in disk["toolchains"]:
            disk["toolchains"][rust] = disk["toolchains"].pop("stock-" + rust)
        disk["validation"].update(status="partial", full_campaign_passed=False)
        disk["campaign"] = {
            "fork_continuation": {
                "release": release,
                "state": "finished_with_failed_original_cohort",
                "finished_at": 2,
            }
        }
        disk["cohort_inventory"] = [
            dict(
                row,
                accepted=row["cell"].startswith("ruff-")
                and (forks or row["cell"].endswith("-single")),
                retained_bytes=row.get("idle_bytes", row.get("retained_bytes")),
            )
            for row in disk.get("cohort_inventory", disk["cohorts"])
        ]
        for row in disk["cohort_inventory"]:
            row["state"] = "audited_complete" if row["accepted"] else "failed"
        disk["cohorts"] = [r for r in disk["cohort_inventory"] if r["accepted"]]
        accepted = {r["cell"] for r in disk["cohorts"]}
        disk["readme_comparisons"] = [
            r
            for r in disk["readme_comparisons"]
            if r["project"] == "ruff" and (forks or r["comparison"]["worktrees"] == 1)
        ]
        disk["omitted_comparisons"] = []
        for project in ("ruff", "uv"):
            for mode in ("single", "forks"):
                missing = {
                    f"{project}-{label}-{mode}" for label in ("stock", "ohm")
                } - accepted
                if missing:
                    disk["omitted_comparisons"].append(
                        {
                            "project": project,
                            "cohort": mode,
                            "missing_audited_cohorts": sorted(missing),
                            "ratio": None,
                        }
                    )
        return disk

    def test_partial_disk_compaction_and_pair_eligibility(self):
        reports = copy.deepcopy(self.reports)
        reports["disk"] = publish.compact(self.partial_disk())
        publish.validate(reports)
        missing = copy.deepcopy(reports["disk"]["readme_comparisons"][0])
        missing["project"] = missing["comparison"]["project"] = "uv"
        reports["disk"]["readme_comparisons"].append(missing)
        with self.assertRaises(ValueError):
            publish.validate(reports)

    def test_partial_disk_requires_terminal_identity_and_correct_arithmetic(self):
        for change in (
            lambda d: d["cohort_inventory"][0].update(state="running"),
            lambda d: d["campaign"]["fork_continuation"].pop("finished_at"),
            lambda d: d["readme_comparisons"][0]["comparison"].update(bytes_saved=1),
        ):
            with self.subTest(change=change):
                reports = copy.deepcopy(self.reports)
                reports["disk"] = self.partial_disk()
                change(reports["disk"])
                with self.assertRaises(ValueError):
                    publish.validate(reports)

    def test_partial_disk_without_ten_worktree_pair_has_no_numeric_headline(self):
        reports = copy.deepcopy(self.reports)
        reports["disk"] = self.partial_disk(forks=False)
        _, headlines = publish.render_tables(
            reports, self.ty_worktree, self.ty_scenario
        )
        headline = headlines[publish.DISK_HEADLINE]
        self.assertEqual(headline, "disk usage comparisons are incomplete")
        first = re.sub(
            publish.DISK_HEADLINE, headline, "disk usage decreases by around 55%"
        )
        self.assertEqual(re.sub(publish.DISK_HEADLINE, headline, first), first)

    def test_tables_match_current_reports(self):
        for name, expected in publish.documents(self.reports).items():
            self.assertEqual(
                publish.normalized_markdown(expected),
                publish.normalized_markdown((publish.ROOT / name).read_text()),
            )

    def test_ty_is_included_in_session_and_command_totals(self):
        tables, _ = publish.render_tables(
            self.reports, self.ty_worktree, self.ty_scenario
        )
        self.assertIn(
            "| ty | Worktree startup (Btrfs) | `ty_python_semantic` |",
            tables["features"],
        )
        rows = {
            cells[0]: cells[1:3]
            for line in tables["sessions"].splitlines()[2:]
            if (cells := [cell.strip() for cell in line.strip("|").split("|")])
        }
        projects = self.reports["sessions"]["commands"]
        excluded = self.reports["sessions"].get("excluded_projects", {})
        session_total = "Completed sessions" if excluded else "All sessions"
        command_total = "Commands in completed sessions" if excluded else "All commands"
        for project in excluded:
            self.assertEqual(rows[f"{publish.SESSION_LABELS[project]} (incomplete)"], ["—", "—"])
        labels = [publish.SESSION_LABELS[project] for project in projects] + ["ty session"]
        for index, lane in enumerate(("stock", "ohm")):
            self.assertAlmostEqual(
                float(rows["ty session"][index].removesuffix(" s")),
                statistics.fmean(self.ty_worktree["session"][lane]["total"]["samples"]),
                delta=0.01,
            )
            session_sum = sum(
                float(rows[label][index].removesuffix(" s").replace(",", ""))
                for label in labels
            )
            shown_total = float(
                rows[session_total][index].removesuffix(" s").replace(",", "")
            )
            self.assertAlmostEqual(session_sum, shown_total, delta=0.02)
            command_sum = sum(
                float(rows[label][index].removesuffix(" s").replace(",", ""))
                for label in (
                    "`cargo check`",
                    "`cargo test`, `cargo nextest`, `just test`",
                    "`cargo clippy`",
                    "`cargo fmt`",
                    "Other commands",
                )
            )
            all_commands = float(
                rows[command_total][index].removesuffix(" s").replace(",", "")
            )
            self.assertAlmostEqual(command_sum, all_commands, delta=0.03)
            expected_ty = statistics.fmean(
                self.ty_worktree["session"][lane]["commands"]["samples"]
            )
            old_commands = sum(
                statistics.fmean(
                    self.reports["sessions"]["timed_command_seconds"][p][lane]
                )
                for p in projects
            )
            self.assertAlmostEqual(all_commands, old_commands + expected_ty, delta=0.01)
            for category, label, indices in (
                ("test", "`cargo test`, `cargo nextest`, `just test`", (2, 3, 4, 5)),
                ("clippy", "`cargo clippy`", (8,)),
            ):
                old = sum(
                    statistics.fmean(command["wall_seconds"][lane])
                    for project in projects
                    for command in self.reports["sessions"]["commands"][project]
                    if command["category"] == category
                )
                ty = sum(
                    statistics.fmean(
                        self.ty_worktree["session_steps"][i][lane]["seconds"]["samples"]
                    )
                    for i in indices
                )
                observed = float(rows[label][index].removesuffix(" s").replace(",", ""))
                self.assertAlmostEqual(observed, old + ty, delta=0.01)

    def test_session_exclusions_require_a_complete_pair(self):
        sessions = self.reports["sessions"]
        project = next(iter(sessions["commands"]))
        excluded = sessions.setdefault("excluded_projects", {})
        excluded[project] = "The replay failed."
        with self.assertRaisesRegex(ValueError, "coverage"):
            publish.validate(self.reports)
        for key in ("commands", "timed_session_seconds", "timed_command_seconds"):
            del sessions[key][project]
        tables, _ = publish.render_tables(self.reports, self.ty_worktree, self.ty_scenario)
        self.assertIn(f"| {publish.SESSION_LABELS[project]} (incomplete) | — | — | — |", tables["sessions"])
        self.assertIn("| Completed sessions |", tables["sessions"])
        del excluded[project]
        with self.assertRaisesRegex(ValueError, "coverage"):
            publish.validate(self.reports)

    def test_failed_replay_cannot_include_timings(self):
        report = self.reports["historical"]
        failure = {key: report[key] for key in ("ohm_release", "rust_version")}
        failure["failure"] = {"project": "ruff", "reason": "The replay failed.", "log_sha256": "a" * 64}
        self.reports["historical"] = failure
        publish.validate(self.reports)
        failure["timed_session_seconds"] = {"ruff": {"stock": [1]}}
        with self.assertRaisesRegex(ValueError, "failed replay"):
            publish.validate(self.reports)

    def test_rejects_mismatched_ty_version_or_median(self):
        for change in (
            lambda r: r.update(rust="1.98.0"),
            lambda r: r["session"]["stock"]["total"].update(median=1),
            lambda r: r["worktree"]["ohm-trusted"]["total"].update(samples=[float("nan")]),
        ):
            with self.subTest(change=change):
                study = copy.deepcopy(self.ty_worktree)
                change(study)
                with self.assertRaises(ValueError):
                    publish.render_tables(self.reports, study, self.ty_scenario)

    def test_codex_replay_compares_completed_selections(self):
        sessions = self.reports["sessions"]
        methods = sessions["methodology"].setdefault("test_count_comparison_by_project", {})
        methods["codex"] = publish.CODEX_TEST_COUNT_COMPARISON
        tests = [c for c in sessions["commands"]["codex"] if c["category"] == "test"]
        for command in tests:
            command.setdefault("selected_tests_completed", copy.deepcopy(command["tests_started"]))
        command = tests[-1]
        command["tests_started"] = {"stock": [3439, 3440], "ohm": [3439, 3439]}
        command["selected_tests_completed"] = {"stock": [3439, 3439], "ohm": [3439, 3439]}
        publish.validate(self.reports)
        self.assertEqual(command["tests_started"]["stock"], [3439, 3440])

        command["selected_tests_completed"]["stock"][1] = 3440
        with self.assertRaisesRegex(ValueError, "mismatched command test counts"):
            publish.validate(self.reports)
        command["selected_tests_completed"]["stock"][1] = 3441
        with self.assertRaisesRegex(ValueError, "Invalid selected test counts"):
            publish.validate(self.reports)
        del methods["codex"]
        with self.assertRaisesRegex(ValueError, "Unexpected selected test counts"):
            publish.validate(self.reports)

    def test_rejects_mismatched_or_incomplete_measurements(self):
        changes = [
            lambda r: r["workflow"].update(ohm_release="ohm-0.0.0-1"),
            lambda r: r["workflow"].update(valid_samples=0),
            lambda r: r["sessions"]["methodology"].update(all_commands_succeeded=False),
            lambda r: r["sessions"]["methodology"].update(
                external_compilations_observed=1
            ),
            lambda r: r["sessions"]["timed_command_seconds"]["ruff"][
                "stock"
            ].__setitem__(0, 0),
            lambda r: r["sessions"]["commands"]["ruff"][0]["wall_seconds"][
                "stock"
            ].__setitem__(0, float("nan")),
            lambda r: r["sessions"]["commands"]["ruff"][0]["tests_started"][
                "stock"
            ].__setitem__(0, 999999),
            lambda r: r["disk"]["validation"].update(status="fail"),
        ]
        for change in changes:
            with self.subTest(change=change):
                reports = copy.deepcopy(self.reports)
                change(reports)
                with self.assertRaises(ValueError):
                    publish.validate(reports)

    def test_compaction_preserves_measurements_and_input(self):
        report = self.reports["sessions"]
        report["provenance"]["rejected_host_evidence"] = {"log": "old attempt"}
        report["provenance"]["independent_controls_review"] = {"passed": True}
        report["provenance"]["system_cpu"].update(
            commands=[{"trace": "detailed"}],
            trace_jsonl='{"violations": []}\n',
            preflight_attempts={"attempt-1": {"passed": True}},
            excluded_attempts=[{"passed": False, "trace_jsonl": "stopped warmup"}],
            coverage={"intervals": 2},
        )
        original = copy.deepcopy(report)
        compact = publish.compact(report)
        self.assertEqual(report, original)
        self.assertEqual(compact["commands"], report["commands"])
        self.assertEqual(compact["methodology"], report["methodology"])
        self.assertNotIn("rejected_host_evidence", compact["provenance"])
        self.assertNotIn("independent_controls_review", compact["provenance"])
        self.assertNotIn("commands", compact["provenance"]["system_cpu"])
        self.assertNotIn("trace_jsonl", compact["provenance"]["system_cpu"])
        self.assertNotIn("preflight_attempts", compact["provenance"]["system_cpu"])
        self.assertEqual(
            compact["provenance"]["system_cpu"]["excluded_attempts"],
            [{"passed": False}],
        )
        self.assertEqual(
            compact["provenance"]["system_cpu"]["coverage"],
            report["provenance"]["system_cpu"]["coverage"],
        )

    def test_compaction_preserves_recovery_segment_summaries(self):
        report = {"provenance": {"system_cpu": {}}}
        summaries = [
            {
                "samples": 10,
                "trace_sha256": "trace-hash",
                "preflight_sha256": "preflight-hash",
                "interval_start": start,
                "interval_end": start + 20,
                "accepted_cell_ids": [["ruff", "stock", repetition]],
                "proof": {"passed": passed, "trace": "raw/monitor.jsonl"},
                "scope": "retained" if repetition == 0 else "resumed",
                "preflight": {"passed": True, "sample_count": 6},
            }
            for repetition, start, passed in [(0, 100, False), (1, 200, True)]
        ]
        segments = copy.deepcopy(summaries)
        for segment in segments:
            segment["trace_jsonl"] = '{"violations": []}\n'
            segment["preflight"] = {"passed": True, "samples": [{}] * 6}
        report["provenance"]["system_cpu"]["segments"] = segments
        original = copy.deepcopy(report)

        compact = publish.compact(report)

        self.assertEqual(compact["provenance"]["system_cpu"]["segments"], summaries)
        self.assertEqual(report, original)

    def test_publish_replaces_current_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("README.md", "BENCHMARKS.md"):
                shutil.copyfile(publish.ROOT / name, root / name)
            for name in (
                "scripts/benchmark_results",
                "node_modules/.bin",
                "inputs",
            ):
                (root / name).mkdir(parents=True)
            self.copy_supplemental_reports(root)
            (root / "node_modules/.bin/prettier").touch()
            for kind, report in self.reports.items():
                publish.write_json(root / "inputs" / f"{kind}.json", report)
                publish.write_json(
                    root / "scripts/benchmark_results" / f"{kind}.json",
                    {"ohm_release": "ohm-0.0.0-1"},
                )

            with (
                mock.patch.object(publish, "ROOT", root),
                mock.patch.object(
                    publish, "RESULTS", root / "scripts/benchmark_results"
                ),
                mock.patch.object(publish.subprocess, "run") as run,
            ):
                publish.publish(root / "inputs")
                run.assert_called_once()
                self.assertEqual(
                    run.call_args.args[0][0], str(root / "node_modules/.bin/prettier")
                )
                actual = publish.latest_reports()
                for kind, report in actual.items():
                    if "failure" in report:
                        self.assertEqual(report["failure"], self.reports[kind]["failure"])
                        continue
                    field = (
                        "readme_comparisons"
                        if kind == "disk"
                        else "samples"
                        if kind == "workflow"
                        else "commands"
                    )
                    self.assertEqual(report[field], self.reports[kind][field])
                for name, expected in publish.documents(actual).items():
                    self.assertEqual((root / name).read_text(), expected)
                with self.assertRaisesRegex(ValueError, "Results already exist"):
                    publish.publish(root / "inputs")
            self.assertEqual(
                {
                    path.stem
                    for path in (root / "scripts/benchmark_results").glob("*.json")
                },
                set(publish.KINDS)
                | {
                    Path(publish.TY_WORKTREE_REPORT).stem,
                    Path(publish.DEVELOPER_WORKFLOW_REPORT).stem,
                },
            )


if __name__ == "__main__":
    unittest.main()
