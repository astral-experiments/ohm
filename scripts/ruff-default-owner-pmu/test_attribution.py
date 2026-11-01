"""Exercise historical native rows and deliberate refusals without starting Rust or a PMU."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import acquire
import common as c
import instrument
import ownership
import reopen


class OptionalTagProbe(unittest.TestCase):
    def setUp(self):
        self.data = c.read(HERE / "tag-probe-fixture.json.gz")
        self.assertEqual(self.data["original_artifact_sha256"],
                         "478477d4a73271fdab470c5da3ceae5b3b3a2e0dbacf321b2f260e8390314f34")

    def examine(self, data, extra_child=False):
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp)
            (trace / "exec.tsv").write_text("\n".join(data["raw"]) + "\n")
            chain = data["chain"]
            chains = {pid: chain[index:] for index, pid in enumerate(chain)}
            if extra_child:
                chains[12] = [12, *chain]
            exits = {pid: [0, 0] for pid in chains}
            exits.update({int(pid): status for pid, status in data["nonzero"].items()})
            ownership.optional_tag_probe(Path(data["repo"]), Path(data["work"]), data["products"], data["inode"],
                                         trace, c.EXPECTED["A"], exits, data["events"], chains)

    def test_real_tagless_process(self):
        self.examine(self.data)
        self.examine(self.data | {"nonzero": {}})

    def test_unrelated_failure_still_refuses(self):
        for what in ("signal", "second", "revision", "log", "image", "script", "inode", "owner", "reexec", "child"):
            with self.subTest(what=what):
                data = copy.deepcopy(self.data)
                probe, parent, build = reversed(data["events"])
                if what == "signal":
                    data["nonzero"][str(probe["pid"])] = [143, 15]
                if what == "second":
                    data["nonzero"][str(parent["pid"])] = [128, 0]
                if what == "revision":
                    probe["argv"][-1] = c.EXPECTED["B"]
                if what == "log":
                    parent["argv"][-1] = "--format=%H"
                if what == "image":
                    probe["path"] = "/tmp/git"
                if what == "script":
                    data["products"][0]["target"]["src_path"] = "/other/build.rs"
                if what == "inode":
                    next(iter(data["inode"].values()))[1] += 1
                if what == "owner":
                    build["kind"] = 1
                if what == "reexec":
                    data["events"].append(probe)
                with self.assertRaises(ValueError):
                    self.examine(data, extra_child=what == "child")


class Census(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = c.read(HERE / "physical-fixture.json.gz")
        cls.root = Path("/home/runner/work/_temp/ohm-branch-object-qa")
        cls.work = cls.root / "work"
        cls.repo = cls.root / "ruff"

    def classify(self, fixture=None):
        f = copy.deepcopy(self.fixture) if fixture is None else fixture
        return self.run_case(f)

    def run_case(self, f):
        products = ownership.graph(f["rows"])[1]
        chains = {int(k): v for k, v in f["chains"].items()}
        events = f["events"]
        selected = {
            e["serial"]: e
            for e in events
            if (e["kind"] == 1 and "--crate-name" in e["argv"] and "--out-dir" in e["argv"])
            or (e["kind"] in (2, 4) and "-o" in e["argv"])
        }
        # These counts are synthetic; every target, output, exec, argv and
        # parent below is from the original X/B, which had no per-owner PMU.
        samples = {i: {1: 1000, 2: 800, 4: 650}[e["kind"]] for i, e in selected.items()}
        samples[0] = 24000
        return ownership.classify(
            self.repo, self.work, products, f["inodes"], events[0]["pid"], events, selected, samples, chains, chains
        )

    def test_actual_graph_and_phase_charge(self):
        x = self.classify()
        self.assertEqual(len(x["owners"]), 20)
        self.assertEqual({tuple(o["kind"]) for o in x["owners"] if o["target"] == "ruff"}, {("lib",), ("bin",)})
        (cli,) = [o for o in x["owners"] if o["links"]]
        self.assertEqual(
            (cli["target"], cli["kind"], cli["outside_cc"], cli["cc_outside_wild"], cli["wild"]),
            ("ruff", ["bin"], 200, 150, 650),
        )
        self.assertEqual(x["outside_rustcs"], 4000)

    def test_foreign_active_elf(self):
        f = copy.deepcopy(self.fixture)
        f["inodes"]["target/debug/ruff"][1] += 1
        with self.assertRaises(ValueError):
            self.classify(f)

    def test_same_name_other_crate_target(self):
        f = copy.deepcopy(self.fixture)
        (a,) = [e["argv"] for e in f["events"] if "crates/ruff/src/main.rs" in e["argv"]]
        a[a.index("crates/ruff/src/main.rs")] = "crates/ruff/src/lib.rs"
        with self.assertRaises(ValueError):
            self.classify(f)

    def test_omitted_physical_link(self):
        f = copy.deepcopy(self.fixture)
        f["events"] = [e for e in f["events"] if e["kind"] != 4]
        with self.assertRaises(ValueError):
            self.classify(f)

    def test_forged_native_output(self):
        f = copy.deepcopy(self.fixture)
        (a,) = [e["argv"] for e in f["events"] if e["kind"] == 4]
        a[a.index("-o") + 1] += ".foreign"
        with self.assertRaises(ValueError):
            self.classify(f)

    def test_nested_rustcs(self):
        f = copy.deepcopy(self.fixture)
        a, b = [e["pid"] for e in f["events"] if e["kind"] == 1 and "--out-dir" in e["argv"]][:2]
        f["chains"][str(b)].insert(1, a)
        with self.assertRaises(ValueError):
            self.classify(f)

    def test_failed_opaque_rustc(self):
        f = copy.deepcopy(self.fixture)
        source = next(e for e in f["events"] if e["kind"] == 1)
        probe = copy.deepcopy(source)
        probe.update(serial=1000, pid=123456, argv=[source["path"], "--print=cfg", "mystery.rs"])
        f["events"].append(probe)
        f["chains"]["123456"] = [probe["pid"], f["events"][0]["pid"]]
        with self.assertRaises(ValueError):
            self.classify(f)

    def test_all_seven_real_22_rustc_query_forms(self):
        entries = self.fixture["source"]["signed_release_probe"]["selected"]
        probes = [a for p, a in entries if p.endswith("/rustc")]
        self.assertEqual(len(probes), 7)
        self.assertTrue(all(ownership.rustc_query(argv) for argv in probes))
        self.assertFalse(ownership.rustc_query(probes[1] + ["--emit=metadata"]))
        self.assertFalse(ownership.rustc_query(probes[0] + ["invalid.rs"]))

    def test_signed_relay_and_foreign_identity(self):
        path, relay = next(
            (p, a)
            for p, a in self.fixture["source"]["signed_release_probe"]["selected"]
            if "ohm-declared-cc" in a[0]
        )
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for i, args in enumerate(([path, *c.CMD[2:]], relay), 1):
                (d / f"args-{i:04d}").write_bytes(("\0".join(args) + "\0").encode())
            rows = [f"1\t1\t0\t0\t9\t10\t{path}", f"2\t2\t0\t0\t9\t10\t{path}"]
            log = d / "exec.tsv"
            log.write_text("\n".join(rows) + "\n")
            ownership.signed_cargo_images(d, Path(path), [9, 10])
            for wrong in (
                rows[1].replace("\t10\t", "\t11\t"),
                rows[1].replace(path, path + ".other"),
                rows[0].replace("1\t1", "2\t2"),
            ):
                with self.subTest(wrong=wrong):
                    # The duplicate-build case uses the actual main argv on the second image.
                    if wrong == rows[0].replace("1\t1", "2\t2"):
                        (d / "args-0002").write_bytes((d / "args-0001").read_bytes())
                    log.write_text(rows[0] + "\n" + wrong + "\n")
                    with self.assertRaises(ValueError):
                        ownership.signed_cargo_images(d, Path(path), [9, 10])

    def test_protected_tree_boundaries(self):
        result = {"owners": [{"serial": 2, "links": [{"cc_serial": 3, "wild_serial": 4}]}]}
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "tasks.tsv"
            s = "exec\t10\t1\nexec\t20\t2\nspawn\t20\t21\t1\nexec\t21\t3\nexec\t22\t4\n"
            p.write_text(s)
            ownership.early_children(p.parent, result)
            for bad in ("spawn\t20\t99\t1\n" + s, s + "exec\t22\t5\n"):
                p.write_text(bad)
                with self.assertRaises(ValueError):
                    ownership.early_children(p.parent, result)

    def test_real_typed_parser_failure_and_forged_span(self):
        e = copy.deepcopy(self.fixture["errors"])
        self.assertEqual(ownership.typed(e, True)[0][:3], ["E0308", "mismatched types", c.PARSER])
        e[0]["message"]["spans"][0]["file_name"] = "crates/foreign.rs"
        with self.assertRaises(ValueError):
            ownership.typed(e, True)
        with self.assertRaises(ValueError):
            ownership.typed(self.fixture["errors"], False)

    def test_no_new_cache_or_outside_output(self):
        rows = copy.deepcopy(self.fixture["rows"])
        ownership.check_roots(rows, self.work)
        one = next(i for i in rows if i.get("reason") == "build-script-executed")
        one["out_dir"] = "/different/target/out"
        with self.assertRaises(ValueError):
            ownership.check_roots(rows, self.work)

    def test_running_equals_enabled_and_two_percent(self):
        v = dict(code=0, event_errno=0, instructions=101, enabled=500, running=500)
        self.assertEqual(instrument.clock_value(v), 101)
        for bad in (dict(running=499), dict(event_errno=1), dict(instructions=0)):
            with self.assertRaises(ValueError):
                instrument.clock_value(v | bad)
        x = reopen.thresholds([10000, 10200, 10001], {"below": 4999, "within": 5000, "above": 5100})
        self.assertTrue(x["below"]["budget"].startswith("below"))
        self.assertEqual(x["within"]["budget"], "straddles half")
        self.assertTrue(x["above"]["budget"].startswith("at least"))
        with self.assertRaises(ValueError):
            reopen.thresholds([10000, 10201, 10001], {})

    def test_complete_six_distinct_workers(self):
        now = "2026-11-01T21:00:00+00:00"
        end = "2026-11-01T17:59:59+00:00"
        prior = dict(
            id=c.PREVIOUS, head_sha=c.PREVIOUS_HEAD, run_attempt=1, event="workflow_dispatch", status="completed"
        )
        jobs = []
        arts = []
        ex = []
        for i, j in enumerate(c.BLOCKED_JOBS, 1):
            p = f"{i:02}"
            jobs.append(
                dict(
                    id=j,
                    name="GNU sorted packed Ruff CLI confirmation " + p,
                    status="completed",
                    runner_id=100 + i,
                    runner_name="old" + p,
                    completed_at=end,
                )
            )
            arts.append(
                dict(
                    id=i,
                    name="gnu-sorted-packed-ruff-cli-confirmation-" + p,
                    digest="sha256:" + format(i, "064x"),
                    size_in_bytes=1000,
                )
            )
            ex.append(dict(job=j, artifact=i, digest=arts[-1]["digest"], boot=str(uuid.UUID(int=i))))
        current = dict(id=100, head_sha="a" * 40, head_branch=c.BRANCH, event="workflow_dispatch", run_attempt=1)
        active = [
            dict(
                id=7777,
                name="Signed GNU Ruff first-A instruction owners",
                runner_name="new",
                runner_id=89898,
                started_at=now,
            )
        ]
        env = dict(
            GITHUB_RUN_ID="100",
            REVIEWED_HEAD="a" * 40,
            GITHUB_SHA="a" * 40,
            GITHUB_REPOSITORY=c.REPO,
            GITHUB_REF="refs/heads/" + c.BRANCH,
            GITHUB_RUN_ATTEMPT="1",
            GITHUB_JOB="diagnostic",
            RUNNER_NAME="new",
        )
        fresh = str(uuid.UUID(int=10))

        def check(boots=ex, job_rows=jobs, boot=fresh):
            return acquire.enrollment(prior, job_rows, arts, boots, current, active, env, boot)

        self.assertEqual(check()["boot"], fresh)
        for args in (
            dict(boot=ex[0]["boot"]),
            dict(boot=c.REFUSED["boot"]),
            dict(boots=ex[::-1]),
            dict(job_rows=[jobs[0] | dict(completed_at="2026-11-01T21:00:01+00:00"), *jobs[1:]]),
        ):
            with self.assertRaises(ValueError):
                check(**args)


if __name__ == "__main__":
    if len(sys.argv) == 3:
        collector, contract = map(Path, sys.argv[1:])
        with tempfile.TemporaryDirectory() as tmp:
            topo, pmu = instrument.compile_sources(collector.resolve(), contract.resolve(), Path(tmp) / "frozen")
            c.need(
                topo.ROLES == ("rustc", "cc", "collect2", "wild") and pmu.NESTED == (0, 2_000_000, 0, 8_000_000),
                "different physical calibration",
            )
        sys.argv[1:] = []
    unittest.main()
