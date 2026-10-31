"""Arithmetic QA with invented numbers only; no acquisition entrypoint."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import ARMS, MIB, PHASES, SAME, evaluate


def fixture():
    rows = {}
    for arm in ARMS:
        rows[arm] = {}
        for phase in PHASES + SAME:
            space = 2500
            cost = 200
            if phase == "cold-A":
                cost = 1000
            if phase in ("first-B", "same-first-B"):
                cost = 500 if arm == "Eoff" else 600
                space = {"Eoff": 2500, "Kon": 2862, "Eon": 2514}[arm]
            if phase in ("return-A", "return-B"):
                cost = 450 if arm == "Eoff" else 100
            rows[arm][phase] = {
                "instructions": cost,
                "running": 995,
                "enabled": 1000,
                "allocated": space * MIB,
                "unmetered_allocated": space * MIB,
            }
    return rows


class Arithmetic(unittest.TestCase):
    def test_positive(self):
        result = evaluate(fixture())
        self.assertTrue(result["meets_numeric_margins"])
        self.assertEqual(
            result["storage"]["allocated"]["visits"]["first-B"]["Eon_minus_Eoff"], 14 * MIB
        )
        self.assertEqual(result["instructions"]["returns"]["Eoff_over_Eon"]["decimal"], 4.5)

    def test_cannot_substitute_Kon_unchanged_for_candidate(self):
        rows = fixture()
        rows["Eon"] = rows["Kon"]
        result = evaluate(rows)
        self.assertFalse(result["meets_numeric_margins"])
        self.assertTrue(result["gates"]["instructions"]["overall_2x_returns"])

    def test_charge_first_switch_regardless_of_return(self):
        rows = fixture()
        rows["Eon"]["first-B"]["instructions"] = 691
        self.assertFalse(evaluate(rows)["gates"]["instructions"]["first_within_15_percent_of_Kon"])

    def test_recovery_space_matters_in_each_lane(self):
        for lane in ("allocated", "unmetered_allocated"):
            rows = fixture()
            rows["Eon"]["repair"][lane] += 8 * MIB + 1
            self.assertFalse(evaluate(rows)["gates"][lane]["repair_no_more_than_8_MiB_extra"])

    def test_bad_direction_does_not_hide_in_sum(self):
        rows = fixture()
        rows["Eoff"]["return-B"]["instructions"] = 199
        result = evaluate(rows)
        self.assertFalse(result["gates"]["instructions"]["overall_2x_return-B"])
        self.assertTrue(result["gates"]["instructions"]["overall_2x_returns"])

    def test_missing_base_advantage_is_ineligible(self):
        rows = fixture()
        for phase in ("return-A", "return-B"):
            rows["Kon"][phase]["instructions"] = 600
        self.assertFalse(
            evaluate(rows)["gates"]["instructions"]["at_least_90_percent_of_Kon_saving"]
        )

    def test_first_without_same_branch_does_not_admit(self):
        rows = fixture()
        rows["Eon"]["same-first-B"]["allocated"] = rows["Kon"]["same-first-B"]["allocated"]
        self.assertFalse(evaluate(rows)["meets_numeric_margins"])

    def test_same_branch_edit_is_charged(self):
        rows = fixture()
        rows["Eon"]["same-edit"]["instructions"] = 251
        result = evaluate(rows)
        self.assertFalse(result["gates"]["instructions"]["same_edit_within_10_percent_of_Kon"])
        self.assertFalse(
            result["gates"]["instructions"]["same_cold_plus_edit_within_5_percent_of_Kon"]
        )

    def test_reject_invalid_event_or_missing_phase(self):
        for key, value in (
            ("running", 994),
            ("running", 1001),
            ("instructions", True),
            ("allocated", 0),
        ):
            rows = fixture()
            rows["Eon"]["invalid"][key] = value
            with self.assertRaises(ValueError):
                evaluate(rows)
        rows = fixture()
        del rows["Eoff"]["invalid"]
        with self.assertRaises(ValueError):
            evaluate(rows)

    def test_gate_inclusive_rounded_display_irrelevant(self):
        rows = fixture()
        rows["Eon"]["return-A"]["instructions"] = 120
        self.assertTrue(evaluate(rows)["gates"]["instructions"]["returns_within_10_percent_of_Kon"])
        rows["Eon"]["return-A"]["instructions"] += 1
        self.assertFalse(
            evaluate(rows)["gates"]["instructions"]["returns_within_10_percent_of_Kon"]
        )


if __name__ == "__main__":
    unittest.main()
