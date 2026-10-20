"""Keep the overlap comparison isolated from the two default configurations."""

import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import benchmark
import benchmark_workflows
import replay_sessions


FLAG = "CARGO_UNSTABLE_OHM_READY_TESTS"


class ReadyTestComparisonTests(unittest.TestCase):
    def test_commands_enable_overlap_only_in_the_additional_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            study = benchmark.Study(
                benchmark.parser().parse_args(
                    ["--output-dir", str(root), "--compare-ready-tests"]
                )
            )
            (root / "logs").mkdir()
            study.worktrees = {("uv", label): root for label, _ in study.toolchains}
            result = subprocess.CompletedProcess([], 0, "    Finished dev profile\n")
            with (
                mock.patch.dict(os.environ, {FLAG: "true"}),
                mock.patch.object(
                    benchmark.subprocess, "run", return_value=result
                ) as run,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                for label, selector in study.toolchains:
                    study.execute(
                        benchmark.WORKLOADS["uv"],
                        "check",
                        label,
                        selector,
                        phase="noop",
                        repetition=0,
                        expected_crate=None,
                    )
            environments = [call.kwargs["env"] for call in run.call_args_list]
            self.assertEqual(
                [env.get(FLAG) for env in environments], [None, None, "true"]
            )
            self.assertEqual(len({env["CARGO_TARGET_DIR"] for env in environments}), 3)
            self.assertEqual(study.toolchains[1][1], study.toolchains[2][1])

    def test_replays_and_workflows_keep_shared_artifacts_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            for module, constructor in (
                (replay_sessions, replay_sessions.Replay),
                (benchmark_workflows, benchmark_workflows.WorkflowStudy),
            ):
                with self.subTest(runner=module.__name__):
                    options = module.parser().parse_args(
                        [
                            "--project",
                            "uv",
                            "--output-dir",
                            temporary,
                            "--compare-ready-tests",
                        ]
                    )
                    study = constructor(options)
                    with mock.patch.dict(os.environ, {FLAG: "true"}):
                        environments = [
                            study.environment(study.scenarios[0], label, selector, 0)
                            for label, selector in study.toolchains
                        ]
                    self.assertEqual(
                        [env.get(FLAG) for env in environments], [None, None, "true"]
                    )
                    self.assertNotIn("CARGO_BUILD_BUILD_DIR", environments[0])
                    self.assertNotEqual(
                        environments[1]["CARGO_BUILD_BUILD_DIR"],
                        environments[2]["CARGO_BUILD_BUILD_DIR"],
                    )
                    controlled = {FLAG, "CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR"}
                    self.assertEqual(
                        {
                            key: value
                            for key, value in environments[1].items()
                            if key not in controlled
                        },
                        {
                            key: value
                            for key, value in environments[2].items()
                            if key not in controlled
                        },
                    )

    def test_three_configurations_balance_position_and_pair_order(self):
        configurations = (
            ("stock", "stock"),
            ("ohm", "ohm"),
            ("ohm-ready-tests", "ohm"),
        )
        orders = [
            benchmark.toolchain_order(configurations, index) for index in range(6)
        ]
        self.assertEqual(len(set(orders)), 6)
        for index in range(0, 6, 2):
            self.assertEqual(orders[index], orders[index + 1][::-1])
        for first in configurations:
            for position in range(3):
                self.assertEqual(sum(order[position] == first for order in orders), 2)
            for second in configurations:
                if first != second:
                    self.assertEqual(
                        sum(
                            order.index(first) < order.index(second) for order in orders
                        ),
                        3,
                    )

    def test_resume_rejects_switching_comparison_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            arguments = ["--project", "uv", "--output-dir", temporary]
            replay_sessions.Replay(
                replay_sessions.parser().parse_args(arguments)
            ).persist()
            with self.assertRaisesRegex(
                benchmark.BenchmarkError, "different toolchains"
            ):
                replay_sessions.Replay(
                    replay_sessions.parser().parse_args(
                        [*arguments, "--resume", "--compare-ready-tests"]
                    )
                )


if __name__ == "__main__":
    unittest.main()
