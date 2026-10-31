"""Independent sign/threshold, official-source, host and partition controls before new observations."""

from copy import deepcopy
from fractions import Fraction
from itertools import product
from pathlib import Path
import json
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE / "review")]
import confirm_binding as r
import decision as d
import media

SCHEDULE = json.loads((r.INPUTS / "orders.json").read_bytes())
OLD = json.loads((r.INPUTS / "previous-boots.json").read_bytes())
PILOTS = json.loads((r.INPUTS / "pilots.json").read_bytes())
MIB = 1 << 20


def boot(i):
    return f"12345678-0000-4000-8000-{i:012x}"


def complete():
    hs = {}
    for i, p in enumerate(d.POSITIONS, 1):
        rows = {}
        for role, work, bytes_ in [
            ("Foff", 601, 2048 * MIB),
            ("Fon", 210, 2500 * MIB),
            ("Eon", 213, 2060 * MIB),
        ]:
            rows[role] = {
                phase: {
                    "instructions": work,
                    "enabled": 1000,
                    "running": 995,
                    "allocated": bytes_,
                    "unmetered_allocated": bytes_,
                }
                for phase in d.metrics.PHASES + d.metrics.SAME
            }
        hs[p] = {"boot": boot(i), "order": SCHEDULE[p], "numbers": rows}
    return hs


def integrated():
    return {
        "run": r.OLD_INTEGRATION,
        "head": r.OLD_HEAD,
        "attempt": 1,
        "branch": r.OLD_REF,
        "hosts": {
            p: {
                "job": r.FJOBS[p],
                "id": 223000 + int(p),
                "head": r.OLD_HEAD,
                "name": "ruff-integration-f-confirmation-" + p,
                "size": 456,
                "sha256": "a" * 64,
                "enrollment_sha256": "b" * 64,
                "worker_receipt_sha256": "c" * 64,
                "boot": boot(100 + int(p)),
            }
            for p in r.POS
        },
    }


def documents():
    run = 8233100
    head = "a" * 40
    common = {"head_sha": head, "run_id": run, "status": "completed", "conclusion": "success"}
    top = {
        "id": run,
        "run_attempt": 1,
        "head_sha": head,
        "head_branch": r.REF,
        "event": "workflow_dispatch",
        "path": ".github/workflows/ci.yml",
        "status": "completed",
        "conclusion": "success",
    }
    jobs = [dict(common, id=231, name=media.PREFLIGHT, steps=[])]
    assets = []
    for i, p in enumerate(d.POSITIONS):
        jobs.append(
            dict(
                common,
                id=232 + i,
                name=media.LABEL + p,
                steps=[{"name": media.CARGO_STEP, "conclusion": "success"}],
            )
        )
        assets.append(
            {
                "name": media.PREFIX + p,
                "id": 7000 + i,
                "size_in_bytes": 64,
                "digest": "sha256:" + "8" * 64,
                "expired": False,
                "workflow_run": {"id": run, "head_sha": head},
            }
        )
    return (
        run,
        head,
        {
            "run": top,
            "jobs": {"total_count": len(jobs), "jobs": jobs},
            "artifacts": {"total_count": len(assets), "artifacts": assets},
        },
    )


class Confirmation(unittest.TestCase):
    def test_schedule(self):
        self.assertEqual(d.orders(SCHEDULE), SCHEDULE)
        other = deepcopy(SCHEDULE)
        other["12"] = other["11"]
        with self.assertRaises(ValueError):
            d.orders(other)

    def test_exact_sign_coverage(self):
        excluded = sum(1 for signs in product((0, 1), repeat=12) if sum(signs) in (0, 1, 11, 12))
        self.assertEqual(excluded, 26)
        self.assertEqual(d.MARGINAL, 1 - Fraction(excluded, 4096))
        self.assertEqual(d.SIMULTANEOUS, Fraction(1983, 2048))
        self.assertEqual(d.median(range(1, 13)), Fraction(13, 2))

    def test_all_raw_thresholds(self):
        h = complete()
        s = d.cohort(h, SCHEDULE, set(OLD))
        self.assertTrue(s["all_five_and_all_boots_pass"])
        self.assertEqual(s["included_pilot_observations"], 0)
        # Two source histories and two independently allocated lanes, so any one can be the failing member.
        for phase, lane in product(d.FIRST, d.LANES):
            v = deepcopy(h)
            m = v["07"]["numbers"]
            n = m["Eon"][phase]
            n[lane] = m["Foff"][phase][lane] + 64 * MIB
            self.assertTrue(d.cohort(v, SCHEDULE, OLD)["all_five_and_all_boots_pass"])
            n[lane] += 1
            q = d.cohort(v, SCHEDULE, OLD)
            self.assertFalse(q["all_five_and_all_boots_pass"])
            self.assertTrue(
                q["five_planned_endpoints"]["max_extra_bytes"]["interval_clears_threshold"]
            )
            n[lane] = m["Foff"][phase][lane] + MIB
            m["Fon"][phase][lane] = n[lane] + 250 * MIB
            self.assertTrue(d.cohort(v, SCHEDULE, OLD)["all_five_and_all_boots_pass"])
            m["Fon"][phase][lane] -= 1
            self.assertFalse(d.cohort(v, SCHEDULE, OLD)["all_five_and_all_boots_pass"])

    def test_repair_and_cpu_cost_share_no_extra_hypothesis(self):
        hosts = complete()
        for p in hosts:
            hosts[p]["numbers"]["Eon"]["repair"]["allocated"] = (2600 + int(p)) * MIB
            hosts[p]["numbers"]["Eon"]["repair"]["instructions"] = 483 + int(p)
        result = d.cohort(hosts, SCHEDULE, OLD)
        self.assertTrue(result["all_five_and_all_boots_pass"])
        sec = result["descriptive_warm_cold_edits_repair_and_maxima"]
        self.assertEqual(
            sec["instructions"]["repair"]["Eon_over_Fon"]["range"],
            [d.form(Fraction(484, 210)), d.form(Fraction(495, 210))],
        )
        self.assertEqual(
            sec["storage"]["allocated"]["largest_visit_end"]["main"]["Eon"]["range"],
            [[2601 * MIB, 1], [2612 * MIB, 1]],
        )
        self.assertEqual(len(result["five_planned_endpoints"]), 5)

    def test_strict_direction_aggregate_and_count(self):
        for phase in ("return-A", "return-B"):
            h = complete()
            m = h["04"]["numbers"]
            m["Foff"][phase]["instructions"] = 2 * m["Eon"][phase]["instructions"]
            q = d.cohort(h, SCHEDULE, OLD)
            self.assertFalse(q["all_five_and_all_boots_pass"])
            self.assertTrue(q["five_planned_endpoints"]["return_sum"]["all_12"])
        h = complete()
        m = h["04"]["numbers"]
        m["Eon"]["return-A"]["instructions"] = 100
        m["Eon"]["return-B"]["instructions"] = 500
        m["Foff"]["return-A"]["instructions"] = 400
        m["Foff"]["return-B"]["instructions"] = 800
        q = d.cohort(h, SCHEDULE, OLD)
        self.assertEqual(q["positions"]["04"]["primary"]["return_sum"], [2, 1])
        self.assertFalse(q["five_planned_endpoints"]["return_sum"]["all_12"])
        h = complete()
        h["02"]["numbers"]["Eon"]["same-edit"]["running"] = 994
        with self.assertRaises(ValueError):
            d.cohort(h, SCHEDULE, OLD)

    def test_boot_missing_order(self):
        for tweak in (
            lambda h: h.pop("06"),
            lambda h: h["08"].update(boot=h["01"]["boot"]),
            lambda h: h["08"].update(boot=OLD[0]),
            lambda h: h["03"].update(order=SCHEDULE["04"]),
            lambda h: h["09"]["numbers"]["Eon"].pop("repair"),
        ):
            h = complete()
            tweak(h)
            with self.assertRaises(ValueError):
                d.cohort(h, SCHEDULE, OLD)

    def test_prior_custody(self):
        proper = integrated()
        self.assertEqual(len(r.validated_prior(OLD, proper, PILOTS)), 66)
        with self.assertRaises(ValueError):
            r.validated_prior(OLD, None, PILOTS)
        for tweak in (
            lambda k: k.update(attempt=2),
            lambda k: k.update(head="9" * 40),
            lambda k: k["hosts"].pop("04"),
            lambda k: k["hosts"]["09"].update(boot=OLD[0]),
            lambda k: k["hosts"]["02"].update(boot=k["hosts"]["01"]["boot"]),
            lambda k: k["hosts"]["12"].update(id=k["hosts"]["11"]["id"]),
            lambda k: k["hosts"]["10"].update(job=2),
            lambda k: k["hosts"]["06"].update(enrollment_sha256="missing"),
        ):
            x = deepcopy(proper)
            tweak(x)
            with self.assertRaises(ValueError):
                r.validated_prior(OLD, x, PILOTS)

    def test_catalog(self):
        run, head, docs = documents()
        self.assertEqual(len(media.catalog(run, head, docs, require_success=True)), 12)
        for tweak in (
            lambda q: q["run"].update(run_attempt=2),
            lambda q: q["run"].update(head_sha="c" * 40),
            lambda q: q["jobs"]["jobs"][-1].update(conclusion="failure"),
            lambda q: q["jobs"]["jobs"][1].update(steps=[]),
            lambda q: q["artifacts"]["artifacts"].pop(),
            lambda q: q["artifacts"]["artifacts"][-1].update(name=media.PREFIX + "01"),
            lambda q: q["artifacts"]["artifacts"][0].update(expired=True),
            lambda q: q["artifacts"]["artifacts"][0]["workflow_run"].update(id=99),
        ):
            x = deepcopy(docs)
            tweak(x)
            with self.assertRaises(ValueError):
                media.catalog(run, head, x, require_success=True)
        failed = deepcopy(docs)
        failed["run"]["conclusion"] = "failure"
        failed["jobs"]["jobs"][3]["conclusion"] = "failure"
        self.assertEqual(len(media.catalog(run, head, failed, require_success=False)), 12)
        with self.assertRaises(ValueError):
            media.catalog(run, head, failed, require_success=True)

    def test_actual_pilot_release_bindings(self):
        records = json.loads((HERE / "review/fixtures/prior-official.json").read_bytes())
        for seed in PILOTS["runs"].values():
            n = str(seed["run"])

            def verify(sample):
                return r.official(lambda key: sample[key.removeprefix("runs/")], seed, 2)

            verify(records)
            for corrupt in (
                lambda doc: doc[n].update(run_attempt=2),
                lambda doc: doc[n].update(head_sha="a" * 40),
                lambda doc: doc[n + "/attempts/1/jobs?per_page=100"]["jobs"][0].update(
                    conclusion="failure"
                ),
                lambda doc: doc[n + "/artifacts?per_page=100"]["artifacts"][0].update(
                    digest="sha256:" + "a" * 64
                ),
                lambda doc: doc[n + "/artifacts?per_page=100"]["artifacts"][0].update(expired=True),
                lambda doc: doc[n + "/artifacts?per_page=100"]["artifacts"][0][
                    "workflow_run"
                ].update(id=99),
            ):
                bad = deepcopy(records)
                corrupt(bad)
                with self.assertRaises(ValueError):
                    verify(bad)

    def test_refused_preflight_preserves_its_empty_catalog(self):
        run, head, docs = documents()
        docs["run"]["conclusion"] = "failure"
        docs["jobs"]["total_count"] = 1
        docs["jobs"]["jobs"] = docs["jobs"]["jobs"][:1]
        docs["jobs"]["jobs"][0]["conclusion"] = "failure"
        docs["artifacts"] = {"total_count": 0, "artifacts": []}
        self.assertEqual(media.catalog(run, head, docs, require_success=False), {})
        with self.assertRaises(ValueError):
            media.catalog(run, head, docs, require_success=True)

    def test_raw_hash(self):
        import hashlib

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "original"
            path.write_bytes(b"original")
            v = {"size": 8, "sha256": hashlib.sha256(b"original").hexdigest()}
            media.verify(path, v)
            path.write_bytes(b"changed!")
            with self.assertRaises(ValueError):
                media.verify(path, v)
            other = root / "symlink"
            other.symlink_to(path)
            with self.assertRaises(ValueError):
                media.verify(other, v)

    def test_null_does_not_launch(self):
        # Run this particular refusal while the real preceding twelve have not yet been authenticated.
        if json.loads((r.INPUTS / "integration-boots.json").read_bytes()) is None:
            with self.assertRaisesRegex(ValueError, "awaiting genuine integration"):
                r.local()


if __name__ == "__main__":
    unittest.main()
