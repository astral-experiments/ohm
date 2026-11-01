"""Offline enrollment and counterexample controls; no hardware, Rust build, or network."""

import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import zlib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("RUNNER_TEMP", tempfile.gettempdir())
import check_metadata, experiment, guards, overlay, placement, protocol as P, reopen, roles, source_binding
import session_tables as tables


def case():
    rows = {r: {p: (301 if r == "Roff" else 100) for p in P.MAIN + P.ORDINARY} for r in P.ROLES}
    storage = {
        r: {"first-B": 1024 * P.M, "repair": 1024 * P.M + (256 * P.M if r == "Eon" else 0)} for r in P.ROLES
    }
    vals = {
        "allocated_including_deleted_peak": 2048 * P.M,
        "pss_peak": 800 * P.M,
        "rss_peak": 900 * P.M,
        "pss_anon_peak": 700 * P.M,
        "all_deleted_mappings_accounted": True,
        "max_working_table_pairs_observed": 1,
    }
    peaks = {r: {p: dict(vals) for p in ("repair", "private-UP035-B")} for r in P.PEAK_ROLES}
    return rows, storage, peaks


class Decision(unittest.TestCase):
    def test_registered_pass(self):
        at = P.final(*case())
        self.assertTrue(at["passed"])
        self.assertEqual(
            P.MAIN[P.MAIN.index("adjacent-repair") + 1 : P.MAIN.index("private-repeat-B")],
            ("adjacent-unchanged-B", "private-UP035-B"),
        )
        self.assertEqual(P.PEAK[P.PEAK.index("repair") + 1], "private-UP035-B")

    def test_early_bounds_and_missing_observation(self):
        for name in ("unchanged-B", "adjacent-invalid", "adjacent-invalid-repeat", "single-source-B"):
            rows, *_ = case()
            rows["Ron"][name] = 103
            self.assertFalse(P.early(rows)[name]["passed"])
        rows, *_ = case()
        rows["Ron"]["repair"] = 110
        self.assertTrue(P.early(rows)["repair"]["passed"])
        rows["Ron"]["repair"] = 111
        self.assertFalse(P.early(rows)["repair"]["passed"])
        del rows["Eon"]["invalid"]
        with self.assertRaises(ValueError):
            P.early(rows)

    def test_each_return_and_storage(self):
        for phase in P.RETURNS:
            r, d, h = case()
            r["Roff"][phase] = 2 * r["Ron"][phase]
            self.assertFalse(P.final(r, d, h)["passed"])
        r, d, h = case()
        d["Ron"]["repair"] = d["Roff"]["repair"] + 33 * P.M
        self.assertFalse(P.final(r, d, h)["passed"])

    def test_observed_lower_bounds_and_coverage(self):
        for reason in ("unresolved", "unavailable", "no overlap", "delta"):
            r, d, h = case()
            p = h["Ron"]["repair"]
            if reason == "unresolved":
                p["all_deleted_mappings_accounted"] = False
            if reason == "unavailable":
                h["Ron"]["repair"] = None
            if reason == "no overlap":
                p["max_working_table_pairs_observed"] = 0
            if reason == "delta":
                p["allocated_including_deleted_peak"] += 161 * P.M
            self.assertFalse(P.final(r, d, h)["passed"], reason)

    def test_process_counter_no_multiplex(self):
        raw = dict(
            start=123,
            stop=200,
            user_us=52,
            system_us=2,
            instructions=103,
            enabled=22,
            running=22,
            event_errno=0,
            code=101,
        )
        self.assertEqual(reopen.hardware(raw, 101), 103)
        for altered in (raw | {"running": 21}, raw | {"code": 0}, raw | {"instructions": 0}):
            with self.assertRaises(ValueError):
                reopen.hardware(altered, 101)

    def test_live_floors(self):
        s = {"work": 4 * guards.G, "receipts": 6 * guards.G, "effective": 8 * guards.G}
        guards.admit(s)
        for k in s:
            with self.assertRaises(RuntimeError):
                guards.admit(s | {k: s[k] - 1})


class Inputs(unittest.TestCase):
    def test_registered_source_and_workflow(self):
        d = json.loads((HERE / "inputs/product.json").read_bytes())
        history = json.loads((HERE / "inputs/previous.json").read_bytes())
        self.assertEqual(set(d["blobs"]), source_binding.EXPECTED)
        self.assertEqual(
            hashlib.sha256((HERE / "inputs/writer.pack").read_bytes()).hexdigest(), source_binding.PACK
        )
        self.assertEqual(len(history["sessions"]), 12)
        self.assertEqual(len(set(history["old_excluded_boots"])), 78)
        yaml = (HERE.parent.parent / ".github/workflows/ci.yml").read_text()
        for ref in (
            "inputs.reviewed_head == github.sha",
            "github.run_attempt == '1'",
            "fetch-depth: 2",
            " .github/workflows",
            "actions: read",
            "contents: read",
            source_binding.REF,
            "if: always()",
        ):
            self.assertIn(ref, yaml)
        self.assertNotIn("pull_request_target", yaml)
        self.assertTrue((HERE / "PLAN.md").is_file())
        self.assertEqual(
            experiment.visits.w.b.CARGO_ELF,
            "035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4",
        )

    def test_real_profile_rows_distinguish_host_and_target(self):
        plan = json.loads((HERE / "inputs/real-check-plan.json").read_bytes())
        self.assertEqual(
            (plan["units"], plan["modes"]), (412, {"build": 115, "check": 260, "run-custom-build": 37})
        )
        self.assertEqual(plan["sha"], "21371ade90a7d0bca17b0994329ac765ba5335fa77afb8c7ce6d9a20c158cf84")
        self.assertEqual(len(plan["rows"]), 7)
        art = []
        for r in plan["rows"]:
            pf = {
                k: r["profile"][k] for k in ("opt_level", "debuginfo", "debug_assertions", "overflow_checks")
            } | {"test": False}
            stem = "/example/lib" + r["crate"] + "-" + ("a" * 16 if r["mode"] == "check" else "b" * 16)
            art.append(
                dict(
                    target={"name": r["crate"], "kind": ["lib"]},
                    profile=pf,
                    features=r["features"],
                    filenames=[stem + ".rmeta"] + ([stem + ".rlib"] if r["mode"] == "build" else []),
                    executable=None,
                )
            )
        art.append(dict(target={"name": "ruff", "kind": ["bin"]}, profile=art[0]["profile"]))
        for n in check_metadata.PROVIDERS:
            self.assertEqual(
                check_metadata.target_provider(art, n)[0].name, "lib" + n + "-" + "a" * 16 + ".rmeta"
            )
            for tag, row in [(True, check_metadata.APIS[n][0]), (False, check_metadata.APIS[n][1])]:
                program = check_metadata.client_source(row, check_metadata.APIS[n][2])
                self.assertEqual(len(program.splitlines()), 3)
                self.assertNotIn("\\n", program)
                self.assertTrue(program.endswith("}\n"))
        for n in ("ruff_source_file", "ruff_text_size"):
            bad = [
                m
                for m in art
                if not (m["target"]["name"] == n and m.get("profile", {}).get("opt_level") == "1")
            ]
            with self.assertRaises(ValueError):
                check_metadata.target_provider(bad, n)

    def test_cross_compiler_and_off(self):
        r = {
            "providers": {n: {"sha256": "d", "listing": "a"} for n in check_metadata.PROVIDERS},
            "typed": {
                n + "-" + k: [i, "out", "err"]
                for n in check_metadata.PROVIDERS
                for k, i in (("accepted", 0), ("refused", 1))
            },
        }
        q = copy.deepcopy(r)
        q["providers"]["ruff_linter"]["listing"] = "different"
        out = check_metadata.cross(r, q)
        self.assertFalse(out["complete_byte_and_listing_equality"])
        self.assertEqual(set(out["differences"]), {"ruff_linter"})
        with self.assertRaises(ValueError):
            check_metadata.equivalent(r, q)
        del q["typed"]["ruff_linter-refused"]
        with self.assertRaises(ValueError):
            check_metadata.cross(r, q)

    def test_paths_and_foreign_role(self):
        with tempfile.TemporaryDirectory() as t:
            q = Path(t)
            (q / "target").mkdir()
            (q / "build").mkdir()
            (q / "build/out").mkdir()
            f = q / "target/lib.rlib"
            f.write_bytes(b"ok")
            row = dict(
                reason="compiler-artifact",
                target={"kind": ["lib"], "name": "qa"},
                profile={},
                features=[],
                package_id="id",
                filenames=[str(f)],
                executable=None,
            )
            script = dict(reason="build-script-executed", package_id="id", out_dir=str(q / "build/out"))
            got = roles.artifacts([row, script], q, q)
            self.assertEqual(got["units"][0][5], ["target/lib.rlib"])
            f.rename(q / "build/lib.rlib")
            row["filenames"] = [str(q / "build/lib.rlib")]
            self.assertNotEqual(got, roles.artifacts([row, script], q, q))
            f.symlink_to(q / "build/lib.rlib")
            row["filenames"] = [str(f)]
            with self.assertRaises(ValueError):
                roles.artifacts([row, script], q, q)

    def test_prior_two_opened_streams_and_lock(self):
        base = Path("/tmp/owned")
        own = "target/debug/incremental/tool-123"
        stem = "s-aa-_0000000000000000_d"
        last = stem + "-b"
        files = [str(base / own / last / ("ohm-packed-" + n)) for n in placement.GRAPH]
        lock = str(base / own / (stem + ".lock"))
        prev = {"latest": last, "streams": {f: {"path": f} for f in files}}
        lines = [
            f"12 flock(8<{lock}>, LOCK_SH|LOCK_NB <unfinished ...>",
            f"12 <... flock resumed>) = 0",
            f'42 openat(AT_FDCWD, "{files[0]}", O_RDONLY <unfinished ...>',
            f"42 <... openat resumed>) = 3<{files[0]}>",
            f'43 openat(AT_FDCWD, "{files[1]}", O_RDONLY) = 4<{files[1]}>',
        ]
        self.assertEqual(
            set(placement.positive_read(placement.returned(lines), prev, base, own)["opened"]), set(files)
        )
        for bad in ([*lines[:-1]], lines[1:], lines[:-2] + [lines[-1]]):
            with self.assertRaises(ValueError):
                placement.positive_read(placement.returned(bad), prev, base, own)

    def test_independent_check_and_raw_shadow(self):
        with tempfile.TemporaryDirectory() as t:
            at = Path(t) / "s-1-_0123456789abcdef_2-3"
            at.mkdir()
            prefix = at.name.rsplit("-", 1)[0].encode()
            ver = "qualification"
            header = tables.raw_header(ver)
            raw = header + bytes(75000)
            (at / "foo.o").write_bytes(b"object")
            (at / "work-products.bin").write_bytes(header + b"work")
            for name, tag in tables.TABLES:
                encoded = b"\x01" + tag + b"\x03" + len(raw).to_bytes(8, "little") + prefix + b"\0" + raw
                (at / ("ohm-packed-" + name)).write_bytes(zlib.compress(encoded))
                (at / ("ohm-check-" + name)).write_bytes(header + b"independent check")
            info = placement.fresh_body(at, {"actual": "packed"}, ver, tables)
            self.assertEqual(len(info["independent_stage_tables"]), 2)
            (at / "ohm-build-dep-graph.bin").write_bytes(raw)
            with self.assertRaises(ValueError):
                placement.fresh_body(at, {"actual": "packed"}, ver, tables)

    def test_only_changed_native_overlay(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            p = root / "E"
            r = root / "R"
            p.mkdir()
            r.mkdir()
            (p / "lib").mkdir()
            (r / "lib").mkdir()
            driver = "lib/librustc_driver-a.so"
            first = {}
            second = {}
            for name in [driver] + [f"member-{i:03}" for i in range(80)]:
                for d, table, text in [
                    (p, first, b"original"),
                    (r, second, b"fixed" if name == driver else b"original"),
                ]:
                    f = d / name
                    f.write_bytes(text)
                    table[name] = [overlay.sha(f), len(text), stat.S_IMODE(f.stat().st_mode)]
            folder = root / "overlay"
            overlay.archive(folder, r, first, second, driver)
            self.assertEqual({p.name for p in folder.iterdir()}, {"manifest.json", "0.zst"})

            def rec(d):
                return {"files": {n: [s, 0, 0, m, l, 0, 0] for n, (s, l, m) in d.items()}, "driver": driver}

            log = root / "logs"
            (log / "sdk").mkdir(parents=True)
            for n, table in (("E", first), ("R", second)):
                (log / "sdk" / (n + ".json")).write_text(json.dumps(rec(table)))
            overlay.restore(folder, log, p, root / "reconstructed")
            self.assertEqual(overlay.sha(root / "reconstructed" / driver), second[driver][0])
            (folder / "0.zst").write_bytes(b"wrong")
            with self.assertRaises(ValueError):
                overlay.verify(folder, first, second, driver)


if __name__ == "__main__":
    unittest.main(verbosity=2)
