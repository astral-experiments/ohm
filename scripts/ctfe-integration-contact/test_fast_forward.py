"""Exercise the enrolled imports, scope and narrow new negative cases, without running Cargo."""

import argparse
import json
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("RUNNER_TEMP", "/tmp")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as q
import instructions as plan
import reopen_contact as review
import contact as worker


def rows():
    result = {}
    refs = {
        k: {"cli": k, "harness": k + "-test", "reader": k + "-consumer"}
        for k in q.EMPTY
    }
    for arm in plan.ORDER:
        rs = {}
        for lane, phase in plan.ACTIONS:
            counter = plan.is_counter(lane, phase)
            bad = phase == "invalid"
            rs[lane + "/" + phase] = dict(
                status=101 if bad else 0,
                typed=390,
                dirty=21,
                physical=None
                if counter
                else {"full": [["ruff_python_ast", "lib", False]]},
                wild_outputs=None
                if counter
                else ["integration_test::integration_test", "ruff::ruff"],
            )
            if not bad:
                rs[lane + "/" + phase]["products"] = refs[q.reference(phase)]
            if counter:
                rs[lane + "/" + phase]["clock"] = {
                    "instructions": 421 if arm == "Eon" else 200
                }
        result[arm] = rs
    return result


class Gates(unittest.TestCase):
    def test_main_import_paths(self):
        donor, selection, suite = q.packages()
        import pilot as h

        self.assertEqual(
            (h.subjects.E, h.subjects.D),
            (
                "393b4b05a4bfa3f531a36023846f86236a6b71a9",
                "d95494a6a63c22222806c06e3d3aa0de504d8e8a",
            ),
        )
        self.assertEqual(
            Path(h.__file__).resolve(), donor / "scripts/ctfe-crossover-pilot/pilot.py"
        )
        self.assertEqual(plan.ORDER, tuple(h.subjects.ARMS))
        self.assertTrue(callable(review.official) and callable(review.read))
        self.assertEqual(
            q.COMMAND,
            [
                "cargo",
                "+ohm",
                "test",
                "-p",
                "ruff",
                "--test",
                "integration_test",
                "--no-run",
                "--locked",
                "--offline",
                "-j4",
                "--message-format=json",
            ],
        )
        verified = suite.inventory(
            (Path(suite.__file__).with_name("expected-tests.txt")).read_bytes()
        )
        self.assertEqual(len(verified), 96)
        self.assertEqual(h.reg.OBSERVER, q.KERNEL)
        self.assertEqual(h.reg.hardware_gate()["source_run"], 41303656721)

    def test_inventory(self):
        self.assertEqual(len(plan.ACTIONS), 15)
        self.assertEqual(sum(plan.is_counter(l, p) for l, p in plan.ACTIONS), 3)
        self.assertEqual(set(plan.LAYOUT["empty"]), set(q.EMPTY))
        self.assertEqual(
            plan.plan("ordinary", "dirty-X-B"), ("clean-semantic", "X-B", "dirty")
        )
        self.assertEqual(
            plan.plan("ordinary", "comment"), ("comment", "comment", "dirty")
        )
        self.assertEqual(plan.plan("ordinary", "X-B"), ("X-B", "X-B", "return"))
        self.assertEqual(plan.plan("physical", "X-B"), ("X-B", "X-B", "return"))
        with self.assertRaises(ValueError):
            plan.plan("physical", "comment")

    def test_decision(self):
        r = rows()
        self.assertTrue(plan.outcomes(r)["above_two"])
        r["Eon"]["ordinary/X-B"]["clock"]["instructions"] = 400
        self.assertFalse(plan.outcomes(r)["above_two"])

    def test_missing_worker_or_mismatched_siblings(self):
        for key, value in (("dirty", 23), ("products", {}), ("physical", {})):
            r = rows()
            r["Don"]["ordinary/X-B"][key] = value
            with self.assertRaises(ValueError):
                plan.outcomes(r)
        r = rows()
        del r["Eon"]["ordinary/dirty-X-B"]
        with self.assertRaises(ValueError):
            plan.outcomes(r)

    def test_stale_or_missing_control(self):
        for key, value in (
            ("ordinary/dirty-X-B", "ordinary/X-B"),
            ("ordinary/comment", "empty/clean-semantic"),
        ):
            r = rows()
            r["Don"][key]["products"] = r["Don"][value]["products"]
            with self.assertRaises(ValueError):
                plan.outcomes(r)
        r = rows()
        r["Eon"]["physical/X-B"]["wild_outputs"] = ["ruff::ruff"]
        with self.assertRaises(ValueError):
            plan.outcomes(r)

    def test_real_clock(self):
        positive = dict(
            start=10,
            stop=21,
            enabled=9,
            running=9,
            instructions=30,
            event_errno=0,
            code=0,
            user_us=1,
            system_us=0,
        )
        self.assertEqual(plan.timed(positive, "X-B"), 30)
        for k, v in (
            ("instructions", 0),
            ("running", 8),
            ("code", 101),
            ("event_errno", 17),
            ("stop", 0),
        ):
            with self.assertRaises(ValueError):
                plan.timed(positive | {k: v}, "X-B")

    def test_no_subject_execution_in_kernel(self):
        q.install_boundary([{"exe": "/sdk/bin/rustc", "pid": 8}])
        for n in ("ruff", "integration_test-0abcdef012345678"):
            with self.assertRaises(ValueError):
                q.install_boundary([{"exe": "/out/" + n, "pid": 8}])

    def test_previous_boot_and_runner(self):
        old = json.loads((q.HERE / "contact-exclusions.json").read_bytes())
        self.assertGreaterEqual(len(old["boots"]), 131)
        for boot, runner in (
            (old["boots"][0], "nsc-runner-abc123"),
            ("deadbeef-0000-0000-0000-000000000000", old["runners"][0]),
        ):
            with self.assertRaises(ValueError):
                q.fresh_runner(boot, runner)

    def test_authentic_trace_lookup_layout(self):
        from tempfile import TemporaryDirectory
        from unittest.mock import Mock

        with TemporaryDirectory() as temp:
            top = Path(temp)
            lane = top / "physical"
            lane.mkdir()
            env = {"LD_LIBRARY_PATH": "/fixed/lib"}
            original = json.dumps({"arm": "Eon", "env": env}).encode()
            (top / "arm.json").write_bytes(original)
            probe = Mock()
            worker.enroll_lane(probe, "Eon", {}, top, lane, env)
            self.assertEqual((lane / "arm.json").read_bytes(), original)
            probe.catalog.assert_called_once_with("Eon", {}, lane, env)
            with self.assertRaises(ValueError):
                worker.enroll_lane(probe, "Don", {}, top, lane, env)

    def test_measured_boundary(self):
        import ast

        parsed = ast.parse((q.HERE / "contact.py").read_bytes())
        trial = next(n for n in parsed.body if getattr(n, "name", "") == "trial")
        branch = next(
            n
            for n in trial.body
            if isinstance(n, ast.If) and ast.unparse(n.test) == "counted"
        )
        texts = [ast.unparse(node) for node in branch.body]
        self.assertEqual(sum("original.invocation" in t for t in texts), 1)
        self.assertFalse(
            any(
                any(
                    word in t
                    for word in (
                        "suite.exercise",
                        "observer.invocation",
                        "donor-opens",
                        "behavior.run",
                    )
                )
                for t in texts
            )
        )
        self.assertTrue(
            any("observer.invocation" in ast.unparse(node) for node in branch.orelse)
        )
        self.assertIn("mapped_build", ast.unparse(branch))
        self.assertIn("dirty_return", ast.unparse(branch))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--enrolled")
    a = p.parse_args()
    if a.enrolled:
        q.check_source(a.enrolled)
    unittest.main(argv=[__file__])
