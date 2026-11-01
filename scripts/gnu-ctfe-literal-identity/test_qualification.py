"""Offline source, role, metadata and artifact admission controls."""

from pathlib import Path
import copy, gzip, hashlib, json, os, struct, subprocess, sys, tempfile, unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import binding, bootstrap_subject, overlay, ruff


class FileTests(unittest.TestCase):
    def test_pack_and_declared_inputs(self):
        d = json.loads((HERE / "inputs/product.json").read_bytes())
        raw = (HERE / "inputs/child.pack").read_bytes()
        self.assertEqual(d["root"], binding.TREE)
        self.assertEqual(d["child"], binding.NEW)
        self.assertEqual(d["parent"], binding.OLD)
        self.assertEqual(set(d["blobs"]), binding.EXPECTED)
        self.assertEqual(raw[:4], b"PACK")
        self.assertEqual(struct.unpack(">II", raw[4:12]), (2, 20))
        self.assertEqual(hashlib.sha1(raw[:-20]).digest(), raw[-20:])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), d["pack"]["sha256"])
        self.assertEqual(len(ruff.GRAPH["roles"]), 36)
        self.assertEqual(len(ruff.GRAPH["scripts"]), 5)

    def test_named_units_are_required_once(self):
        names = ["aliases_preserve_allocation_identity", "only_the_original_ctfe_literal_id_is_restored"]
        lines = ["test mir::interpret::tests::" + n + " ... ok" for n in names]
        end = "test result: ok. 2 passed; 0 failed;"
        self.assertEqual(bootstrap_subject.unit_log("\n".join(lines + [end])), names)
        for bad in (
            lines[1:],
            lines + [lines[0]],
            [v.replace("::interpret::", "::fake::") for v in lines],
            lines + ["internal compiler error"],
        ):
            with self.assertRaises(ValueError):
                bootstrap_subject.unit_log("\n".join(bad + [end]))

    def test_rust_scope_and_safety(self):
        w = (HERE.parents[1] / ".github/workflows/ci.yml").read_text()
        self.assertIn("reviewed_head == github.sha", w)
        self.assertIn(binding.REF, w)
        self.assertEqual(w.count("runs-on:"), 1)
        self.assertEqual(w.count("actions/checkout@"), 4)
        self.assertNotRegex(
            w,
            r"permissions: (write-all|read-all)|: write\s*$|RUSTFLAGS|secrets\.|perf_event|experiment\.py|build_writer\.py",
        )
        self.assertEqual(w.count("GH_TOKEN:"), 1)
        self.assertIn("persist-credentials: false", w)
        self.assertFalse(any(v in w for v in ("workflow_run:", "pull_request:", "push:", "schedule:")))
        calls = (HERE / "bootstrap_subject.py").read_text()
        for text in (
            "helper.succeeded(args",
            "helper.verdict(",
            "reg.validate(repo, install=True)",
            "helper.STAGE0",
            "helper.LLVM",
        ):
            self.assertIn(text, calls)

    def test_source_rejected_before_remote(self):
        with mock.patch.dict(
            os.environ,
            {"GITHUB_EVENT_NAME": "push", "GITHUB_REPOSITORY": "astral-experiments/ohm"},
            clear=True,
        ):
            with self.assertRaises(ValueError):
                binding.job()

    def test_archive_path_and_integrity(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            f = r / "asset"
            f.write_bytes(b"exact payload")
            key = ruff.put(r, f)
            self.assertEqual(ruff.read_body(r, key), f.read_bytes())
            (r / (key + ".gz")).write_bytes(gzip.compress(b"replaced payload"))
            with self.assertRaises(ValueError):
                ruff.read_body(r, key)
            bad = r / "foreign.a"
            subprocess.run(["ar", "rcs", bad, f], check=True)
            with self.assertRaises(ValueError):
                ruff.archive(bad)

    def test_overlay_roundtrip_and_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            world = r / "candidate"
            world.mkdir()
            driver = "libdriver.so"
            names = [driver, "bin/rustdoc"] + ["f" + str(i) for i in range(79)]
            old = {}
            new = {}
            for i, n in enumerate(names):
                f = world / n
                f.parent.mkdir(exist_ok=True)
                f.write_bytes(bytes([i]))
                f.chmod(0o600)
                old[n] = [binding.digest(bytes([i + (n == driver)])), 1, 0o600]
                new[n] = [binding.sha(f), 1, 0o600]
            body = r / "overlay"
            sig = overlay.archive(body, world, old, new, driver)
            self.assertEqual(sig, overlay.verify(body, old, new, driver))
            m = json.loads((body / "manifest.json").read_bytes())
            self.assertEqual(set(m["members"]), {driver})
            m["candidate"] = binding.OLD
            (body / "manifest.json").write_text(json.dumps(m))
            with self.assertRaises(ValueError):
                overlay.verify(body, old, new, driver)

    @mock.patch.object(ruff, "expansions", lambda o: o["exps"])
    def test_full_def_and_expansion_polarity(self):
        defs = {i: dict(id=i, fp="f" if i < 17431 else None, path=("source", i)) for i in range(18142)}
        empty = dict(
            name="ruff_python_ast",
            raw=b"empty",
            stable=309,
            private="same",
            global_fp="global",
            public="clean",
            defs=defs,
            exps=dict.fromkeys(range(3589), "x"),
            allocs=[],
        )
        warm = copy.deepcopy(empty)
        warm["raw"] = b"warm"
        warm["public"] = "dirty"
        for i in range(10150):
            warm["defs"][i]["fp"] = "d"
        self.assertEqual(ruff.projection(warm, empty, "E")["changed_def_hashes"], 10150)
        with self.assertRaises(ValueError):
            ruff.projection(warm, empty, "C")
        with self.assertRaises(ValueError):
            ruff.projection(empty, empty, "E")
        self.assertEqual(ruff.projection(empty, empty, "C")["changed_def_hashes"], 0)
        warm["defs"][200]["fp"] = "f"
        with self.assertRaises(ValueError):
            ruff.projection(warm, empty, "E")
        for k, value in (("private", "other"), ("global_fp", "other"), ("exps", {})):
            with self.assertRaises(ValueError):
                ruff.projection(empty | {k: value}, empty, "C")


if __name__ == "__main__":
    unittest.main(verbosity=2)
