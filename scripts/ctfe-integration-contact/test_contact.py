"""Check the actual entry points, old physical integration controls and fail-closed contract."""

import argparse
import ast
import gzip
import hashlib
import json
from pathlib import Path
import sys
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as q
import reopen_contact as replay


class Contract(unittest.TestCase):
    def test_source_constants(self):
        self.assertEqual(len(q.PHASES), len(set(q.PHASES)))
        self.assertEqual(q.PHASES, q.EMPTY + q.HISTORY)
        self.assertEqual(len(q.ARMS) * (len(q.PHASES) + 2), 24)
        self.assertEqual(sum(p != "invalid" for p in q.PHASES) * len(q.ARMS), 18)
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
        self.assertEqual(q.reference("X-A"), "clean-A")
        self.assertEqual(q.reference("repair"), "clean-edited")
        with self.assertRaises(ValueError):
            q.reference("invalid")

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

    def test_selection_is_counterbalanced_at_future_pilot_only(self):
        def entry(full, links):
            return {"comment": {"physical": {"full": full}, "wild_outputs": links}}

        x = ["ruff_python_ast", "lib", False]
        y = ["index", "lib", False]
        e = entry([x, y], ["integration_test::integration_test", "ruff::ruff"])
        c = entry([x], ["ruff::ruff"])

        def check(a, b):
            return q.structural({"Eon": a, "Con": b})["eligible"]

        self.assertTrue(check(e, c))
        self.assertFalse(check(e, e))
        self.assertFalse(check(e, entry([x, ["index", "bin", False]], [])))
        self.assertFalse(check(e, entry([x], ["other_crate::ruff"])))
        with self.assertRaises(ValueError):
            check(e, entry([y], []))

    def test_positive_link_identity(self):
        full = dict(event=91, crate="integration_test", mode="full", argv=["rustc", "--test"])
        only = dict(event=101, crate="ruff", mode="link-only", argv=["rustc", "-Zlink-only"])
        raw = {
            "rustcs": [full, only],
            "wild_processes": [
                dict(output="/a/integration_test-12345678abcdef90", rustc_event=91),
                dict(output="/b/ruff", rustc_event=101),
            ],
        }
        self.assertEqual(q.link_outputs(raw), ["integration_test::integration_test", "ruff::ruff"])
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
        working = s.REFERENCE["diagnostic"] | {"filename": str(PurePosixPath("/ruff/dev_loop.pyi"))}
        self.assertTrue(s.verdict("pyi", False, 1, json.dumps([working]).encode(), b"", "/ruff"))
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
        import contact_review

        self.assertEqual(Path(h.__file__).parent, ctfe / "scripts/ctfe-crossover-pilot")
        self.assertEqual(h.subjects.policy().b, h.b)
        self.assertEqual(h.original.CARGO, q.BUILD)
        self.assertEqual(h.reg.OBSERVER, q.KERNEL)
        self.assertEqual(n.CARGO, q.BUILD)
        self.assertEqual(
            h.reg.READER,
            q.sha((ctfe / "scripts/ctfe-crossover-pilot/kernel-review/read_events.py").read_bytes()),
        )

    def test_anchored_core_and_out_of_window(self):
        for file in q.HERE.glob("*.py"):
            ast.parse(file.read_bytes(), filename=str(file))
        w = (q.HERE.parents[1] / ".github/workflows/ci.yml").read_text()
        for v in (q.BRANCH, q.CTFE, q.F_HEAD, q.KERNEL, "0b50022990577aadd904731e51c4d6c2a0f9b665"):
            self.assertIn(v, w)
        self.assertEqual(w.count("GH_TOKEN:"), 1)
        self.assertEqual(w.count("actions/checkout@"), w.count("persist-credentials: false"))
        self.assertNotIn("pull_request:", w)
        self.assertNotIn("meter.py", w)
        self.assertNotIn("CARGO_UNSTABLE_OHM_", w)


def previous(archive):
    """Use authentic archived F test executions; none are scored here."""
    _, sel, suite = q.packages()
    import pilot as common
    import reopen as native

    with archive.open("rb") as f:
        q.need(
            hashlib.file_digest(f, "sha256").hexdigest()
            == "cbe8a61f3efdb85a06ed0de95ce05649c1dfebe3402b89afd6582de68c491bb3",
            "wrong earlier structural ZIP",
        )
    with zipfile.ZipFile(archive) as z:

        def D(p):
            return json.loads(gzip.decompress(z.read(p)) if p.endswith(".gz") else z.read(p))

        key = "clean/Fon/B"
        cmd = D(key + "/cargo.json.gz")
        root = Path(cmd["cwd"]).parent

        def info(arm, phase):
            p = arm + "/" + phase
            cert = D(arm + "/arm.json")
            cmd, events = replay.cargo(z, p, root, cert, 101 if phase == "invalid" else 0)
            members, dirty = sel.roster(events, Path(cmd["cwd"]))
            q.need(
                D(p + "/roster.json.gz") == dict(units=members, dirty=dirty),
                "changed original F typed graph",
            )
            return cmd, events

        cases = 0
        for arm in ("Foff", "Fon"):
            for group, phases in [
                ("clean", ("A", "B")),
                ("history", ("cold-A", "return-A", "return-B", "invalid", "repair")),
            ]:
                for phase in phases:
                    top = group + "/" + arm
                    p = top + "/" + phase
                    cmd, events = info(top, phase)
                    if phase == "invalid":
                        continue
                    r = D(p + "/visit.json")
                    imgs = native.replay_native.native_verdict(z, p, r["state"])
                    paths = {
                        ("harness" if m["target"]["kind"] == ["test"] else "cli"): m["executable"]
                        for m in events
                        if m["reason"] == "compiler-artifact" and m["executable"]
                    }
                    pref = D("initial/eacces.json")["argv"]
                    pref = pref[: pref.index("--") + 1] if pref[:1] == ["setpriv"] else []
                    v = replay.full_suite(z, p, paths, cmd["cwd"], suite, common.original.processes, pref)
                    q.need(
                        len(v["names"]) == 96 and imgs["source"] in native.metrics.REVS.values(),
                        "wrong real old suite",
                    )
                    cases += 1

        class Mutant:
            def __init__(self, which, data):
                self.which, self.data = which, data

            def read(self, n):
                return self.data if n == self.which else z.read(n)

        paths = {
            ("harness" if m["target"]["kind"] == ["test"] else "cli"): m["executable"]
            for m in events
            if m["reason"] == "compiler-artifact" and m["executable"]
        }
        for member, content in [
            ("libtest-list.stdout.gz", gzip.compress(b"0 tests\n")),
            ("dev-rule.stdout.gz", gzip.compress(b"wrong")),
            ("check_input_from_argfile.exec.gz", gzip.compress(b"")),
        ]:
            try:
                replay.full_suite(
                    Mutant(p + "/" + member, content),
                    p,
                    paths,
                    cmd["cwd"],
                    suite,
                    common.original.processes,
                    pref,
                )
            except (KeyError, ValueError):
                pass
            else:
                raise ValueError("accepted corrupt native evidence " + member)
        platform_links = 0
        for entry in z.namelist():
            if entry.endswith("native-execs.json.gz"):
                for ld in D(entry)["other_linkers"]:
                    native.kernel.system_link(ld["argv"])
                    platform_links += 1
        q.need(platform_links == 372, "not all 18 physical inherited configurator sets were audited")
        print(
            "old structure ZIP: 14 real Cargo streams,",
            cases,
            "complete 96-case suites, two invalids,",
            platform_links,
            "actual system ld calls and three genuine artifact mutations",
        )


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--enrolled")
    a.add_argument("--previous", type=Path)
    args = a.parse_args()
    if args.enrolled:
        q.check_source(args.enrolled)
    raw = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(Contract)
    )
    if not raw.wasSuccessful():
        sys.exit(1)
    if args.previous:
        previous(args.previous)
