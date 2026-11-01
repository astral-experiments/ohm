"""Adversarial counter, ordered-worker, antecedent and clean selection checks."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import instructions as p


def witness():
    obj = {
        "official": {
            k: v
            for k, v in p.REGISTERED.items()
            if k in {"attempt", "run", "job", "artifact", "head", "bytes", "sha256"}
        },
        "boot": p.REGISTERED["boot"],
        "contact_only": True,
        "commands": 24,
        "complete_96_case_suites": 18,
        "semantic_commands": 4,
        "expected_E0308": 2,
        "scored": 0,
        "continuation": {"eligible": True},
        "records": {},
    }
    for a, n in (("Eon", 21), ("Con", 4)):
        obj["records"][a] = {
            "comment": {
                "physical": {"full": list(range(n)), "wild": [1, 2], "link_only": []},
                "wild_outputs": ["integration_test::integration_test", "ruff::ruff"],
                "suite_count": 96,
            },
            "invalid": {"status": 101},
        }
    return obj


def results(pos):
    count = 0
    table = {}
    for arm in p.ORDER[pos]:
        rows = {q: {} for q in p.q.PHASES}
        for phase in p.q.HISTORY:
            count += 3
            rows[phase]["clock"] = dict(
                start=count,
                stop=count + 1,
                enabled=10,
                running=10,
                instructions=(201 if arm == "Eon" else 100),
                event_errno=0,
                code=(101 if phase == "invalid" else 0),
                user_us=1,
                system_us=0,
            )
        table[arm] = rows
    return dict(
        head="b" * 40,
        position=pos,
        order=list(p.ORDER[pos]),
        run=10,
        job=int(pos),
        runner="native-" + pos,
        boot="00000000-0000-4000-8000-0000000000" + pos,
        prerequisite=p.REGISTERED,
        qualified=True,
        semantic_commands=4,
        complete_96_case_suites=18,
        records=table,
        observed=p.outcomes(table),
    )


class Contract(unittest.TestCase):
    def test_true_390_contact_identity(self):
        for mutate in (
            lambda x: x["official"].update(artifact=99),
            lambda x: x.update(boot="alternate"),
            lambda x: x["records"]["Con"]["comment"]["physical"]["full"].append(9),
            lambda x: x["records"]["Eon"]["comment"]["wild_outputs"].pop(),
            lambda x: x["continuation"].update(eligible=False),
        ):
            w = witness()
            self.assertEqual(p.enrolled(w)["comment_full"], {"Eon": 21, "Con": 4})
            mutate(w)
            with self.assertRaises(ValueError):
                p.enrolled(w)

    def test_raw_meter(self):
        clock = results("01")["records"]["Con"]["repair"]["clock"]
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

    def test_ratio_and_immutable_orders(self):
        rows = {pos: results(pos) for pos in p.ORDER}
        self.assertTrue(p.pair(rows)["both_strictly_over_two"])
        for e, want in [(199, False), (200, False), (201, True)]:
            x = deepcopy(rows)
            x["02"]["records"]["Eon"]["comment"]["clock"]["instructions"] = e
            x["02"]["observed"] = p.outcomes(x["02"]["records"])
            self.assertEqual(p.pair(x)["both_strictly_over_two"], want)
        for field in ("runner", "job", "boot"):
            x = deepcopy(rows)
            x["02"][field] = x["01"][field]
            with self.assertRaises(ValueError):
                p.pair(x)
        for field, value in [
            ("order", list(p.ORDER["01"])),
            ("qualified", False),
            ("prerequisite", {}),
            ("boot", p.REGISTERED["boot"]),
            ("complete_96_case_suites", 17),
        ]:
            x = deepcopy(rows)
            x["02"][field] = value
            with self.assertRaises(ValueError):
                p.pair(x)
        x = deepcopy(rows)
        x["02"]["records"]["Eon"]["invalid"]["clock"]["running"] -= 1
        with self.assertRaises(ValueError):
            p.pair(x)

    def test_physical_empty_only(self):
        selected = {
            "cli": {"pid": 9, "linked_by": [{"pid": 11}], "externs": {"a": "actual A"}},
            "harness": {"pid": 10, "linked_by": [{"pid": 12}], "externs": {"a": "actual B"}},
        }
        for role, vals in p.reference_owners(selected).items():
            self.assertEqual(vals, dict(pid=None, linked_by=[], externs=selected[role]["externs"]))
        for field, v in (("pid", None), ("pid", False), ("linked_by", [])):
            x = deepcopy(selected)
            x["cli"][field] = v
            with self.assertRaises(ValueError):
                p.reference_owners(x)

    def test_missing_or_substituted_graph(self):
        rows = [{"id": str(i)} for i in range(390)]
        dirty = rows[-3:]
        r = {
            "roster": {
                "Con": {
                    "comment": {
                        k: p.q.sha(p.canonical(v)) for k, v in (("units", rows), ("dirty", dirty))
                    }
                }
            }
        }
        p.rosters_admit(r, "Con", "comment", rows, dirty)
        for o, d in (
            (rows[:-1], dirty),
            (rows, list(reversed(dirty))),
            ([{"id": "foreign"}, *rows[1:]], dirty),
        ):
            with self.assertRaises(ValueError):
                p.rosters_admit(r, "Con", "comment", o, d)


if __name__ == "__main__":
    unittest.main()
