"""Require real libc pass-through outside the one fresh target, including a distinct executable."""

import argparse
import errno
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evidence as ev

LIBRARY = None


class Scope(unittest.TestCase):
    def test_native_interposition(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = Path(tmp)
            gate = LIBRARY or r / "shim.so"
            if not LIBRARY:
                subprocess.run(
                    [
                        "/usr/bin/cc",
                        "-std=gnu11",
                        "-O2",
                        "-fPIC",
                        "-shared",
                        "-Wall",
                        "-Wextra",
                        "-Werror",
                        HERE / "pack_gate.c",
                        "-ldl",
                        "-o",
                        gate,
                    ],
                    check=True,
                )
            helper = r / "helper"
            subprocess.run(
                ["/usr/bin/cc", "-std=gnu11", "-Wall", "-Werror", HERE / "call_fixture.c", "-o", helper],
                check=True,
            )
            other = r / "same-argv0"
            shutil.copyfile(helper, other)
            other.chmod(0o755)
            owner = r / "incremental/34237/cohort-314"
            good = owner / "s-aa-_aaaaaaaaaaaaaaaa_1-working"
            final = owner / "s-ab-_aaaaaaaaaaaaaaaa_1-012"
            extra = owner.with_name(owner.name + "0") / good.name
            nested = good / "nested"
            bad = owner / "wrong-working"
            for p in (good, final, extra, nested, bad):
                p.mkdir(parents=True, exist_ok=True)
            flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_CLOEXEC
            control = r / "control"
            control.mkdir()
            env = dict(
                os.environ,
                LD_PRELOAD=str(gate),
                OHM_QA_PACK_CONTROL=str(control),
                OHM_QA_PACK_RUSTC=str(helper),
            )

            def call(path, f, binary=helper):
                c = subprocess.run(
                    [str(helper), str(path), str(f)],
                    executable=str(binary),
                    env=env,
                    check=True,
                    capture_output=True,
                )
                return [int(i) for i in c.stdout.split()]

            def mode(m):
                (control / "config").write_text(ev.config(m, [str(owner)]))

            g = good / ev.FILES[0]
            q = good / ev.FILES[1]
            mode("P")
            self.assertEqual(call(g, flags), [1, 0])
            g.unlink()
            mode("B")
            self.assertEqual(call(g, flags), [0, errno.EACCES])
            self.assertFalse(g.exists())
            for p in (q, final / g.name, extra / g.name, nested / g.name, bad / g.name, good / "different.bin"):
                self.assertEqual(call(p, flags), [1, 0])
                self.assertTrue(p.is_file())
            for f in (os.O_CREAT | os.O_RDWR, os.O_CREAT | os.O_EXCL | os.O_WRONLY):
                self.assertEqual(call(g, f), [1, 0])
                g.unlink()
            self.assertEqual(call(g, flags, other), [1, 0])
            self.assertEqual(call(g, os.O_RDONLY), [1, 0])
            self.assertEqual(call(q, flags), [0, errno.EEXIST])
            self.assertEqual(call(final / "absent", os.O_RDONLY), [0, errno.ENOENT])
            events = [r.split("\t") for p in control.glob("*.events") for r in p.read_text().splitlines()]
            refused = [r for r in events if r[0] == "G" and int(r[4]) == errno.EACCES]
            self.assertEqual(len(refused), 1)
            self.assertEqual(refused[0][-1], str(g))
            self.assertEqual(len([r for r in events if r[0] == "N"]), 1)

    def test_bad_configuration(self):
        for mode, p in [("F", ["/a"]), ("P", ["/a", "/a"]), ("B", ["a"]), ("P", ["/a/../b"]), ("P", ["/a\nx"])]:
            with self.subTest(mode=mode, p=p), self.assertRaises(ValueError):
                ev.config(mode, p)

    def test_native_object_discriminator(self):
        valid = bytearray(18)
        valid[:7] = b"\x7fELF\x02\x01\x01"
        valid[16] = 1
        self.assertTrue(ev.valid_object(valid))
        valid[16] = 2
        self.assertFalse(ev.valid_object(valid))

    def test_only_source_enrolled_owners(self):
        data = json.loads((HERE / "owners.json").read_bytes())
        self.assertEqual(len(data["selected"]), 14)
        self.assertFalse(set(data["selected"]) & set(data["other"]))
        self.assertEqual(set(data["packed_raw_objects"]), set(data["selected"] + data["other"]))
        self.assertEqual(
            [sum(row[i] for row in data["packed_raw_objects"].values()) for i in (0, 1)], [748, 918]
        )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", type=Path)
    args = ap.parse_args()
    LIBRARY = args.library
    unittest.main(argv=[sys.argv[0]])
