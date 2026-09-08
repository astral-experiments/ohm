"""Keep the comparison's lint coverage, arm isolation, and accounting honest."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import benchmark
import benchmark_clippy_codegen as campaign
import replay_sessions


class CampaignTests(unittest.TestCase):
    def test_discard_rejects_paths_outside_campaign_before_removing_anything(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "campaign"
            owned = root / "target"
            unrelated = Path(directory) / "unrelated"
            owned.mkdir(parents=True)
            unrelated.mkdir()
            with self.assertRaises(benchmark.BenchmarkError):
                campaign.discard_artifacts(root, [owned, unrelated])
            self.assertTrue(owned.exists())
            self.assertTrue(unrelated.exists())
            campaign.discard_artifacts(root, [owned])
            self.assertFalse(owned.exists())

    def test_discard_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            link = root / "link"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaises(benchmark.BenchmarkError):
                campaign.discard_artifacts(root, [link])
            self.assertTrue(target.exists())

    def test_workflow_sums_lint_and_test_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            options = benchmark.parser().parse_args(
                ["--output-dir", directory, "--project", "uv"]
            )
            study = campaign.WorkflowStudy(options)
            calls = []

            def execute(instance, workload, workflow, label, selector, **kwargs):
                calls.append((workflow, kwargs))
                instance.samples.append(
                    {"wall_seconds": 3 if workflow == "clippy" else 5, "valid": True}
                )

            with patch.object(benchmark.Study, "execute", execute):
                study.execute(
                    benchmark.WORKLOADS["uv"],
                    "test",
                    "separate",
                    "ohm",
                    phase="direct",
                    repetition=0,
                    expected_crate="uv",
                )
            self.assertEqual(study.cycles[0]["wall_seconds"], 8)
            self.assertEqual([item[0] for item in calls], ["clippy", "test"])
            self.assertIn("it", calls[0][1]["arguments"])
            self.assertEqual(
                calls[0][1]["target_directory"], calls[1][1]["target_directory"]
            )
            self.assertEqual(calls[0][1]["extra_environment"][campaign.OPT_IN], "false")

    def test_combined_has_one_command_and_unmeasured_warmup(self):
        with tempfile.TemporaryDirectory() as directory:
            options = benchmark.parser().parse_args(
                ["--output-dir", directory, "--project", "uv"]
            )
            study = campaign.WorkflowStudy(options)

            def execute(instance, workload, workflow, label, selector, **kwargs):
                self.assertEqual(kwargs["extra_environment"][campaign.OPT_IN], "true")
                instance.samples.append({"wall_seconds": 7, "valid": True})

            with patch.object(benchmark.Study, "execute", execute):
                study.execute(
                    benchmark.WORKLOADS["uv"],
                    "test",
                    "combined",
                    "ohm",
                    phase="warmup",
                    repetition=0,
                    expected_crate=None,
                    record=False,
                )
            self.assertFalse(study.cycles[0]["measured"])
            self.assertEqual(len(study.cycles[0]["components"]), 1)

    def test_balanced_order_covers_all_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            options = benchmark.parser().parse_args(
                ["--output-dir", directory, "--project", "uv"]
            )
            study = campaign.WorkflowStudy(options)
            orders = [
                tuple(label for label, _ in study.ordered_toolchains(i))
                for i in range(6)
            ]
            self.assertEqual(len(set(orders)), 6)
            for label in campaign.ARMS:
                for position in range(3):
                    self.assertEqual(
                        sum(order[position] == label for order in orders), 2
                    )

    def test_replay_preserves_standalone_clippy_and_separates_caches(self):
        with tempfile.TemporaryDirectory() as directory:
            options = replay_sessions.parser().parse_args(
                ["--output-dir", directory, "--project", "uv"]
            )
            study = campaign.SessionStudy(options)
            scenario = study.scenarios[0]
            study.active_step = {"args": ["test"]}
            default = study.environment(scenario, "default", "ohm", 0)
            combined = study.environment(scenario, "combined", "ohm", 0)
            self.assertEqual(default[campaign.OPT_IN], "false")
            self.assertEqual(combined[campaign.OPT_IN], "true")
            for key in ("CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR"):
                self.assertNotEqual(default[key], combined[key])
            self.assertEqual(
                default["CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST"],
                combined["CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST"],
            )
            study.active_step = {"args": ["clippy"]}
            self.assertEqual(
                study.environment(scenario, "combined", "ohm", 0)[campaign.OPT_IN],
                "false",
            )
            lint_steps = [
                step
                for step in scenario.steps
                if step.get("args", [None])[0] == "clippy"
            ]
            self.assertEqual(len(lint_steps), 3)


if __name__ == "__main__":
    unittest.main()
