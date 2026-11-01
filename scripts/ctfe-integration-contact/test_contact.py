"""Applicable regression controls retained from the earlier real 96-test contact."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as q


class Contract(unittest.TestCase):
    def test_forbidden_real_execution(self):
        for path in (
            "/actual/ruff",
            "/actual/integration_test",
            "/actual/integration_test-0123456789abcdef",
            "/actual/ruff-0123456789abcdef",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                q.install_boundary([{"pid": 17, "exe": path}])
        q.install_boundary(
            [
                {"pid": 42, "exe": "/work/ruff-01234/build-script-build"},
                {"pid": 99, "exe": "/sdk/bin/rustc"},
            ]
        )

    def test_positive_link_identity(self):
        full = dict(
            event=91, crate="integration_test", mode="full", argv=["rustc", "--test"]
        )
        only = dict(
            event=101, crate="ruff", mode="link-only", argv=["rustc", "-Zlink-only"]
        )
        raw = {
            "rustcs": [full, only],
            "wild_processes": [
                dict(output="/a/integration_test-12345678abcdef90", rustc_event=91),
                dict(output="/b/ruff", rustc_event=101),
            ],
        }
        self.assertEqual(
            q.link_outputs(raw), ["integration_test::integration_test", "ruff::ruff"]
        )
        self.assertEqual(
            q.identities(raw),
            dict(
                full=[["integration_test", "<implicit>", True]],
                link_only=["ruff"],
                wild=[["integration_test", "<implicit>"], ["ruff", "<implicit>"]],
            ),
        )
        raw["wild_processes"][0]["rustc_event"] = 1
        with self.assertRaises(KeyError):
            q.link_outputs(raw)

    def test_known_arms_excluded(self):
        j = json.loads((q.HERE / "excluded-boots.json").read_bytes())
        self.assertEqual(len(j["F-integration-confirm"]["boots"]), 12)
        self.assertEqual(len(j["E-12"]["boots"]), 12)
        for v in j.values():
            for boot in v["boots"]:
                with self.assertRaises(ValueError):
                    q.excluded_boot(boot)
        with self.assertRaises(ValueError):
            q.excluded_boot("x")

    def test_real_pinned_modules(self):
        ctfe, selection, suite = q.packages()
        s = q.semantics()
        from pathlib import PurePosixPath

        for key in ("py", "pyi", "qno", "qno-as-pyi", "pyi-as-py"):
            self.assertEqual(s.argv(key)[0], "check")
        working = s.REFERENCE["diagnostic"] | {
            "filename": str(PurePosixPath("/ruff/dev_loop.pyi"))
        }
        self.assertTrue(
            s.verdict("pyi", False, 1, json.dumps([working]).encode(), b"", "/ruff")
        )
        with self.assertRaises(ValueError):
            s.verdict("pyi", True, 1, json.dumps([working]).encode(), b"", "/ruff")
        with self.assertRaises(ValueError):
            s.altered(b'"pyi" => Self::Stub,')
        data = Path(suite.__file__).with_name("expected-tests.txt").read_bytes()
        self.assertEqual(len(suite.inventory(data)), 96)
        with self.assertRaises(ValueError):
            suite.inventory(data.split(b"\n", 1)[1])
        import pilot as h
        import reopen as n

        self.assertEqual(Path(h.__file__).parent, ctfe / "scripts/ctfe-crossover-pilot")
        self.assertEqual(h.subjects.policy().b, h.b)
        self.assertEqual(h.original.CARGO, q.BUILD)
        self.assertEqual(h.reg.OBSERVER, q.KERNEL)
        self.assertEqual(n.CARGO, q.BUILD)
        self.assertEqual(
            h.reg.READER,
            q.sha(
                (
                    ctfe / "scripts/ctfe-crossover-pilot/kernel-review/read_events.py"
                ).read_bytes()
            ),
        )


if __name__ == "__main__":
    unittest.main()
