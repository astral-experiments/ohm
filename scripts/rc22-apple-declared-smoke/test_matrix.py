import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import acquire
import fixture
import matrix


class Protocol(unittest.TestCase):
    def test_exact_scripts(self):
        for f, key in [(fixture.BASE, "original_smoke"), (fixture.PUBLISHED, "corrected_smoke")]:
            ref = matrix.REG[key]
            self.assertEqual(acquire.sha(f), ref["sha256"])
            self.assertEqual(
                subprocess.check_output(["git", "hash-object", f]).decode().strip(), ref["blob"]
            )
            subprocess.run(["bash", "-n", f], check=True)
        self.assertEqual(matrix.REG["corrected_smoke"]["cargo"], acquire.READERS["fourfix"])

    def test_declared_unmarked_changes_only_rust(self):
        a, b = fixture.sources("A"), fixture.sources("B")
        self.assertEqual(set(a), set(b))
        self.assertEqual([k for k in a if a[k] != b[k]], ["engine/src/lib.rs"])
        self.assertIn('core::arch::asm!("/* {0} */", in(reg) value', a["engine/src/lib.rs"])
        self.assertNotIn("asm!", b["engine/src/lib.rs"])
        self.assertEqual(fixture.sources("C"), a)

    def test_unwatched_only_changes_declaration(self):
        a, u = fixture.sources("A"), fixture.sources("U")
        self.assertEqual(fixture.sources("U-legacy"), u)
        self.assertEqual([k for k in a if a[k] != u[k]], ["build.rs"])
        self.assertIn("rerun-if-changed=build.rs", u["build.rs"])
        self.assertIn("cargo::rustc-link-search=native={dir}/native", u["build.rs"])
        self.assertIn("cargo::rustc-link-lib=static=answer", u["build.rs"])
        self.assertEqual(u["src/bin/first.rs"], u["src/bin/second.rs"])

    def test_enrolled_graph(self):
        self.assertEqual(set(matrix.REG["readers"]), set(acquire.READERS))
        self.assertEqual(matrix.REG["readers"]["fourfix"][0], "actual-corrected-script")
        self.assertEqual(set(matrix.REG["readers"]["packaged"]), {"A", "B", "C", "U"})
        self.assertEqual(matrix.REG["readers"]["old328"], ["U-legacy"])
        self.assertEqual(sum(map(len, matrix.REG["readers"].values())), 10)
        self.assertEqual(len(set(fixture.SCHEDULE)), 10)
        self.assertEqual(set(v for _, v in fixture.SCHEDULE), set(fixture.STATES))

    def test_same_inode_backdated_valid_malformed_and_repaired(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            p = d / "native"
            providers = d / "providers"
            for n in (17, 29, 37):
                f = providers / str(n) / "libanswer.a"
                f.parent.mkdir(parents=True)
                f.write_bytes(bytes([n]) * 128)
            with patch.object(fixture, "PROVIDERS", providers):
                a = fixture.put(p, 17, False)
                b = fixture.put(p, 29, True)
                bad = fixture.put(p, "malformed", True)
                self.assertEqual(len({a["sha256"], b["sha256"], bad["sha256"]}), 3)
                self.assertTrue(all(a[k] == b[k] == bad[k] for k in ("dev", "ino", "mtime_ns", "bytes")))
                self.assertFalse(fixture.put(p, "missing", True)["exists"])
                self.assertFalse(p.exists())
                self.assertEqual(
                    fixture.put(p, 37, True)["sha256"], acquire.sha(providers / "37/libanswer.a")
                )

    def test_scoped_output(self):
        roots = [Path("/subject/target"), Path("/subject/build")]
        self.assertEqual(fixture.bin_id("/subject/target/foo/second", roots), "second")
        self.assertEqual(fixture.bin_id("/subject/build/first-1234567890abcdef", roots), "first")
        for f in (
            "/subject-other/target/first",
            "/subject/target/build_script_build",
            "first",
            "/subject/target/first-fab",
        ):
            self.assertIsNone(fixture.bin_id(f, roots))

    def test_physical_driver_and_actual_tool_join(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)
            cargo = p / "cargo"
            ld = p / "ld"
            rustc = p / "rustc"
            clang = p / "clang"
            alias = p / "ld-alias"
            provider = p / "native"
            for f in (cargo, ld, rustc, clang):
                f.write_bytes(f.name.encode())
            os.link(ld, alias)

            def row(idx, prog, *args):
                return dict(
                    pid=idx + 21, ppid=20, seq=100 + idx, path=str(prog), argv=[str(prog), *args]
                )

            c = row(1, cargo, "build", "--bins", "--offline")
            middle = row(2, rustc, "-Z", "link-only", "first.rlink")
            out = p / "target/first"
            l = row(3, alias, "-L", str(provider), "-lanswer", "-o", str(out))
            middle["ppid"] = c["pid"]
            l["ppid"] = middle["pid"]
            rows = [c, middle, l]
            roots = [p / "target"]
            args = (cargo, rustc, ld, roots, provider)
            z = matrix.classify(rows, *args)
            self.assertEqual(
                z["final"]["first"],
                l | {"rustc_parent_pid": middle["pid"], "cargo_ancestor_pid": c["pid"]},
            )
            self.assertEqual(z["rustc"], [middle])
            self.assertFalse(matrix.classify(rows[:2] + [row(3, clang, *l["argv"][1:])], *args)["final"])
            for bad in (
                rows[1:],
                rows + [row(4, ld, *l["argv"][1:])],
                [c, middle, row(3, ld, "-L/foreign", "-lanswer", "-o", str(out))],
                [c, middle, row(3, ld, "-L", str(provider), "-o", str(out))],
            ):
                with self.assertRaises(ValueError):
                    matrix.classify(bad, *args)

    def test_independent_actual_errors(self):
        self.assertTrue(fixture.projected_errors("ld: library 'answer' not found", "missing"))
        self.assertTrue(
            fixture.projected_errors("ld: unknown file type in '/n/libanswer.a'", "malformed")
        )
        self.assertFalse(
            fixture.projected_errors("error: could not compile reader from src/lib.rs", "missing")
        )
        self.assertFalse(fixture.projected_errors("a malformed foreign peer", "malformed"))
        row = {
            "code": 101,
            "processes": {"final": {}},
            "error": "ld: unknown file type in libanswer.a",
            "phase": "bad",
        }
        with self.assertRaises(ValueError):
            matrix.check(row, "malformed")
        row["processes"]["final"] = {"first": {"pid": 7}}
        matrix.check(row, "malformed")

    def test_two_actual_binaries_versus_stale(self):
        row = {
            "code": 0,
            "phase": "warm",
            "products": {k: {"value": 17} for k in fixture.BINS},
            "processes": {"all_ld": [], "final": {}},
        }
        matrix.check(row, 17, 0)
        with self.assertRaises(ValueError):
            matrix.check(row, 29)
        with self.assertRaises(ValueError):
            matrix.check(row, 17, 2)
        del row["products"]["second"]
        with self.assertRaises(ValueError):
            matrix.check(row, 17)

    def test_installed_tree_catches_mutated_runtime_and_alias(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "bin").mkdir()
            p = root / "bin/rustc"
            p.write_bytes(b"17")
            link = root / "rustc"
            link.symlink_to("bin/rustc")
            a = acquire.installed_tree(root)
            p.write_bytes(b"29")
            b = acquire.installed_tree(root)
            self.assertNotEqual(a["bin/rustc"], b["bin/rustc"])
            self.assertEqual(a["rustc"], {"link": "bin/rustc"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
