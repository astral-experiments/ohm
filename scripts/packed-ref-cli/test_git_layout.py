"""Check the frozen public carrier, exact Ruff watches, and negative observations."""

import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import git_layout as g


class TestPackedRuffRefs(unittest.TestCase):
    def record(self, name, commit):
        ref = "refs/heads/" + name
        values = {
            "HEAD": g.digest(("ref: " + ref + "\n").encode()),
            "packed-refs": g.TABLE,
            ref: g.digest((commit + "\n").encode()),
        }
        files = {}
        for n in g.watched_names(name):
            files[n] = {
                "type": "dir" if n == "refs/heads" else "file",
                "dev": 1,
                "ino": 2,
                "mtime_ns": 3,
                "ctime_ns": 4,
            }
            if n in values:
                files[n]["sha256"] = values[n]
        return {
            "ref": name,
            "revision": commit,
            "y_loose": False,
            "table_sha256": g.TABLE,
            "table_bytes": g.TABLE_BYTES,
            "y_range": list(g.Y_RANGE),
            "watched": files,
        }

    def test_public_advertisement_and_git_objects(self):
        contents, pairs = g.inputs()
        self.assertEqual(len(pairs), 1291)
        self.assertEqual(len({a for a, _ in pairs}), 1286)
        self.assertEqual(sum(map(len, contents.values())), 623563)
        self.assertTrue(all(k.startswith(b"refs/remotes/origin/") for _, k in pairs))

    def test_known_observations(self):
        for ref, rev in ((g.Y, g.B), (g.X, g.A), (g.X, g.B)):
            g.verify_snapshot(self.record(ref, rev), ref, rev)

    def test_reject_wrong_table_or_loose_witness(self):
        original = self.record(g.Y, g.B)
        for key, value in (
            ("y_loose", True),
            ("y_range", [47, 118]),
            ("table_bytes", 65536),
            ("table_sha256", "0" * 64),
        ):
            changed = deepcopy(original)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                g.verify_snapshot(changed, g.Y, g.B)
        for name, key, value in (
            ("refs/heads", "type", "file"),
            ("packed-refs", "sha256", "0" * 64),
            ("HEAD", "ino", 0),
        ):
            changed = deepcopy(original)
            changed["watched"][name][key] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                g.verify_snapshot(changed, g.Y, g.B)
        with self.assertRaises(ValueError):
            g.verify_snapshot(self.record(g.X, g.B), g.Y, g.B)
        with self.assertRaises(ValueError):
            g.verify_snapshot(self.record(g.Y, g.A), g.Y, g.A)

    def test_build_stdout_rejects_other_ref_path_or_stale_commit(self):
        repo = Path("/private/study/ruff")
        for name, rev in ((g.Y, g.B), (g.X, g.A), (g.X, g.B)):
            watches = [
                b"cargo:rerun-if-changed="
                + str(repo / "crates/ruff/../../.git" / p).encode()
                for p in g.watched_names(name)
            ]
            rows = [
                *watches,
                b"cargo::rustc-env=RUFF_COMMIT_HASH=" + rev.encode(),
                b"cargo::rustc-env=RUST_HOST_TARGET=x86_64-unknown-linux-gnu",
            ]
            raw = b"\n".join(rows) + b"\n"
            self.assertEqual(
                g.build_output(raw, repo, name, rev)["stdout_sha256"], g.digest(raw)
            )
            for bad in (
                raw.replace(watches[-1], b"", 1),
                raw + rows[0] + b"\n",
                raw.replace(rev.encode(), b"0" * 40),
            ):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    g.build_output(bad, repo, name, rev)

    def test_refuse_an_unowned_fixture(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict("os.environ", {"RUNNER_TEMP": temp}),
        ):
            location = Path(temp) / "unrecognized-checkout"
            with self.assertRaises(ValueError):
                g.install(location)
            self.assertFalse(location.exists())


if __name__ == "__main__":
    unittest.main()
