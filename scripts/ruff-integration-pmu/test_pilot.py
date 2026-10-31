"""Synthetic gate positives and negatives. No Ruff result or Rust build is opened."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import verify as v


def mock(position):
    return {"position":position,"head":"h","run":11,"boot":position,"order":v.ORDER[position],
            "calibration":{"cpu":{},"pmu":"toy"},"structural":v.a.SHA,
            "observations":{arm:{phase:{"instructions":300 if arm=="Foff" and "return-" in phase else 100} for phase in v.VISITS} for arm in v.a.ARMS}}


class Tests(unittest.TestCase):
    def test_both_orders_and_all_phases(self):
        result=v.pair(mock("01"),mock("02"))
        self.assertTrue(result["qualifies_for_separate_confirmation"])
        self.assertEqual(result["positions"]["01"]["off_over_on"]["return_sum"],[3,1])
        self.assertEqual(result["positions"]["02"]["off_over_on"]["all_seven"],[11,7])

    def test_single_bad_return_refuses(self):
        x,y=mock("01"),mock("02")
        y["observations"]["Foff"]["return-B"]["instructions"]=200
        self.assertFalse(v.pair(x,y)["qualifies_for_separate_confirmation"])

    def test_reused_boot_wrong_order_missing_phase(self):
        x=mock("01");y=mock("02")
        for wrong in (y|{"boot":"01"},y|{"order":x["order"]},y|{"calibration":{"cpu":{},"pmu":"different"}},y|{"head":"other"}):
            with self.assertRaises(ValueError):v.pair(x,wrong)
        del y["observations"]["Fon"]["repair"]
        with self.assertRaises(ValueError):v.pair(x,y)

    def test_counter_values_and_other_cohort_custody(self):
        x,y=mock("01"),mock("02")
        for bad in (0,-3,True,2.0):
            variant=deepcopy(x)
            variant["observations"]["Fon"]["return-A"]["instructions"]=bad
            with self.assertRaises(ValueError):v.pair(variant,y)
        cohorts=[]
        for name,run in (("c1",41219513694),("c2",41219530573)):
            record={"spec":{"cohort":name,"run":run,"head":"1d446332e82ca0188f63c3fddc9689f1f131fd42"},
                    "positions":{f"{i:02d}":{"host":{"boot":name+str(i)}} for i in range(1,13)}}
            cohorts.append({"receipt":record})
        self.assertEqual(v.compare_other_boots({},x,y,*cohorts)["disjoint_confirmed_packed_boots"],24)
        cohorts[1]["receipt"]["positions"]["12"]["host"]["boot"]=x["boot"]
        with self.assertRaises(ValueError):v.compare_other_boots({},x,y,*cohorts)

    def test_real_entrypoint_without_checkout_cwd(self):
        with tempfile.TemporaryDirectory() as d:
            result=subprocess.check_output([sys.executable,"-IB",HERE/"pilot.py","--print-command"],cwd=d,
                                        env=os.environ|{"RUNNER_TEMP":d})
            self.assertEqual(json.loads(result),v.s.CARGO)

    def test_actual_unscored_antecedent(self):
        d=json.loads((HERE/"structure.json").read_bytes())
        self.assertEqual(d["original"]["sha256"],v.a.SHA)
        self.assertEqual({(x["full"],x["link_only"],x["wild"]) for k,x in d["structural"].items() if k.endswith("unchanged-B")},{(0,2,2)})
        self.assertEqual(d["structural"]["Fon/repair"]["typed"],390)
if __name__=="__main__":unittest.main()
