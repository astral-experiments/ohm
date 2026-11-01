"""Reopen the real refused link/whole calibration and exercise the new, prospectively required file witness."""

from copy import deepcopy
import gzip
import json
from pathlib import Path
import os
import sys
import tempfile
import unittest
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import protocol as p
import file_witness as files
import inventory
import verify
import instrument

f = p.f
COLLECTOR, CONTRACT = (Path(a).resolve() for a in sys.argv[1:3])
PREFIX = "cli/inventory/edited/"
REPO = Path("/home/runner/work/_temp/ohm-branch-object-qa/ruff")
WORK = REPO.parent / "work"


class Media:
    def __init__(self, z, prefix, replace=None, omit=None):
        self.z, self.prefix = z, prefix
        self.replace, self.omit = replace or {}, omit or set()

    def namelist(self):
        return [
            n.removeprefix(self.prefix)
            for n in self.z.namelist()
            if n.startswith(self.prefix) and n.removeprefix(self.prefix) not in self.omit
        ]

    def open(self, name):
        from io import BytesIO

        return BytesIO(self.replace[name]) if name in self.replace else self.z.open(self.prefix + name)

    def read(self, name):
        with self.open(name) as f:
            return f.read()


class Physical(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        zpath = HERE / "retained-registration.zip"
        f.require(
            p.c.sha(zpath) == "dd16c35427ec56dc248340c1ddd071e5a6a94c21afc7b33619614f6fbbc11cb3",
            "different original evidence",
        )
        cls.z = zipfile.ZipFile(zpath)
        cls.media = Media(cls.z, "case/")
        cls.rows = [
            json.loads(v) for v in gzip.decompress(cls.media.read(PREFIX + "cargo.stdout.gz")).splitlines()
        ]
        _, _, cls.products, _ = p.graph(cls.rows, "cli", REPO, WORK)
        cls.ins = json.loads(gzip.decompress(cls.media.read(PREFIX + "output-inodes.json.gz")))
        cls.sdk = json.loads(cls.media.read("sdk.json"))
        cls.selectors = json.loads(cls.media.read("selectors.json"))
        corpus = root / "actual"
        cls.trace = corpus / PREFIX / "trace"
        cls.trace.mkdir(parents=True)
        for n in cls.media.namelist():
            if n.startswith(PREFIX + "trace/"):
                (corpus / n).write_bytes(cls.media.read(n))
        original, cls.pmu = instrument.compile_sources(COLLECTOR, CONTRACT, root / "reader")
        cls.topo = inventory.decoder(original)

    @classmethod
    def tearDownClass(cls):
        cls.z.close()
        cls.tmp.cleanup()

    def project(self):
        return inventory.read(
            self.trace, self.topo, "cli", REPO, WORK, self.products, self.ins, self.sdk, self.selectors
        )

    def test_official_all_seven_images_and_actual_outputs(self):
        result = self.project()
        self.assertEqual(result["successful_execs"], 7)
        self.assertEqual(
            [(v["target"], v["kind"], v["mode"]) for v in result["owners"]],
            [("ruff_python_parser", ["lib"], "full"), ("ruff", ["bin"], "link-only")],
        )
        self.assertEqual(len(result["without_rustc"]), 14)
        self.assertEqual(result["wild"], 1)
        link = result["owners"][1]["links"][0]
        self.assertEqual([link[v] for v in ("cc_serial", "collect2_serial", "wild_serial")], [5, 6, 7])
        self.assertEqual(self.ins[files.relative(link["output"], WORK)], self.ins["target/debug/ruff"])
        self.assertEqual(self.ins["target/debug/ruff"][:3], [33, 7860867, 147231016])
        self.assertEqual(len(self.products), 375)
        self.assertEqual(sum(not r["fresh"] for r in self.products), 16)
        # V1 did not capture its saved input or the pre-command library hashes: a projected owner
        # roster is available, but this old host cannot pass successor storage/measurement admission.
        with self.assertRaises((KeyError, ValueError)):
            files.validate({}, {}, "cli", self.products, result, self.ins, REPO, WORK)

    def test_actual_argv_and_kernel_output_mutations(self):
        mutations = [
            ("args-0004", b"/out/ruff.rlink\0", b"/out/other.rlink\0"),
            ("args-0004", b"--edition=2024\0", b"--edition=2024\0--sysroot\0"),
            ("args-0004", b"--emit=dep-info,link\0", b"--emit=dep-info,link\0--emit=metadata\0"),
            ("args-0004", b"/out/ruff.rlink\0", b"/out/ruff.rlink\0crates/ruff/src/main.rs\0"),
            ("args-0004", b"\0-Z\0link-only\0", b"\0-Z\0link-only=no\0"),
            ("args-0004", b"/out/ruff.rlink\0", b"/out/ruff.input\0"),
            ("args-0003", b"crates/ruff_python_parser/src/lib.rs\0", b"/unrelated/src/lib.rs\0"),
            ("args-0007", b"/out/ruff\0", b"/out/other\0"),
            ("exec.tsv", b"33\t7613891\t", b"33\t7613892\t"),
            ("exec.tsv", b"33\t7613888\t", b"33\t7613891\t"),
        ]
        for n, a, b in mutations:
            path = self.trace / n
            original = path.read_bytes()
            self.assertIn(a, original)
            try:
                path.write_bytes(original.replace(a, b))
                with self.subTest(member=n, change=b), self.assertRaises(
                    (ValueError, AssertionError, KeyError)
                ):
                    self.project()
            finally:
                path.write_bytes(original)
        old = self.ins["target/debug/ruff"]
        self.ins["target/debug/ruff"] = [old[0], old[1] + 1, *old[2:]]
        try:
            with self.assertRaisesRegex(ValueError, "executable inode"):
                self.project()
        finally:
            self.ins["target/debug/ruff"] = old

    def test_entire_genuine_signed_calibration_and_four_empty_exceptions(self):
        with tempfile.TemporaryDirectory() as td:
            r = Path(td)
            verify.counter_files(Media(self.z, "first-A/"), r)
            cal = self.pmu.calibration(r / "counter-programs", r, replay=True)
            self.assertEqual(sum(len(v[0]) for v in cal["whole28"].values()), 28)
        for repl, omit in [
            ({"calibration/nested-plain-0/exec.tsv": b"forged"}, set()),
            ({"calibration/nested-tree-2/exec.tsv": b""}, set()),
            ({"calibration/nested-plain-0/tasks.tsv": b""}, set()),
            ({"calibration/nested-plain-1/samples.tsv": b""}, set()),
            ({}, {"calibration/nested-plain-3/exec.tsv"}),
        ]:
            with tempfile.TemporaryDirectory() as td, self.subTest(
                repl=list(repl), omit=omit
            ), self.assertRaises(ValueError):
                verify.counter_files(Media(self.z, "first-A/", repl, omit), Path(td))

    def test_genuine_parser_target_with_full_and_saved_operands(self):
        # The target/filename/features are from a real signed B --no-run build. These argv mutations
        # test both classifier branches and are not evidence of a hosted parser exec.
        target = json.loads(self.z.read("local-test/edited.json"))
        name = Path(target["executable"])
        suffix = name.name.removeprefix("fixtures")
        folder = WORK / "target/debug/deps"
        output = folder / name.name
        target["filenames"] = [str(output)]
        target["executable"] = str(output)
        target["target"]["src_path"] = str(REPO / "crates/ruff_python_parser/tests/fixtures.rs")
        stored = {files.relative(output, WORK): [11, 12, 1001, 0o100755, 13, 14]}
        common = [
            "rustc",
            "--crate-name",
            "fixtures",
            "--test",
            "--emit=dep-info,link",
            "-C",
            "extra-filename=" + suffix,
            "--out-dir",
            str(folder),
        ]
        full = common + ["--edition=" + target["target"]["edition"], target["target"]["src_path"]]
        saved = common + [
            "--edition=" + target["target"]["edition"],
            str(output.with_suffix(".rlink")),
            "-Z",
            "link-only",
        ]

        def read(a):
            return inventory.products([target], {"argv": a}, REPO, WORK, stored)[1]

        self.assertEqual((read(full), read(saved)), ("full", "link-only"))
        for a in (
            common,
            full[:-1] + ["other.rs"],
            saved[:-2],
            full + saved[-3:],
            saved + ["--target", "custom"],
            [x for x in full if x != "--test"],
        ):
            with self.assertRaises((ValueError, KeyError)):
                read(a)

    def test_physical_file_witness_keeps_only_content_and_same_inode(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            work = root / "work"
            repo = root / "ruff"
            out = work / "target" / "debug" / "real"
            out.mkdir(parents=True)
            libpaths = [out / "libkeep.rlib", out / "libkeep.rmeta"]
            for i, q in enumerate(libpaths):
                q.write_bytes(b"ar or metadata" + bytes([i]))
            exe = out / "ruff"
            exe.write_bytes(b"native")
            public = work / "target/debug/ruff"
            os.link(exe, public)
            recipe = exe.with_suffix(".rlink")
            recipe.write_bytes(b"private saved link bytes")
            row = dict(
                target=dict(name="keep", kind=["lib"], src_path=str(repo / "crates/keep/src/lib.rs")),
                filenames=list(map(str, libpaths)),
            )
            final = dict(target=dict(name="ruff", kind=["bin"]), executable=str(public))
            result = dict(
                without_rustc=[dict(target="keep", outputs=row["filenames"])],
                owners=[dict(outputs=[str(exe)], mode="link-only")],
            )
            args = ("cli", [row, final], repo, work)
            before = files.capture(*args)
            s = libpaths[0].stat()
            os.utime(libpaths[0], ns=(s.st_atime_ns, s.st_mtime_ns + 100))
            after = files.capture(*args)

            def checked(a):
                ins = {k: v[:6] for k, v in a["libraries"].items()}
                files.validate(before, a, "cli", [row, final], result, ins, repo, work)

            checked(after)
            for q in (libpaths[0], recipe):
                before = files.capture(*args)
                original = q.read_bytes()
                timestamps = q.stat()
                q.write_bytes(b"x" * len(original))
                os.utime(q, ns=(timestamps.st_atime_ns, timestamps.st_mtime_ns))
                with self.assertRaisesRegex(ValueError, "changed"):
                    checked(files.capture(*args))
                q.write_bytes(original)
            before = files.capture(*args)
            foreign = out / "new"
            foreign.write_bytes(libpaths[0].read_bytes())
            foreign.replace(libpaths[0])
            with self.assertRaisesRegex(ValueError, "inode or bytes"):
                checked(files.capture(*args))
            before = files.capture(*args)
            recipe.unlink()
            with self.assertRaisesRegex(ValueError, "saved linker input"):
                checked(files.capture(*args))
            foreign.write_bytes(b"foreign")
            recipe.symlink_to(foreign)
            with self.assertRaisesRegex(ValueError, "redirected"):
                files.capture(*args)

    def test_all_signed_queries_and_foreign_action(self):
        actual = p.c.read(p.c.HERE / "physical-fixture.json.gz")
        original = actual["source"]["signed_release_probe"]["selected"]
        queries = [tuple(a[1:]) for name, a in original if name.endswith("/rustc")]
        self.assertEqual(len(queries), 7)
        self.assertTrue(set(queries) <= inventory.signed_queries())
        for example in (("--print=cfg", "--unstable-option"), ("--print=sysroot", "fake.rlink")):
            self.assertNotIn(example, inventory.signed_queries())
        path = self.trace / "exec.tsv"
        intact = path.read_bytes()
        argv = self.trace / "args-0003"
        argv_intact = argv.read_bytes()
        try:
            original = next(line for line in intact.splitlines() if line.startswith(b"3\t"))
            changed = original.split(b"\t")
            changed[2:7] = [b"0", b"0", b"34", b"8000000", b"/usr/bin/foreign"]
            path.write_bytes(intact.replace(original, b"\t".join(changed)))
            argv.write_bytes(b"/usr/bin/foreign\0" + argv_intact.split(b"\0", 1)[1])
            with self.assertRaises((ValueError, AssertionError)):
                self.project()
        finally:
            path.write_bytes(intact)
            argv.write_bytes(argv_intact)

    def test_same_byte_executable_on_wrong_inode(self):
        public = WORK / "target/debug/ruff"
        raw = self.ins["target/debug/ruff"]
        witness = [*raw, "a" * 64]
        desc = {"whole": witness[-1], "size": raw[2]}
        files.final_image(witness, witness, public, desc, self.ins, WORK)
        for n in (0, 1, 2, 4, 5, 6):
            wrong = witness.copy()
            wrong[n] = "b" * 64 if n == 6 else wrong[n] + 1
            with self.assertRaisesRegex(ValueError, "final writer"):
                files.final_image(wrong, wrong, public, desc, self.ins, WORK)

    def test_structural_refusal_delayed_without_waiver(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for role in p.ROLES:
                visit = root / role / "inventory/edited"
                visit.mkdir(parents=True)
                for label in ("before", "output", "after", "classification"):

                    def refuse():
                        raise ValueError("deliberate structural refusal")

                    self.assertIsNone(files.record(visit, label, refuse))
                    self.assertIn(
                        "deliberate structural refusal",
                        (visit / (label + "-inventory-refusal.txt")).read_text(),
                    )
                (visit / "true-native-result.json").write_text('{"retained":true}')
            with self.assertRaisesRegex(ValueError, "structural evidence refused"):
                files.complete(root)
            self.assertEqual(sum(1 for _ in root.glob("*/inventory/edited/*-inventory-refusal.txt")), 8)


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1], verbosity=2)
