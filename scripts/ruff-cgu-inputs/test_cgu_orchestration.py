"""Exercise the orchestration seams using historical real compiler vectors and adversarial receipts."""

import copy
import gzip
import hashlib
import json
import os
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("RUNNER_TEMP", tempfile.gettempdir())
import worker_cgu as run

OFFICIAL = "c67951dfc484eeb5971a01103965f841115f9658dbc80969f674fad2e10f2e4b"


class Files:
    def __init__(self):
        self.data = {}

    def read(self, name):
        return self.data[name]

    def namelist(self):
        return list(self.data)


def stage(events, physical, capture):
    # Synthetic *collector-format* fields only, from actual recorded Rust argv below.
    # CI exercises the real ptrace/auxv/selected-inode paths separately with test_capture.py.
    z = Files()
    records = []
    for seq, (pid, raw) in enumerate(events, 1):
        args = run.decoded(raw)
        owner = args[args.index("--crate-name") + 1] if "--crate-name" in args else ""
        name = f"rustc-{seq:05d}.nul"
        z.data["stage/" + name] = raw
        records.append({"seq": seq, "pid": pid, "crate": owner, "entry": name})
        if owner in run.OWNERS and "--out-dir" in args:
            base = "stage/" + owner + "/"
            z.data[base + "original.nul"] = raw
            z.data[base + "observed.nul"] = raw + ((run.FLAG.encode() + b"\0") if capture else b"")
            z.data[base + "process.json"] = json.dumps(
                {
                    "pid": pid,
                    "compiler_dev": physical[0],
                    "compiler_ino": physical[1],
                    "capture": capture,
                    "argc": [len(args), len(args) + capture],
                    "envc": [13, 13 - capture],
                    "aux_pairs": 24,
                }
            ).encode()
    z.data["stage/rustc.jsonl"] = b"".join(json.dumps(x).encode() + b"\n" for x in records)
    return z


class Orchestration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        f = run.c.read(run.a.BASE / "physical-fixture.json.gz")
        cls.products = run.w.ownership.graph(f["rows"])[1]
        cls.repo = Path("/home/runner/work/_temp/ohm-branch-object-qa/ruff")
        cls.work = cls.repo.parent / "work"
        cls.ledger = f["inodes"]
        cls.events = [
            (e["pid"], b"\0".join(a.encode() for a in e["argv"]) + b"\0")
            for e in f["events"]
            if e["kind"] == 1
        ]
        cls.rustc = [1, 2, run.decoded(cls.events[0][1])[0]]

    def recorded(self, z, mode="capture"):
        return run.recorded_roster(
            z, "stage", self.products, self.repo, self.work, self.rustc, self.ledger, mode, False
        )

    def test_real_375_unit_cargo_graph_and_20_dirty_units(self):
        self.assertEqual((len(self.products), len(run.cargo_dirty(self.products, self.repo))), (375, 20))
        products = copy.deepcopy(self.products)
        (target,) = [p for p in products if p["target"]["name"] == "ruff_linter"]
        target["fresh"] = True
        with self.assertRaisesRegex(ValueError, "20"):
            run.cargo_dirty(products, self.repo)

    def test_effective_arguments_and_physical_negative_controls(self):
        observed = self.recorded(stage(self.events, self.rustc, False), "observe")
        run.same_vectors(observed, self.recorded(stage(list(reversed(self.events)), self.rustc, True)))
        for what in ("inode", "pid", "flag", "original", "env", "entry", "orphan", "missing", "untraced"):
            with self.subTest(what=what):
                z = stage(self.events, self.rustc, True)
                b = "stage/ruff_linter/"
                p = json.loads(z.read(b + "process.json"))
                if what == "inode":
                    p["compiler_ino"] += 1
                if what == "pid":
                    p["pid"] += 1
                if what == "env":
                    p["envc"][1] += 1
                if what == "flag":
                    z.data[b + "observed.nul"] = z.read(b + "original.nul")
                if what == "original":
                    z.data[b + "original.nul"] += b"--cfg=other\0"
                if what == "entry":
                    z.data["stage/rustc.jsonl"] = z.read("stage/rustc.jsonl").replace(
                        b"rustc-00001", b"rustc-00000", 1
                    )
                if what == "orphan":
                    z.data["stage/rustc-99999.nul"] = b"orphan\0"
                if what == "missing":
                    del z.data[b + "observed.nul"]
                z.data[b + "process.json"] = json.dumps(p).encode()
                with self.assertRaises((ValueError, KeyError)):
                    self.recorded(z, "observe" if what == "untraced" else "capture")

    def test_exact_original_multiset_fails_a_consistently_resigned_other_dependency(self):
        z = stage(self.events, self.rustc, False)
        ordinary = self.recorded(z, "observe")
        changed = [(p, raw.replace(b"--extern\0", b"--renamed\0", 1)) for p, raw in self.events]
        diagnostic = self.recorded(stage(changed, self.rustc, True))
        with self.assertRaisesRegex(ValueError, "multisets"):
            run.same_vectors(ordinary, diagnostic)
        missing = ordinary.copy()
        missing.pop(next(iter(missing)))
        with self.assertRaisesRegex(ValueError, "multisets"):
            run.same_vectors(ordinary, missing)

    def test_fifteen_visits_and_independent_empties(self):
        seen = []
        empty = []

        def visit(lane, phase, *args):
            seen.append((lane, phase))

        with (
            tempfile.TemporaryDirectory() as d,
            patch.object(run.w, "OUT", Path(d)),
            patch.object(run, "visit", side_effect=visit),
            patch.object(run.w.b, "fresh_outputs", side_effect=lambda: empty.append(len(seen))),
        ):
            run.histories(None, None, None, None, None)
        self.assertEqual(len(seen), 15)
        self.assertEqual(
            [seen[i] for i in empty],
            [
                ("reference", "B"),
                ("reference", "A"),
                ("plain-1", "B"),
                ("ordinary-observed", "B"),
                ("diagnostic-empty", "B"),
                ("diagnostic-empty", "A"),
                ("diagnostic", "B"),
                ("green-reasons", "B"),
            ],
        )

    def test_visit_orders_cargo_snapshot_then_native_and_restores_env_on_refusal(self):
        for case in (
            ("ordinary-observed", "A", True),
            ("ordinary-observed", "B", False),
            ("plain-1", "A", False),
        ):
            with self.subTest(case=case):
                self.exercise_visit(*case)

    def exercise_visit(self, lane, phase, failure):
        rows = [{"reason": "build-finished", "success": True}]
        env = {"HOME": "test"}
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            (out / lane).mkdir()
            tools = out / "kit"
            capture = out / "cgu-capture"
            where = out / lane / phase
            seen = []
            cmd = [*run.c.CMD]
            if lane == "plain-1":
                cmd = [tools / "plain", where / "clock.json", *cmd]

            def invoke(folder, actual, want, sampler):
                self.assertEqual((folder, want, sampler), (where, 0, None))
                self.assertEqual(
                    actual,
                    (
                        [capture, where / "stage", run.w.b.SDK / "bin/rustc", "observe", *run.c.CMD]
                        if lane == "ordinary-observed"
                        else cmd
                    ),
                )
                self.assertEqual(
                    run.w.ENV, env | ({run.REQUEST: run.FLAG} if lane == "ordinary-observed" else {})
                )
                seen.append("Cargo")
                return rows

            class Physical:
                @staticmethod
                def assert_empty(work):
                    seen.append("before")

                @staticmethod
                def snapshot(folder, result, stage, store, work, instrumented):
                    self.assertIs(run.w.ENV, env)
                    self.assertEqual(
                        (folder, result, stage, instrumented), (where, rows, where / "stage", False)
                    )
                    seen.append("snapshot")
                    if failure:
                        raise ValueError("preserved physical refusal")

            def called(*_):
                where.mkdir()
                self.assertIs(run.w.invoke(where, cmd, 0), rows)
                self.assertIs(run.w.ENV, env)
                seen.append("native")

            with (
                patch.object(run.green_inputs, "capture", side_effect=lambda *args: seen.append("graphs-"+args[-1])),
                patch.object(run.w, "OUT", out),
                patch.object(run.w, "invoke", invoke),
                patch.object(run.w, "ENV", env),
                patch.object(run.w, "run_visit", called),
            ):
                if failure:
                    with self.assertRaisesRegex(ValueError, "physical refusal"):
                        run.visit(lane, phase, {}, tools, None, capture, out, Physical)
                else:
                    run.visit(lane, phase, {}, tools, None, capture, out, Physical)
                self.assertIs(run.w.invoke, invoke)
                self.assertIs(run.w.ENV, env)
            expected = ["before"]
            if lane == "ordinary-observed" and phase == "A":
                expected.append("graphs-before")
            expected.extend(["Cargo", "snapshot"])
            if not failure:
                if lane == "ordinary-observed":
                    expected.append("graphs-after")
                expected.append("native")
            self.assertEqual(seen, expected)

    def test_sources_and_credential_boundaries(self):
        run.a.verify_inherited_sources()
        t = (HERE.parents[1] / ".github/workflows/ci.yml").read_text()
        self.assertIn(run.a.BRANCH, t)
        self.assertEqual(t.count("persist-credentials: false"), 3)
        self.assertEqual(t.count("${{ github.token }}"), 1)
        self.assertIn("timeout-minutes: 120", t)
        self.assertNotIn("GH_TOKEN", t[t.index("      - name: Run the ordinary") :])
        self.assertNotIn("write", t)
        for key in (*run.FORBIDDEN, run.REQUEST, "CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                run.ordinary_env({key: ""})

    def test_fresh_enrollment_rejections(self):
        # An altered physical boot in the six inputs must be refused even if it is a valid UUID.
        with self.assertRaisesRegex(ValueError, "six"):
            run.a.check_fresh({}, [{"boot": "5ccbe1fd-0a0a-49b5-9ff8-e8c1e14e405d"}])
        with patch.object(run.a, "SIX_DIGEST", hashlib.sha256(b"[]").hexdigest()):
            state = {
                "run": 1,
                "job": 2,
                "runner_id": 3,
                "runner": "new",
                "boot": "unused",
                "started": "2026-11-02T00:00:00Z",
            }
            self.assertEqual(run.a.check_fresh(state, []), state)
            for prior in run.a.PRIOR:
                for index, key in enumerate(("run", "job", "runner_id", "runner", "boot")):
                    with (
                        self.subTest(worker=prior[0], key=key),
                        self.assertRaisesRegex(ValueError, "repeated"),
                    ):
                        run.a.check_fresh(state | {key: prior[index]}, [])


def original(path, collector, contract):
    """Rehearse on the previous signed first-A's actual Cargo/PMU/argv/inode and clean ELF originals."""
    assert path.stat().st_size == 86736376 and run.c.sha(path) == OFFICIAL
    root = Path("/home/runner/work/_temp/ohm-branch-object-qa")
    old = run.module("signed_first_a_reopen", run.a.BASE / "reopen.py")
    with ZipFile(path) as z:
        selector = old.record(z, "selectors.json")["rustc"]
        with tempfile.TemporaryDirectory(prefix="historic-cgu-clock-") as tmp:
            temp = Path(tmp)
            _, pmu = run.w.instrument.compile_sources(collector, contract, temp / "source")
            old.bounded_files(z, temp)
            calibration = pmu.calibration(temp / "counter-programs", temp, replay=True)
        ordinary_count = run.w.instrument.clock_value(old.record(z, "plain-1/A/clock.json"))
        result = {}
        for b in "AB":
            reference = old.replay_native.native_verdict(z, "reference/" + b, b)
            for role, crate in [("cli", "ruff"), ("reader", "ohm_branch_reader")]:
                e = reference[role]
                old.replay_elf.verify(z, "native-bodies/" + e["whole"] + ".zst", e, crate)
            for lane in ("plain-1", "attributed", "plain-2"):
                x = lane + "/" + b
                rows = [json.loads(v) for v in gzip.decompress(z.read(x + "/cargo.stdout.gz")).splitlines()]
                graph, products = run.w.ownership.graph(rows)
                run.w.ownership.check_roots(rows, root / "work")
                assert (
                    graph == old.record(z, x + "/roster.json.gz")
                    and old.replay_native.native_verdict(z, x, b) == reference
                )
                old.actual_externs(z, x, products, root)
                if b == "A":
                    result[lane] = run.cargo_dirty(products, root / "ruff")
        assert (
            result["plain-1"] == result["attributed"] == result["plain-2"] and len(result["attributed"]) == 20
        )
        p = "attributed/A"
        products = run.w.ownership.graph(
            [json.loads(x) for x in gzip.decompress(z.read(p + "/cargo.stdout.gz")).splitlines()]
        )[1]
        records = []
        for row in z.read(p + "/trace/exec.tsv").decode().splitlines():
            serial, pid, _, _, dev, ino, image = row.split("\t")
            if image == selector[2]:
                assert [int(dev), int(ino)] == selector[:2]
                records.append((int(pid), z.read(f"{p}/trace/args-{int(serial):04d}")))
        vectors = []
        for mode in ("observe", "capture"):
            k = stage(records, selector, mode == "capture")
            vectors.append(
                run.recorded_roster(
                    k,
                    "stage",
                    products,
                    root / "ruff",
                    root / "work",
                    selector,
                    old.record(z, p + "/path-inodes.json.gz"),
                    mode,
                    True,
                )
            )
        run.same_vectors(*vectors)
        assert vectors[0] == Counter(v for _, v in records)
        print(
            json.dumps(
                {
                    "original": OFFICIAL,
                    "actual_first_A_physical_rustcs": len(records),
                    "dirty_Cargo": 20,
                    "actual_clean_elfs": 4,
                    "actual_ordinary_instructions": ordinary_count,
                    "actual_calibration_sha256": hashlib.sha256(
                        z.read("calibration/admitted.json")
                    ).hexdigest(),
                    "actual_calibrated_modes": sorted(calibration["whole28"]),
                    "synthetic_new_control_format": True,
                    "physical_original_argument_hashes": sorted(
                        hashlib.sha256(v).hexdigest() for _, v in records
                    ),
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    if sys.argv[1:2] == ["--original"] and len(sys.argv) == 5:
        original(*(Path(p).resolve(strict=True) for p in sys.argv[2:]))
    else:
        unittest.main()
