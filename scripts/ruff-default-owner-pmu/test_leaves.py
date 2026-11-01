"""Compare complete, genuine old hardware records to two independent decoders, plus fail-closed mutations."""

import base64
from collections import Counter
from dataclasses import replace
from pathlib import Path
import gzip
import hashlib
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import leaf_charge as charge
import leaf_events as raw
import leaf_profile as pf
import leaf_symbols

FROZEN_FIXTURE = "8385f2f23ff09bcf53c99c67d0bc46fa0e22e3d69846d7479f2a461f449528d4"
SAMPLER = Path(sys.argv.pop(1)) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None


class LeafRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = pf.support(SAMPLER)
        fixture = HERE / "leaf-historical-fixture.json.gz"
        assert pf.c.sha(fixture) == FROZEN_FIXTURE
        cls.data = {
            k: base64.b64decode(v, validate=True)
            for k, v in json.loads(gzip.decompress(fixture.read_bytes())).items()
        }
        cls.host = json.loads(cls.data["sampling-calibration/tools.json"])["loop"]
        cls.seal = json.loads(cls.data["sampling-calibration/qualified.json"])
        cls.temp = tempfile.TemporaryDirectory()
        file = Path(cls.temp.name) / "loop"
        file.write_bytes(cls.data["counter-programs/loop"])
        assert pf.c.sha(file) == cls.host["sha256"]
        sites = cls.s.loop_sites(file)
        with leaf_symbols.Symbols(file) as elf:
            cls.sites = {elf.offset(x) for s in sites.values() for x in s}
        cls.elf = file
        cls.profiles = {}
        for label in ("child", "thread"):
            path = "sampling-calibration/" + label + "/"
            packed = cls.data[path + "perf.data.zst"]
            data = subprocess.check_output(["zstd", "-qd", "--stdout"], input=packed)
            seal = json.loads(cls.data[path + "sampling-raw.json"])
            assert (
                len(data) == seal["bytes"]
                and hashlib.sha256(data).hexdigest() == seal["raw_sha256"]
                and hashlib.sha256(packed).hexdigest() == seal["zstd_sha256"]
            )
            cls.profiles[label] = (
                data,
                raw.read(data, "retired", pf.PERIOD, explicit_period=True, historical_dwarf=True),
            )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_genuine_hardware_rows_and_loop_sites(self):
        for label, (b, rec) in self.profiles.items():
            orig = self.s.raw_report(io.BytesIO(b))[0]
            self.assertEqual(Counter((pid, tid, t, ip, w) for t, pid, tid, ip, w, _ in rec[0]), orig)
            p, tg = pf.groups(self.data["sampling-calibration/" + label + "/trace/tasks.tsv"])
            result = pf.calibration_case(
                rec, p, tg, self.host, self.sites, label, hashlib.sha256(b).hexdigest()
            )
            self.assertEqual({str(k): v for k, v in result["hot"].items()}, self.seal[label]["hot_periods"])
            self.assertEqual(result["skid"], {})
            self.assertEqual(result, json.loads(json.dumps(result)))

    def test_new_contact_refuses_legacy_dwarf(self):
        with self.assertRaisesRegex(ValueError, "unregistered"):
            raw.read(self.profiles["thread"][0], "retired", pf.PERIOD, explicit_period=True)

    def test_rebound_tool_or_period_not_hardware(self):
        b = self.profiles["child"][0]
        for kind, per in (("cpu-clock", pf.PERIOD), ("retired", pf.PERIOD - 1)):
            with self.assertRaisesRegex(ValueError, "event is not registered"):
                raw.read(b, kind, per, historical_dwarf=True)

    def test_rejected_loss_and_scope(self):
        original = self.profiles["child"][0]
        _, _, ao, _, do, _ = struct.unpack_from("<6Q", original, 8)
        for change in ("lost", "throttle", "kernel", "no_inherit"):
            b = bytearray(original)
            if change in ("lost", "throttle"):
                struct.pack_into("<I", b, do, 2 if change == "lost" else 5)
            else:
                b[ao + 40] &= ~(32 if change == "kernel" else 2)
            with self.assertRaisesRegex(ValueError, "lost|unregistered"):
                raw.read(b, "retired", pf.PERIOD, historical_dwarf=True)

    def test_real_period_and_signed_file_substitution(self):
        _, rec = self.profiles["child"]
        p, tg = pf.groups(self.data["sampling-calibration/child/trace/tasks.tsv"])
        wrong = {**self.host, "mapping_ino": self.host["mapping_ino"] + 1}
        with self.assertRaisesRegex(ValueError, "file mapping"):
            pf.calibration_case(rec, p, tg, wrong, self.sites, "child", "irrelevant")
        with self.assertRaisesRegex(ValueError, "loop instruction"):
            pf.calibration_case(rec, p, tg, self.host, {0}, "child", "irrelevant")

    def test_observer_does_not_invent_a_owner(self):
        rows, maps, *_ = self.profiles["thread"][1]
        m = next(x for x in maps if x.path == self.host["path"] and x.perm & 4)
        q = next(x for x in rows if x[5] == 2 and x[1] == m.pid and x[0] >= m.when and m.low <= x[3] < m.high)
        idx = {m.path: (m.dev, m.ino, "loop")}
        self.assertEqual(raw.named_mapping(q, [m], idx)[0], "loop")
        reserved = replace(m, perm=0, when=m.when - 1, dev=(0, 0), ino=0, path="//anon")
        self.assertEqual(raw.named_mapping(q, [reserved, m], idx)[0], "loop")
        self.assertIsNone(raw.named_mapping(q, [replace(reserved, when=m.when), m], idx)[1])
        self.assertIsNone(raw.named_mapping(q, [replace(reserved, when=q[0]), m], idx)[1])
        self.assertIsNone(raw.named_mapping(q, [m, m], idx)[1])
        self.assertIsNone(raw.named_mapping(q, [replace(m, when=q[0] + 1)], idx)[1])
        for wrong in (replace(m, ino=m.ino + 1), replace(m, perm=1)):
            with self.assertRaisesRegex(ValueError, "identity/permissions"):
                raw.named_mapping(q, [wrong], idx)

    def test_thread_lifetime_and_nonexec_leaf(self):
        rows, maps, execs, forks, exits, _ = self.profiles["thread"][1]
        pid, _ = pf.groups(self.data["sampling-calibration/thread/trace/tasks.tsv"])
        # Project the real loop's task times and mapping onto the rustc epoch gate.
        proj = [(t, p, tid, "rustc" if p == pid and tid == p else n) for t, p, tid, n in execs]
        got, _ = raw.epochs(rows, maps, proj, forks, exits, pid, self.host["path"])
        self.assertGreater(len(got), 10)
        tid = next(row[2] for row in got if row[2] != pid)
        with self.assertRaisesRegex(ValueError, "worker TID"):
            raw.epochs(rows, maps, proj, forks, [e for e in exits if e[3] != tid], pid, self.host["path"])
        with self.assertRaisesRegex(ValueError, "final rustc lifetime"):
            raw.epochs(rows, maps, proj, forks, [e for e in exits if e[3] != pid], pid, self.host["path"])
        with leaf_symbols.Symbols(self.elf) as elf:
            self.assertFalse(elf.resolve(0))
            self.assertTrue(any(elf.resolve(offs) for offs in self.sites))

    def test_complete_ordinary_owner_selector(self):
        roster = [{"key": "ruff/lib", "pid": 1}, {"key": "ruff/bin", "pid": 2}]

        def row(k, pid):
            return {"key": k, "pid": pid, "phase": {"phase": 2}, "weighted_observations": 2}

        xs = [row("ruff/lib", 1), row("ruff/bin", 2)]
        self.assertEqual(charge.cohort(xs, roster, {"ruff/lib", "ruff/bin"}), {"phase": 4})
        self.assertEqual(charge.cohort(xs, roster, {"ruff/lib"}), {"phase": 2})
        for bad in ([xs[0]], xs + xs[:1], [xs[0], row("ruff/bin", 1)]):
            with self.assertRaises(ValueError):
                charge.cohort(bad, roster, {"ruff/lib", "ruff/bin"})

    def test_strict_owner_size_and_residual(self):
        # All numbers here are synthetic tests of the scale thresholds.
        p = pf.PERIOD
        row = dict(
            samples=1000,
            weighted_observations=1000 * p,
            physical_sized_functions_weight=700 * p,
            sampled_tids=[5, 6],
            phase={},
        )
        pf.coverage(row, 1000 * p)
        for diff in (
            {"samples": 0},
            {"sampled_tids": [5]},
            {"phase": {"kernel skid": 51 * p}},
            {"physical_sized_functions_weight": 599 * p},
        ):
            with self.assertRaises(ValueError):
                pf.coverage(row | diff, 1000 * p)

    def test_distinct_symbol_scope_and_no_training_rule(self):
        self.assertEqual(
            charge.category(
                pf.LLVM,
                "driver",
                "<rustc_middle[abcd]::dep_graph::graph::DepGraphData>::try_mark_previous_green",
            ),
            "incremental graph",
        )
        self.assertEqual(
            charge.category(pf.LLVM, "driver", "<alloc::vec::Vec<rustc_monomorphize::Thing> as Trait>::drop"),
            "other signed function",
        )
        self.assertEqual(
            charge.category(pf.LLVM, "driver", "std::foo::<rustc_monomorphize::Thing>"),
            "other signed function",
        )

    def test_four_empty_tables_are_the_only_ones(self):
        import counter_members

        self.assertEqual(
            counter_members.EMPTY, {"calibration/nested-plain-%d/exec.tsv" % i for i in range(4)}
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
