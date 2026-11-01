"""Two real hardware histories calibrate the order check; neither contributes a sample."""

import copy
import json
from pathlib import Path
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import confirmation as c
import contract as q
import instructions as policy


def original(case):
    file = q.HERE / "native-order-controls.json"
    assert (
        q.sha(file.read_bytes())
        == "107faaec36df7c2307eb877faea0edf8b1483f3622b23e48d47190cd3534802a"
    )
    obj = json.loads(file.read_bytes())[case]["members"]
    result = {}
    for name, (digest, data) in obj.items():
        assert q.sha(data.encode()) == digest
        result[name] = json.loads(data)
    return result


def records(position):
    source = original("contact")
    reverse = original("reverse")
    out = {}
    for arm in q.ARMS:
        rows = {"physical/X-B": source[arm + "/physical/X-B/visit.json"]}
        for phase in policy.PLAIN:
            clock = (
                source[arm + "/ordinary/" + phase + "/clock.json"]
                if int(position) % 2
                else reverse["measured-return-" + arm + "/" + phase + "/clock.json"]
            )
            policy.timed(clock, phase)
            rows["ordinary/" + phase] = {"clock": clock}
        out[arm] = rows
    return out


def hosts():
    return {
        p: dict(
            position=p,
            run=10000,
            head="f" * 40,
            runner="nsc-runner-test" + p,
            runner_id=7_000_000 + int(p),
            job=8_000_000 + int(p),
            artifact=9_000_000 + int(p),
            boot="fc424242-0000-4040-bfa4-0000000000" + p,
            bytes=100,
            sha256=p * 32,
            position_sha256="a" * 64,
            order=list(c.order(p)),
        )
        for p in c.POSITIONS
    }


def registry():
    hs = hosts()
    return hs, {
        p: dict(
            qualified=True,
            boot=h["boot"],
            complete_suites=24,
            official={**h, "attempt": 1},
            records=records(p),
        )
        for p, h in hs.items()
    }


class Confirmation(unittest.TestCase):
    def test_reviewed_plan_and_independent_genuine_records(self):
        self.assertEqual(q.sha((q.HERE / "PLAN.md").read_bytes()), c.PLAN)
        self.assertEqual(
            q.sha((q.HERE / "contact-x-b-roster.json").read_bytes()),
            "835df1eccf3b3530032c71cb2f53d9ee12f5193b6d0c40c1e12a2a8abb19900d",
        )
        self.assertEqual(len(c.exclusions()["boots"]), 132)
        for p in c.POSITIONS:
            c.subjects(records(p), p)
            with self.assertRaises(ValueError):
                c.subjects(records("02" if int(p) % 2 else "01"), p)

    def test_refuse_different_real_roster_or_linker(self):
        for field in ("full", "link_only", "wild"):
            r = records("01")
            r["Don"]["physical/X-B"]["physical"][field].append(["extra", "lib", False])
            with self.assertRaises(ValueError):
                c.subjects(r, "01")
        r = records("01")
        r["Eon"]["physical/X-B"]["wild_outputs"].pop()
        with self.assertRaises(ValueError):
            c.subjects(r, "01")

    def test_boot_runner_numeric_id_job_artifact_and_order(self):
        old = c.exclusions()
        for field in ("boot", "runner", "runner_id", "job", "artifact"):
            hs = hosts()
            hs["03"][field] = hs["01"][field]
            with self.assertRaises(ValueError):
                c.check_hosts(hs)
        for field, key in (
            ("boot", "boots"),
            ("runner", "runners"),
            ("runner_id", "runner_ids"),
            ("job", "jobs"),
        ):
            hs = hosts()
            hs["04"][field] = old[key][0]
            with self.assertRaises(ValueError):
                c.check_hosts(hs)
        for field, value in (
            ("order", ["Eon", "Don"]),
            ("sha256", "partial"),
            ("run", 1),
            ("head", "d" * 40),
            ("bytes", False),
        ):
            hs = hosts()
            hs["02"][field] = value
            with self.assertRaises(ValueError):
                c.check_hosts(hs)

    def test_official_and_archive_positions_must_agree(self):
        h = hosts()["01"]
        p = dict(
            mode=c.MODE,
            position="01",
            order=list(c.order("01")),
            runner=h["runner"],
            run=h["run"],
            head=h["head"],
            command=q.COMMAND,
            plan=c.PLAN,
            contact=c.CONTACT,
            exclusions=c.EXCLUSIONS,
            boot=h["boot"],
        )
        c.position_record(p, h)
        for key, value in (
            ("mode", "one-host-contact"),
            ("position", "02"),
            ("order", ["Don", "Eon"]),
            ("contact", 7),
            ("boot", hosts()["02"]["boot"]),
            ("plan", "a" * 64),
        ):
            with self.assertRaises(ValueError):
                c.position_record(p | {key: value}, h)

    def test_official_jobs_assets_and_full_original(self):
        from tempfile import TemporaryDirectory

        hs = hosts()
        rid, head = hs["01"]["run"], hs["01"]["head"]
        raw = b"reviewed synthetic source-binding fixture"
        hs["04"].update(bytes=len(raw), sha256=q.sha(raw))
        registrations = {
            p: {"job": v["job"], "order": list(c.order(p))} for p, v in hs.items()
        }
        run = dict(
            id=rid,
            repository={"full_name": c.REPO},
            head_repository={"full_name": c.REPO},
            head_sha=head,
            head_branch=q.BRANCH,
            event="workflow_dispatch",
            run_attempt=1,
            path=".github/workflows/ci.yml",
            status="completed",
            conclusion="success",
        )
        jobs = [
            dict(
                id=v["job"],
                name=c.LABEL + p,
                runner_name=v["runner"],
                runner_id=v["runner_id"],
                head_sha=head,
                run_id=rid,
                run_attempt=1,
                labels=["namespace-profile-ubuntu-24-04-16"],
                status="completed",
                conclusion="success",
                steps=[{"conclusion": "success"}],
            )
            for p, v in hs.items()
        ]
        assets = [
            dict(
                name=c.ARTIFACT + p,
                id=v["artifact"],
                expired=False,
                size_in_bytes=v["bytes"],
                digest="sha256:" + v["sha256"],
                workflow_run={"id": rid, "head_sha": head},
            )
            for p, v in hs.items()
        ]
        data = {
            "pre-outcome": dict(
                run=rid, head=head, attempt=1, assets=0, positions=registrations
            ),
            "run": run,
            "jobs": dict(total_count=6, jobs=jobs),
            "artifacts": dict(total_count=6, artifacts=assets),
            "boot-admission": dict(
                run=rid, head=head, outcomes_opened=0, admitted=True, hosts=hs
            ),
        }
        with TemporaryDirectory() as td:
            top = Path(td)
            f = top / "original.zip"
            f.write_bytes(raw)

            def read(obj):
                for k, v in obj.items():
                    (top / (k + ".json")).write_text(json.dumps(v))
                return c.official(top, f, head, "04")

            self.assertEqual(read(data), hs["04"] | {"attempt": 1})
            for group, field, val in (
                ("run", "run_attempt", 2),
                ("run", "conclusion", "cancelled"),
                ("pre-outcome", "assets", 1),
                ("boot-admission", "outcomes_opened", 1),
            ):
                bad = copy.deepcopy(data)
                bad[group][field] = val
                with self.assertRaises(ValueError):
                    read(bad)
            for group, key, field, val in (
                ("jobs", "jobs", "labels", ["ubuntu-latest"]),
                ("jobs", "jobs", "runner_id", 7),
                ("artifacts", "artifacts", "digest", "sha256:" + "0" * 64),
                ("artifacts", "artifacts", "expired", True),
            ):
                bad = copy.deepcopy(data)
                bad[group][key][3][field] = val
                with self.assertRaises(ValueError):
                    read(bad)
            f.write_bytes(b"x" * len(raw))
            with self.assertRaises(ValueError):
                read(data)

    def test_all_six_integer_pairs_and_ties(self):
        hs, rs = registry()
        # Synthetic integer samples exercise only the distribution-free decision.
        for i, (p, r) in enumerate(rs.items()):
            r["records"]["Eon"]["ordinary/X-B"]["clock"]["instructions"] = 300 + i
            r["records"]["Don"]["ordinary/X-B"]["clock"]["instructions"] = 100
        result = c.evaluate(rs, hs)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["median"], [121, 40])
        self.assertEqual(result["interval"], [[3, 1], [61, 20]])
        self.assertEqual(result["one_sided_sign_tail"], [1, 64])
        rs["04"]["records"]["Eon"]["ordinary/X-B"]["clock"]["instructions"] = 200
        r = c.evaluate(rs, hs)
        self.assertFalse(r["accepted"])
        self.assertEqual(r["wins"], 5)
        self.assertEqual(r["one_sided_sign_tail"], [7, 64])
        for field, test in (
            ("complete_suites", 23),
            ("qualified", False),
            ("boot", hs["06"]["boot"]),
        ):
            case = copy.deepcopy(rs)
            case["01"][field] = test
            with self.assertRaises(ValueError):
                c.evaluate(case, hs)
        bad = copy.deepcopy(rs)
        bad["01"]["records"]["Don"]["ordinary/X-B"]["clock"]["instructions"] = False
        with self.assertRaises(ValueError):
            c.evaluate(bad, hs)
        del rs["05"]
        with self.assertRaises(ValueError):
            c.evaluate(rs, hs)


if __name__ == "__main__":
    unittest.main()
