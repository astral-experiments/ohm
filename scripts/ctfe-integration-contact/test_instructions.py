"""Applicable regression controls retained from the earlier real 96-test contact."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import instructions as p


class Contract(unittest.TestCase):
    def test_raw_meter(self):
        clock = dict(
            start=10,
            stop=20,
            enabled=10,
            running=10,
            instructions=100,
            event_errno=0,
            code=0,
            user_us=1,
            system_us=0,
        )
        self.assertEqual(p.timed(clock, "repair"), 100)
        for patch in [
            dict(running=9),
            dict(running=11),
            dict(instructions=True),
            dict(event_errno=13),
            dict(enabled=0, running=0),
            dict(code=101),
            dict(start=clock["stop"]),
            dict(user_us=0),
        ]:
            with self.assertRaises(ValueError):
                p.timed(clock | patch, "repair")
        with self.assertRaises(ValueError):
            p.timed(clock, "invalid")

    def test_physical_empty_only(self):
        selected = {
            "cli": {"pid": 9, "linked_by": [{"pid": 11}], "externs": {"a": "actual A"}},
            "harness": {
                "pid": 10,
                "linked_by": [{"pid": 12}],
                "externs": {"a": "actual B"},
            },
        }
        for role, vals in p.reference_owners(selected).items():
            self.assertEqual(
                vals, dict(pid=None, linked_by=[], externs=selected[role]["externs"])
            )
        for field, v in (("pid", None), ("pid", False), ("linked_by", [])):
            x = deepcopy(selected)
            x["cli"][field] = v
            with self.assertRaises(ValueError):
                p.reference_owners(x)


if __name__ == "__main__":
    unittest.main()
