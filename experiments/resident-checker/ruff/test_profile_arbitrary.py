import unittest

from profile_arbitrary import compact_metric, duration, read_profile, summarize_rows


def ns(value):
    return {"secs": value // 1_000_000_000, "nanos": value % 1_000_000_000}


def activity(name, time=0, self_time=0, incremental=0, invocations=0):
    return {
        "label": name,
        "time": ns(time),
        "self_time": ns(self_time),
        "incremental_load_time": ns(incremental),
        "invocation_count": invocations,
    }


def row(items, test=1_000_000):
    activities, queries, counts = read_profile({"query_data": items})
    return {
        "activity_ns": activities,
        "activity_counts": counts,
        "lazy_query_decode_ns": queries,
        "external_ns": {
            "compile": 10_000_000,
            "test": test,
            "save_to_result": 12_000_000,
        },
    }


class ProfileTests(unittest.TestCase):
    def test_duration_across_seconds(self):
        self.assertEqual(duration({"secs": 2, "nanos": 123}), 2_000_000_123)

    def test_keeps_nested_phases_independent_and_sums_exclusive_query_loads(self):
        activities, lazy, _ = read_profile(
            {
                "query_data": [
                    activity("incr_comp_prepare_load_dep_graph", time=10),
                    activity("incr_comp_load_dep_graph", time=8),
                    activity("type_of", time=20, incremental=7),
                    activity("optimized_mir", time=11, incremental=4),
                    activity("metadata_decode_entry_type_of", time=3, self_time=2),
                    activity("metadata_decode_entry_adt_def", time=3, self_time=1),
                ]
            }
        )
        self.assertEqual(activities["incremental"]["prepare_and_load_graph"], 10)
        self.assertEqual(activities["incremental"]["load_graph"], 8)
        self.assertEqual(activities["incremental"]["lazy_query_decode_self_time"], 11)
        self.assertEqual(
            activities["frontend"]["external_crate_metadata_decode_self_time"], 3
        )
        self.assertEqual(lazy, {"type_of": 7, "optimized_mir": 4})
        self.assertNotIn("type_check", activities["frontend"])

    def test_summary_distinguishes_absent_events_from_zero_query_loads(self):
        rows = [
            row(
                [
                    activity("incr_comp_load_dep_graph", time=2_000_000),
                    activity("type_of", incremental=4_000_000),
                ]
            ),
            row([], test=None),
        ]
        result = summarize_rows(rows)
        graph = result["activities"]["incremental"]["load_graph"]
        lazy = result["activities"]["incremental"]["lazy_query_decode_self_time"]
        self.assertEqual(
            (graph["observed"], graph["missing"], graph["ms"]["median"]), (1, 1, 2.0)
        )
        self.assertEqual(
            (lazy["observed"], lazy["missing"], lazy["ms"]["median"]), (2, 0, 2.0)
        )
        self.assertEqual(result["external"]["test"]["missing"], 1)
        self.assertEqual(
            result["largest_lazy_query_decodes"]["type_of"]["ms"]["median"], 2.0
        )
        self.assertIsNone(result["activities"]["backend"]["run_linker"]["ms"])

    def test_duplicate_trace_labels_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError, "repeats event"):
            read_profile({"query_data": [activity("type_of"), activity("type_of")]})

    def test_proc_macro_execution_is_separate_from_all_macro_work(self):
        rows = [
            row(
                [
                    activity("macro_expand_crate", time=100_000_000, invocations=1),
                    activity("expand_proc_macro", time=5_000_000, invocations=21),
                    activity(
                        "expand_derive_proc_macro_outer", time=6_000_000, invocations=21
                    ),
                ]
            ),
            row([]),
        ]
        result = summarize_rows(rows)
        frontend = result["activities"]["frontend"]
        self.assertEqual(
            frontend["macro_expansion_including_module_parsing"]["ms"]["median"], 100
        )
        self.assertEqual(frontend["procedural_macro_calls"]["ms"]["median"], 5)
        self.assertEqual(frontend["derive_macro_outer"]["ms"]["median"], 6)
        self.assertEqual(
            result["activity_counts"]["procedural_macro_calls"],
            {"count": 2, "min": 0, "median": 10.5, "p95": 21, "max": 21},
        )

    def test_public_metric_preserves_missing_data(self):
        result = summarize_rows([row([]), row([], test=None)])
        self.assertEqual(
            compact_metric(result["activities"]["backend"]["run_linker"]),
            {"count": 0, "missing": 2},
        )
        tests = compact_metric(result["external"]["test"])
        self.assertEqual(
            (tests["count"], tests["missing"], tests["median"]), (1, 1, 1.0)
        )
        self.assertNotIn("missing", compact_metric(result["external"]["compile"]))


if __name__ == "__main__":
    unittest.main()
