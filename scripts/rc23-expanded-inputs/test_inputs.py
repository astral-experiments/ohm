"""Offline admission tests for the two source transports and native evidence readers."""

import copy
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from materialize import REG, index, sha
from diamond_policy import collision
import pgo


class NativeInputs(unittest.TestCase):
    def test_installer_and_compiler_transports(self):
        for name in ("rust", "cargo"):
            spec = REG[name + "_tail"]
            packet = HERE / (name + "-tail.pack")
            self.assertEqual(sha(packet), spec["sha256"])
            self.assertEqual(packet.stat().st_size, spec["bytes"])
            self.assertEqual(int.from_bytes(packet.read_bytes()[8:12], "big"), spec["objects"])
            self.assertEqual(spec["chain"][0][::2], [spec["commit"], spec["tree"]])
            self.assertEqual(spec["chain"][-1][1], spec["from"])
        self.assertEqual(REG["rust_tail"]["gitlinks"], {"src/tools/cargo": REG["cargo_tail"]["commit"]})
        for short in ("reader.rs", "rmake.rs", "roster.rs"):
            name = "trait-impl-bucket-projection/" + short
            raw = (HERE / name).read_bytes()
            self.assertEqual(
                hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest(),
                REG["rust_tail"]["paths"]["tests/run-make/" + name],
            )
        self.assertEqual(
            sha(HERE / "ohm_ready_tests.rs"),
            "aed63f3c04ca7fb3eb4826bc53125d9dc741d23d1a6f75ec66cf4017ad3b50b8",
        )

    def test_strict_git_receives_header_natively(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source.git"
            dst = root / "restore.git"
            for r in (src, dst):
                subprocess.run(["git", "init", "-q", "--bare", "--template=", r], check=True)
            payload = hashlib.shake_256(b"actual nonseekable-child file descriptor control").digest(32768)
            oid = subprocess.check_output(["git", "-C", src, "hash-object", "-w", "--stdin"], input=payload)
            raw = subprocess.check_output(["git", "-C", src, "pack-objects", "--stdout"], input=oid)
            p = root / "source.pack"
            p.write_bytes(raw)
            self.assertGreater(p.stat().st_size, 16384)
            spec = dict(objects=1, bytes=len(raw), sha256=sha(p))
            index(dst, p, spec)
            self.assertEqual(
                subprocess.check_output(["git", "-C", dst, "cat-file", "blob", oid.decode().strip()]), payload
            )
            for key, value in [("objects", 2), ("sha256", "f" * 64), ("bytes", len(raw) - 2)]:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    index(dst, p, dict(spec, **{key: value}))
            p.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
            with self.assertRaises(ValueError):
                index(dst, p, spec)

    def test_genuine_training_actors_and_complete_profiles(self):
        data = json.loads(gzip.decompress((HERE / "historical-training.json.gz").read_bytes()))
        for host, case in data.items():
            rows = case["ordered_rows"]
            got = pgo.roster(rows, host)
            self.assertEqual((len(got["rows"]), len(got["finished"])), (27, 9))
            self.assertEqual(got["invocation"]["argv"][0].split("/")[-3:], ["stage0", "bin", "cargo"])
            wrong = []
            for old, new in [
                ("stage2/bin/rustc", "stage0/bin/rustc"),
                ("stage2-tools-bin/cargo", "stage0/bin/cargo"),
                ("--jobs 4", "--jobs 2"),
                ("RUSTC_BOOTSTRAP=1", "RUSTC_BOOTSTRAP=0"),
            ]:
                b = copy.copy(rows)
                b[1] = b[1].replace(old, new)
                wrong.append(b)
            wrong += [rows[:2] + rows[3:], rows[:-2] + [rows[-1]], rows[:3] + [rows[2]] + rows[3:]]
            for changed in wrong:
                with self.subTest(host=host, changed=changed[1]), self.assertRaises(ValueError):
                    pgo.roster(changed, host)
            with self.assertRaises(ValueError):
                pgo.roster(rows, host, Path("/other/build"))

    def test_reported_darwin_alias_is_one_unfollowed_leaf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            actual = root / "private" / "var"
            actual.mkdir(parents=True)
            alias = root / "var"
            alias.symlink_to(actual, target_is_directory=True)
            leaf = actual / ".tmpGktchz"
            old = "stderr=   Compiling diesel v2.2.10 (" + str(leaf) + ")"
            other = "command did not complete successfully: rustc -C incremental=" + str(
                alias / leaf.name / "incremental-state"
            )
            result = pgo.reported_temps([old, other], actual)
            self.assertEqual(result, {leaf: sorted([str(alias / leaf.name), str(leaf)])})
            outside = root / "unrelated"
            outside.mkdir()
            leaf.symlink_to(outside, target_is_directory=True)
            (captured,) = pgo.reported_temps([old, other], actual)
            self.assertTrue(captured.is_symlink())
            self.assertNotEqual(captured, outside)
            with self.assertRaises(ValueError):
                pgo.reported_temps([old.replace(str(actual), str(outside))], actual)

    def test_host_specific_published_diamond_evidence(self):
        g = "x86_64-unknown-linux-gnu"
        a = "aarch64-apple-darwin"
        for h in [g, a]:
            for phase in ["cold-doc", "build-doc"]:
                for code in [0, 101, 127]:
                    self.assertFalse(collision("corrected", h, "default", phase, code))
                    self.assertFalse(collision("published-22", h, "off", phase, code))
                self.assertTrue(collision("published-22", g, "default", phase, 101))
        self.assertFalse(collision("published-22", a, "default", "cold-doc", 0))
        self.assertFalse(collision("published-22", a, "default", "build-doc", 0))
        self.assertTrue(collision("published-22", a, "default", "build-doc", 101))
        with self.assertRaises(ValueError):
            collision("published-22", a, "default", "build-doc", 127)


if __name__ == "__main__":
    unittest.main()
