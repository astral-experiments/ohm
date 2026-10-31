"""Offline checks for the integration-specific gates; no Cargo or compiler is invoked."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import selection
import suite


class Controls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.libtest = self.root / "integration_test-abcd"
        self.cli = self.root / "ruff"
        self.libtest.touch()
        self.cli.touch()

    def args(self, fixture=suite.EXACT[0]):
        operand = "@!.txt" if fixture == suite.EXACT[1] else "@/tmp/legitimate/file_paths.txt"
        return [(100, str(self.libtest), [str(self.libtest), "--exact", fixture, "--test-threads=1", "--color", "never"]),
                (103, str(self.cli), [str(self.cli), "check", "--no-cache", "--isolated", operand])]

    def test_native_inventory(self):
        data = (HERE / "expected-tests.txt").read_bytes()
        names = suite.inventory(data)
        self.assertTrue(set(suite.EXACT) < set(names))
        with self.assertRaises(ValueError):
            suite.inventory(data.replace(b"unreadable_dir: test\n", b"another_test: test\n"))

    def test_complete_test_outcomes(self):
        p = b"test first ... ok\ntest second ... ok\n\ntest result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.04s\n"
        suite.verdict(p, ["first", "second"])
        for q in (p.replace(b"second ... ok", b"second ... FAILED"), p.replace(b"second", b"first"),
                  p.replace(b"0 ignored", b"1 ignored"), p+p, p.replace(b"2 passed", b"96 passed")):
            with self.assertRaises(ValueError):
                suite.verdict(q, ["first", "second"])

    def test_two_physical_children(self):
        for case in suite.EXACT:
            self.assertEqual(suite.check_children(self.args(case), self.libtest, self.cli, case)["ruff_pid"], 103)
        first, second = self.args()
        for bad in ([first], [first, second, (104, "/bin/cargo", ["cargo", "metadata"])],
                    [first,(100,second[1],second[2])], [first,(103,str(self.libtest),second[2])],
                    [first,(103,second[1],second[2][:-1]+["@!.txt"])]):
            with self.assertRaises(ValueError):
                suite.check_children(bad, self.libtest, self.cli, suite.EXACT[0])

    def test_real_eacces(self):
        suite.permission_prefix(self.root)
        self.assertTrue((self.root / "eacces.json").is_file())

    def externs(self):
        rows, argv = [], []
        for name in selection.LIBS:
            body = self.root / ("lib" + name + "-owner.rlib")
            meta = body.with_suffix(".rmeta")
            body.write_bytes(name.encode())
            meta.write_bytes(b"meta")
            for p in (body,meta):
                argv += ["--extern", name + "=" + str(p)]
            rows.append(dict(reason="compiler-artifact", target=dict(name=name,kind=["lib"]),
                             features=[],profile={},filenames=list(map(str,(body,meta)))))
        return rows, argv

    def test_resolve_real_rlib_and_rmeta_pair(self):
        rows, argv = self.externs()
        match = selection.selected_externs(argv)
        mapping = {"cli": {"externs":match}, "harness":{"externs":match}}
        other = self.root / "libparser-other.rlib"
        other.write_bytes(b"bad")
        other_row = rows[1] | {"filenames": [str(other)]}
        sha = lambda f: hashlib.sha256(Path(f).read_bytes()).hexdigest()
        kept, actual = selection.reader_stream([other_row,*rows], mapping, sha)
        self.assertEqual(kept, rows)
        self.assertEqual(len(actual["ruff_python_parser"]["actual_rmeta"]), 1)
        for raw in ([*argv,*argv[-2:]], argv[:-1]+[argv[-1].replace("-owner.rmeta", "-other.rmeta")]):
            with self.assertRaises(ValueError):
                selection.selected_externs(raw)
        for data in ([rows[0],other_row], [*rows,rows[1]], [rows[0], rows[1]|{"filenames":rows[1]["filenames"][:1]}]):
            with self.assertRaises(ValueError):
                selection.reader_stream(data, mapping, sha)

    def test_preserve_typed_variants(self):
        def row(feature, fresh):
            return dict(package_id="path+"+self.root.as_uri()+"/crates/one#0.1.0", reason="compiler-artifact",
                target=dict(name="one",kind=["lib"],crate_types=["lib"]),features=[feature],profile={},fresh=fresh)
        rows, dirty = selection.roster([row("test-rules",False),row("ordinary",True)], self.root)
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["features"] for r in dirty], [["test-rules"]])
        with self.assertRaises(ValueError):
            selection.roster([row("ordinary",True) | {"package_id":"path+file:///other/workspace#0.1.0"}],self.root)


if __name__ == "__main__":
    unittest.main()
