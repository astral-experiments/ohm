"""Check report arithmetic, evidence preservation, and publication ordering."""

import copy
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile

import publish_benchmarks as publish


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.reports = publish.latest_reports()
        self.ty_worktree = publish.load(publish.RESULTS / publish.TY_WORKTREE_REPORT)
        self.ty_scenario = publish.load(publish.ROOT / publish.TY_SCENARIO)

    def copy_ty_study(self, root):
        destination = root / "scripts/benchmark_results" / publish.TY_WORKTREE_REPORT
        destination.parent.mkdir(parents=True, exist_ok=True)
        publish.write_json(destination, self.ty_worktree)
        fixture = root / publish.TY_SCENARIO
        fixture.parent.mkdir(parents=True, exist_ok=True)
        publish.write_json(fixture, self.ty_scenario)

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
        self.assertIn("| ty session | 287.99 s | 189.85 s | 34.08% |", tables["sessions"])
        self.assertIn(
            "| ty | Worktree startup (Btrfs) | `ty_python_semantic` | 93.42 s | 13.41 s | 6.97× |",
            tables["features"],
        )
        rows = {
            cells[0]: cells[1:3]
            for line in tables["sessions"].splitlines()[2:]
            if (cells := [cell.strip() for cell in line.strip("|").split("|")])
        }
        for index, lane in enumerate(("stock", "ohm")):
            session_sum = sum(
                float(rows[label][index].removesuffix(" s").replace(",", ""))
                for label in ("Ruff session", "uv session", "Codex session", "ty session")
            )
            shown_total = float(
                rows["All sessions"][index].removesuffix(" s").replace(",", "")
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
                rows["All commands"][index].removesuffix(" s").replace(",", "")
            )
            self.assertAlmostEqual(command_sum, all_commands, delta=0.03)
            expected_ty = statistics.fmean(
                self.ty_worktree["session"][lane]["commands"]["samples"]
            )
            old_commands = sum(
                statistics.fmean(
                    self.reports["sessions"]["timed_command_seconds"][p][lane]
                )
                for p in ("ruff", "uv", "codex")
            )
            self.assertAlmostEqual(all_commands, old_commands + expected_ty, delta=0.01)
            for category, label, indices in (
                ("test", "`cargo test`, `cargo nextest`, `just test`", (2, 3, 4, 5)),
                ("clippy", "`cargo clippy`", (8,)),
            ):
                old = sum(
                    statistics.fmean(command["wall_seconds"][lane])
                    for project in ("ruff", "uv", "codex")
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
        report["provenance"]["system_cpu"].update(
            commands=[{"trace": "detailed"}],
            trace_jsonl='{"violations": []}\n',
            preflight_attempts={"attempt-1": {"passed": True}},
            excluded_attempts=[{"passed": False, "trace_jsonl": "stopped warmup"}],
            coverage={"intervals": 2},
        )
        original = copy.deepcopy(report)
        compact = publish.compact(report, {"url": "archive"})
        self.assertEqual(report, original)
        self.assertEqual(compact["commands"], report["commands"])
        self.assertEqual(compact["methodology"], report["methodology"])
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
        report = self.reports["historical"]
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

        compact = publish.compact(report, {"url": "archive"})

        self.assertEqual(compact["provenance"]["system_cpu"]["segments"], summaries)
        self.assertEqual(report, original)

    def test_archive_round_trip_and_determinism(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind, report in self.reports.items():
                publish.write_json(root / f"{kind}.json", report)
            first, second = root / "one.zip", root / "two.zip"
            manifest = publish.archive_reports(root, first)
            publish.archive_reports(root, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                for name, checksum in manifest.items():
                    data = archive.read(name)
                    self.assertEqual(data, (root / name).read_bytes())
                    self.assertEqual(publish.digest(data), checksum)

    def test_failed_download_verification_leaves_checkout_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("README.md", "BENCHMARKS.md"):
                shutil.copyfile(publish.ROOT / name, root / name)
            self.copy_ty_study(root)
            prettier = root / "node_modules/.bin/prettier"
            prettier.parent.mkdir(parents=True)
            prettier.touch()
            inputs = root / "inputs"
            inputs.mkdir()
            for kind, report in self.reports.items():
                publish.write_json(inputs / f"{kind}.json", report)
            before = {
                p.relative_to(root): p.read_bytes()
                for p in root.rglob("*")
                if p.is_file()
            }

            def run(arguments, **kwargs):
                if arguments[:3] == ["gh-auto", "release", "download"]:
                    destination = Path(arguments[-1])
                    destination.mkdir()
                    (
                        destination / arguments[arguments.index("--pattern") + 1]
                    ).write_bytes(b"wrong archive")
                return subprocess.CompletedProcess(arguments, 0)

            with (
                mock.patch.object(publish, "ROOT", root),
                mock.patch.object(
                    publish, "RESULTS", root / "scripts/benchmark_results"
                ),
                mock.patch.object(publish.subprocess, "run", side_effect=run),
            ):
                with self.assertRaisesRegex(ValueError, "Downloaded evidence differs"):
                    publish.publish(inputs)
            after = {
                p.relative_to(root): p.read_bytes()
                for p in root.rglob("*")
                if p.is_file()
            }
            self.assertEqual(before, after)

    def test_verified_archive_publishes_a_single_canonical_session_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("README.md", "BENCHMARKS.md"):
                shutil.copyfile(publish.ROOT / name, root / name)
            for name in (
                "scripts/benchmark_results",
                "scripts/session_replays",
                "node_modules/.bin",
                "inputs",
            ):
                (root / name).mkdir(parents=True)
            self.copy_ty_study(root)
            (root / "node_modules/.bin/prettier").touch()
            for kind, report in self.reports.items():
                publish.write_json(root / "inputs" / f"{kind}.json", report)

            def run(arguments, **kwargs):
                if arguments[:3] == ["gh-auto", "release", "download"]:
                    destination = Path(arguments[-1])
                    destination.mkdir()
                    name = arguments[arguments.index("--pattern") + 1]
                    shutil.copyfile(destination.parent / name, destination / name)
                return subprocess.CompletedProcess(arguments, 0)

            with (
                mock.patch.object(publish, "ROOT", root),
                mock.patch.object(
                    publish, "RESULTS", root / "scripts/benchmark_results"
                ),
                mock.patch.object(publish.subprocess, "run", side_effect=run),
            ):
                publish.publish(root / "inputs")
                actual = publish.latest_reports()
                for kind, report in actual.items():
                    field = (
                        "readme_comparisons"
                        if kind == "disk"
                        else "samples"
                        if kind == "workflow"
                        else "commands"
                    )
                    self.assertEqual(report[field], self.reports[kind][field])
                    self.assertEqual(report["evidence"]["path"], f"{kind}.json")
                for name, expected in publish.documents(actual).items():
                    self.assertEqual((root / name).read_text(), expected)
            self.assertEqual(
                len(list((root / "scripts/session_replays").glob("release-*.json"))), 3
            )


if __name__ == "__main__":
    unittest.main()
