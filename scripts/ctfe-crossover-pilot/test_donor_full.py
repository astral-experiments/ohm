"""Exercise the full-CLI donor verifier on four independently reopened real native source histories."""

import copy
import gzip
import hashlib
import json
from pathlib import Path
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import donor_witness as dw
import storage_tables

HERE = Path(__file__).resolve().parent
PATH = HERE / "enrollment/registered-source-observations.json.gz"
SHA = "0348f5cf1f9e2bc51278ec6d1a771fd47716a6cbdb8542a592022ed864920ce2"


class DonorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = PATH.read_bytes()
        assert hashlib.sha256(data).hexdigest() == SHA
        dataset = json.loads(gzip.decompress(data))
        assert dataset["source"] == [
            41303656721,
            124839568474,
            "8f633d8fc21e453f4c81d81588b6dcab125bfeae",
        ]
        cls.rows = dataset["cases"]

    def bind(self, row, role):
        return dw.register(row["training"], row["producer"], role, refnames=("ast-A", "ast-B"))

    def selected(self, row, role):
        return dw.check_processes(
            row["mapped"],
            (row["registered"], row["files"], role),
            Path(row["mapped"]["reference"]["path"]),
            row["sdk_driver"],
            row["compilers"],
        )

    def test_actual_two_sides_and_dirty_source(self):
        self.assertEqual(set(self.rows), {r + "/" + s for r in "ED" for s in ("clean", "dirty")})
        for key, row in self.rows.items():
            role, state = key.split("/")
            with self.subTest(role=role, state=state):
                self.assertEqual(self.bind(row, role), row["registered"])
                side = "Y" if role == "E" else "X"
                seen = self.selected(row, role)
                for owner in dw.OWN:
                    want = owner == "ruff_python_ast" or role == "E" or state == "dirty"
                    self.assertEqual(
                        set(seen[owner]),
                        {side + "/" + t for t in dw.donors.TABLES} if want else set(),
                    )

    def test_reused_disappeared_forged_or_wrong_revision(self):
        for name in ("lost", "retag", "wrong_source", "y_is_x", "old_x", "no_producer"):
            r = copy.deepcopy(self.rows["D/clean"])
            f, prior, last = r["training"]
            owner = dw.OWN[0]
            x = r["registered"][owner]["X_path"]
            y = r["registered"][owner]["Y_path"]
            if name == "lost":
                del last["sessions"][y]
            elif name == "retag":
                last["sessions"][x]["revision"] = "f" * 16
            elif name == "wrong_source":
                last["source"]["revision"] = "f" * 40
            elif name == "y_is_x":
                last["sessions"][x]["directory"] = last["sessions"][y]["directory"]
            elif name == "old_x":
                prior["sessions"][x] = last["sessions"][x]
            elif name == "no_producer":
                r["producer"] = [c for c in r["producer"] if c["name"] != owner]
            with self.subTest(case=name), self.assertRaises((ValueError, KeyError)):
                self.bind(r, "D")

    def test_wrong_fd_owner_driver_and_missing_event(self):
        for name in ("other_pid", "wrong_inode", "no_open", "wrong_map", "wrong_argv", "no_live"):
            r = copy.deepcopy(self.rows["D/dirty"])
            p = str(r["compilers"][0]["pid"])
            if name == "other_pid":
                r["files"]["events"][0]["pid"] = 1
            elif name == "wrong_inode":
                r["files"]["registered"][0]["ino"] += 1
            elif name == "no_open":
                r["files"]["events"] = []
            elif name == "wrong_map":
                r["mapped"]["actual"][p]["maps"][0] = r["mapped"]["actual"][p]["maps"][0].replace(
                    " r-xp ", " r--p "
                )
            elif name == "wrong_argv":
                r["mapped"]["actual"][p]["argv"].append("--foreign")
            elif name == "no_live":
                del r["mapped"]["actual"][p]
            with self.subTest(case=name), self.assertRaises((ValueError, KeyError)):
                self.selected(r, "D")

    def test_allocated_hardlinks_dirs_and_adjacent_locks(self):
        a = "target/debug/incremental/ast/h/s-1-old"
        b = "build/debug/incremental/ast/h/s-2-now"
        inode = [1, 4, 2, 0o100444, 8, 200]
        rows = {
            a: [1, 1, 1, 0o40700, 8, 404],
            b: [1, 2, 1, 0o40700, 8, 404],
            a + ".lock": [1, 3, 1, 0o100600, 0, 0],
            a + "/dep-graph.bin": inode,
            b + "/dep-graph.bin": inode,
        }
        obs = storage_tables.scan(rows)
        self.assertEqual(obs["total"], 3 * 4096)
        self.assertEqual(len(obs["sessions"]), 2)
        self.assertEqual(
            obs["tables"]["raw/dep-graph.bin"], dict(files=1, names=2, length=200, allocated=4096)
        )
        rows[a + "/ohm-build-dep-graph.bin"] = inode
        observed = storage_tables.scan(rows)
        self.assertEqual(
            observed["tables"]["raw+build-alias/dep-graph.bin"],
            dict(files=1, names=3, length=200, allocated=4096),
        )
        rows[b + "/dep-graph.bin"] = [*inode[:4], 0, 0]
        with self.assertRaises(ValueError):
            storage_tables.scan(rows)


if __name__ == "__main__":
    unittest.main()
