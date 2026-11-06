"""Check report arithmetic, compaction, and publication."""

import copy
from pathlib import Path
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
        for name in (publish.DEVELOPER_WORKFLOW_REPORT, publish.RUFF_DOCTEST_REPORT):
            shutil.copyfile(publish.RESULTS / name, root / "scripts/benchmark_results" / name)

    def test_ruff_doctests_exclude_cold_runs(self):
        samples = [
            {"pair": pair, "toolchain": lane, "seconds": 1000 if not pair else base + pair}
            for pair in range(6) for lane, base in (("stock", 10), ("ohm", 0))
        ]
        report = {"upstream": "1.99.0", "ohm": "ohm-1.99.0-23", "samples": samples}
        self.assertIn("| 13.000 s | 3.000 s | 4.33× |", publish.ruff_doctest_table(report))
        samples.pop()
        with self.assertRaisesRegex(ValueError, "five warm"):
            publish.ruff_doctest_table(report)

    def test_tables_match_current_reports(self):
        for name, expected in publish.documents(self.reports).items():
            self.assertEqual(
                publish.normalized_markdown(expected),
                publish.normalized_markdown((publish.ROOT / name).read_text()),
            )

    def test_ty_is_included_in_session_and_command_totals(self):
        tables, _, _ = publish.render_tables(
            self.reports, self.ty_worktree, self.ty_scenario
        )
        self.assertIn(
            "| ty | Worktree startup (Btrfs) | `ty_python_semantic` |",
            tables["features"],
        )
        rows = {
            cells[0]: cells[1:3]
            for section in ("sessions", "commands")
            for line in tables[section].splitlines()[2:]
            if (cells := [cell.strip() for cell in line.strip("|").split("|")])
        }
        for index, lane in enumerate(("stock", "ohm")):
            self.assertAlmostEqual(
                float(rows["ty session"][index].removesuffix(" s")),
                statistics.fmean(self.ty_worktree["session"][lane]["total"]["samples"]),
                delta=0.01,
            )
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
            lambda r: r["disk"]["release_manifest"].update(path="toolchains/0.0.0/1.json"),
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

        compact = publish.compact(report)

        self.assertEqual(compact["provenance"]["system_cpu"]["segments"], summaries)
        self.assertEqual(report, original)

    def prepare_publication(self, root):
        for name in ("README.md", "BENCHMARKS.md"):
            shutil.copyfile(publish.ROOT / name, root / name)
        (root / "inputs").mkdir()
        (root / "node_modules/.bin").mkdir(parents=True)
        (root / "node_modules/.bin/prettier").touch()
        self.copy_supplemental_reports(root)

    def test_publish_replaces_current_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare_publication(root)
            disk_rust, disk_version = publish.disk_versions(self.reports["disk"])
            for kind, report in self.reports.items():
                if kind in publish.TIMING_KINDS:
                    report = dict(
                        report, ohm_release=f"ohm-{disk_version}", rust_version=disk_rust
                    )
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
                    Path(publish.RUFF_DOCTEST_REPORT).stem,
                },
            )

    def test_publish_timing_release_preserves_disk_measurements_and_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare_publication(root)
            results = root / "scripts/benchmark_results"
            disk = results / "disk.json"
            disk_bytes = (publish.RESULTS / disk.name).read_bytes()
            disk.write_bytes(disk_bytes)
            disk_rust, disk_version = publish.disk_versions(self.reports["disk"])
            current = self.reports["sessions"]["ohm_release"].removeprefix("ohm-")
            rust, revision = current.rsplit("-", 1)
            version = f"{rust}-{int(revision) + 1}"
            for kind in publish.TIMING_KINDS:
                report = dict(self.reports[kind], ohm_release=f"ohm-{version}")
                publish.write_json(root / "inputs" / f"{kind}.json", report)

            with (
                mock.patch.object(publish, "ROOT", root),
                mock.patch.object(publish, "RESULTS", results),
                mock.patch.object(publish.subprocess, "run") as run,
            ):
                incoming_disk = root / "inputs" / disk.name
                incoming_disk.write_bytes(disk_bytes)
                with self.assertRaisesRegex(ValueError, "New disk measurements"):
                    publish.publish(root / "inputs")
                incoming_disk.unlink()
                publish.publish(root / "inputs")

            self.assertEqual(disk.read_bytes(), disk_bytes)
            self.assertNotIn(
                "scripts/benchmark_results/disk.json", run.call_args.args[0]
            )
            readme = (root / "README.md").read_text()
            results = (root / "BENCHMARKS.md").read_text()
            self.assertIn(
                f"| Scope | Rust {disk_rust} | Ohm {disk_version} | Space saved |", results
            )
            self.assertRegex(
                readme, r"and `target/` disk usage decreases by around \d+%\."
            )
            self.assertIn(f"| Rust {rust} | Ohm {version} | Speedup |", results)
            self.assertIn(f"disk study compared Rust {disk_rust} and Ohm {disk_version}", readme)
            self.assertIn(f"four development sessions with Rust {rust} and Ohm {version}", readme)
            charts = root / "docs/benchmarks"
            self.assertIn(f"Rust {rust} and Ohm {version}.", (charts / "sessions.svg").read_text())
            self.assertIn(f"Rust {disk_rust} and Ohm {disk_version}.", (charts / "disk.svg").read_text())


if __name__ == "__main__":
    unittest.main()
