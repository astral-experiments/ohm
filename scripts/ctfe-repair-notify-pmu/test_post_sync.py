"""Native FD, hard-link, sparse extent and boundary-identity controls outside any PMU."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import post_sync as s


class Boundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name).resolve()
        self.owners = {x: str(self.work / "target/debug/incremental/branch" / x) for x in ("one", "two")}
        self.fresh = "s-abc-_0123456789abcdef_aaa-bbb"
        self.before = {"owners": self.owners, "sessions": {a: {} for a in self.owners}}
        self.pl = {a: {"final": self.fresh} for a in self.owners}

    def write(self, mode):
        for a, p in self.owners.items():
            d = Path(p) / self.fresh
            d.mkdir(parents=True)
            for name in s.names(mode, a, {"one"}):
                target = d / name
                with target.open("xb") as f:
                    for i in range(256):
                        f.seek(8192 * i)
                        f.write((b"archive-fd-stability\n" * 199)[:4096])
                if name in s.RAW:
                    os.link(target, d / ("ohm-build-" + name))
        return Path(self.owners["one"]) / self.fresh / s.names(mode, "one", {"one"})[0]

    def read(self, mode):
        post = {"sessions": {a: {self.fresh: {}} for a in self.owners}}
        led = {}
        for a, p in self.owners.items():
            for n in s.names(mode, a, {"one"}):
                f = Path(p) / self.fresh / n
                x = f.stat()
                with f.open("rb") as i:
                    h = hashlib.file_digest(i, "sha256").hexdigest()
                post["sessions"][a][self.fresh][n] = dict(
                    dev=x.st_dev,
                    ino=x.st_ino,
                    links=x.st_nlink,
                    bytes=x.st_size,
                    blocks=x.st_blocks * 512,
                    sha256=h,
                )
                led[str(f.relative_to(self.work))] = [
                    x.st_dev,
                    x.st_ino,
                    x.st_nlink,
                    x.st_mode,
                    x.st_blocks,
                    x.st_size,
                ]
        return post, led

    def whole(self, mode):
        self.write(mode)
        wait = time.monotonic_ns()
        with s.hold(self.before, {"one"}, mode, self.work, wait) as b:
            post, led = self.read(mode)
        clock = {"stop": wait - 1} if mode != "E" else None
        s.verify(b, self.before, post, self.pl, led, {"one"}, mode, self.work, clock)
        return b, post, led

    def test_real_raw_linked(self):
        self.whole("E")

    def test_real_packed_and_raw(self):
        self.whole("O")

    def test_real_pass(self):
        self.whole("P")

    def test_real_blocked(self):
        self.whole("B")

    def test_original_worker_rows_remain_refused(self):
        here = Path(__file__).resolve().parent
        sys.path.insert(0, str(here.parent / "ctfe-repair-encode"))
        import archive

        rows = json.loads((here / "allocation-refusals.json").read_bytes())
        self.assertEqual(
            [(r["stage"], r["job"], r["artifact"]) for r in rows],
            [("structural-E", 124825218930, 13081195030), ("return-B", 124825218713, 13080658595)],
        )
        for row in rows:
            identity, ledger = row["file"], row["whole_tree"]
            self.assertFalse(archive.row_matches(ledger, identity))
            self.assertEqual(ledger[4] * 512 - identity["blocks"], 4096)
            self.assertTrue(archive.row_matches(ledger, identity | {"blocks": ledger[4] * 512}))
            self.assertEqual(
                Path(row["path"]).name, "query-cache.bin" if row["position"] == "01" else "dep-graph.bin"
            )

    def test_changed_single_sector_is_still_refused(self):
        b, p, ld = self.whole("E")
        k = next(iter(ld))
        ld[k][4] += 8
        with self.assertRaisesRegex(ValueError, "post-sync whole-tree"):
            s.verify(b, self.before, p, self.pl, ld, {"one"}, "E", self.work, None)
        ld[k][4] -= 8
        for field, value in (
            ("after_sha256", "f" * 64),
            ("after_bytes", 123),
            ("before_sha256", "f" * 64),
            ("identity", [9, 9, 33188, 2, 5, 5, 5]),
        ):
            x = deepcopy(b)
            x["files"][k][field] = value
            with self.assertRaises(ValueError):
                s.verify(x, self.before, p, self.pl, ld, {"one"}, "E", self.work, None)
        with self.assertRaises(ValueError):
            s.verify(
                b, self.before, p, self.pl, ld, {"one"}, "E", self.work, {"stop": b["ready_ns"] + 1}
            )

    def test_replacement_with_same_bytes(self):
        path = self.write("E")
        alias = path.with_name("ohm-build-" + path.name)
        content = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "different table identity"):
            with s.hold(self.before, {"one"}, "E", self.work, time.monotonic_ns()):
                new = path.with_name("foreign")
                new.write_bytes(content)
                self.assertNotEqual(new.stat().st_ino, path.stat().st_ino)
                os.replace(new, path)
        self.assertEqual(alias.read_bytes(), content)

    def test_replaced_or_changed_same_inode(self):
        path = self.write("B")
        with self.assertRaisesRegex(ValueError, "different table identity"):
            with s.hold(self.before, {"one"}, "B", self.work, time.monotonic_ns()):
                st = path.stat()
                with path.open("r+b") as f:
                    f.write(b"different")
                os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
                self.assertEqual(st.st_ino, path.stat().st_ino)

    def test_wrong_format_and_symlink(self):
        path = self.write("E")
        shadow = path.with_name(s.PACKED[0])
        shadow.symlink_to(path.name)
        with self.assertRaisesRegex(ValueError, "wrong fresh"):
            with s.hold(self.before, {"one"}, "E", self.work, time.monotonic_ns()):
                pass
        shadow.unlink()
        path.unlink()
        path.symlink_to("ohm-build-" + path.name)
        with self.assertRaisesRegex(ValueError, "nonregular"):
            with s.hold(self.before, {"one"}, "E", self.work, time.monotonic_ns()):
                pass


if __name__ == "__main__":
    unittest.main()
