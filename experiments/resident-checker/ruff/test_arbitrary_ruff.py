import unittest

from arbitrary_ruff import paired_timing_statistics


def row(round_number, expected, worker, fresh):
    return {
        "round": round_number,
        "expected": expected,
        "modes": {
            "worker": {"elapsed_ns": worker * 1_000_000},
            "fresh": {"elapsed_ns": fresh * 1_000_000},
        },
    }


class PairedTimingTests(unittest.TestCase):
    def test_pooled_medians_can_disagree_with_matched_edits(self):
        summary = paired_timing_statistics(
            [
                row(0, "pass", 1, 5000),
                row(1, "pass", 10, 11),
                row(1, "pass", 20, 12),
                row(1, "fail", 30, 40),
                row(2, "pass", 1000, 50),
                row(2, "compile_error", 1010, 60),
            ]
        )
        overall = summary["all"]
        self.assertEqual(overall["revisions"], 5)
        self.assertEqual(overall["save_to_result_ms"]["worker"]["median"], 30)
        self.assertEqual(overall["save_to_result_ms"]["fresh"]["median"], 40)
        self.assertEqual(overall["ratio_of_medians_fresh_over_worker"], 1.3333)
        self.assertEqual(overall["median_of_paired_ratios_fresh_over_worker"], 0.6)
        self.assertEqual(
            (overall["worker_wins"], overall["fresh_wins"], overall["ties"]), (2, 3, 0)
        )
        self.assertEqual(summary["successful_compilations"]["revisions"], 4)
        self.assertEqual(summary["by_outcome"]["pass"]["revisions"], 3)
        self.assertEqual(summary["by_outcome"]["compile_error"]["revisions"], 1)
        self.assertEqual(summary["by_round"]["1"]["worker_wins"], 2)
        self.assertEqual(summary["by_round"]["2"]["worker_wins"], 0)

    def test_counts_ties_and_handles_error_only_data(self):
        summary = paired_timing_statistics([row(1, "compile_error", 15, 15)])
        self.assertEqual(summary["all"]["ties"], 1)
        self.assertEqual(
            summary["all"]["paired_ratio_fresh_over_worker"],
            {"min": 1, "median": 1, "p95": 1, "max": 1},
        )
        self.assertIsNone(summary["successful_compilations"])
        self.assertEqual(tuple(summary["by_outcome"]), ("compile_error",))


if __name__ == "__main__":
    unittest.main()
