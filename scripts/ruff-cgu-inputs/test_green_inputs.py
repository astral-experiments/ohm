"""Exercise the read-only graph capture and its failure conditions before touching Ruff."""

import gzip
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import green_inputs


class CaptureTests(unittest.TestCase):
    def test_graphs_and_checkpoints_are_reopened_and_donors_are_hashed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / "out"
            store = out / "green-originals"
            store.mkdir(parents=True)
            for lane in ("ordinary-observed", "diagnostic"):
                work = root / lane
                inc = work / "target/incremental/id"
                session = inc / "ruff_workspace-123/s-123"
                session.mkdir(parents=True)
                (session / "dep-graph.bin").write_bytes(b"RSIC graph")
                (session / "ohm-build-dep-graph.bin").write_bytes(b"RSIC build")
                (session / "ohm-check-dep-graph.bin").write_bytes(b"RSIC check")
                (session / "work-products.bin").write_bytes(b"RSIC work")
                (session / "owner.o").write_bytes(b"object")
                for phase in ("B", "A"):
                    where = out / lane / phase
                    stage = where / "stage/ruff_workspace"
                    stage.mkdir(parents=True)
                    args = stage / "original.nul"
                    argv = [
                        "rustc",
                        "--crate-name",
                        "ruff_workspace",
                        "-C",
                        f"incremental={inc}",
                    ]
                    args.write_bytes(b"\0".join(arg.encode() for arg in argv) + b"\0")
                    if phase == "A":
                        previous = out / lane / "B/stage/ruff_workspace/original.nul"
                        green_inputs.capture(where, previous, work, store, "before")
                        (session / "owner.o").write_bytes(b"changed")
                    green_inputs.capture(where, args, work, store, "after")

            receipt = green_inputs.verify(out)
            self.assertEqual(len(receipt["graph_objects"]), 4)
            archived = [gzip.decompress(p.read_bytes()) for p in store.iterdir()]
            self.assertCountEqual(
                archived, [b"RSIC graph", b"RSIC build", b"RSIC check", b"RSIC work"]
            )
            captured = out / "diagnostic/A/green-inputs-before.json"
            contents = json.loads(captured.read_bytes())
            donor = next(
                r for r in contents["sessions"][0]["files"] if r["name"] == "owner.o"
            )
            self.assertEqual(donor["sha256"], hashlib.sha256(b"object").hexdigest())
            self.assertFalse(donor["stored"])
            donor["sha256"] = hashlib.sha256(b"other").hexdigest()
            captured.write_text(json.dumps(contents))
            with self.assertRaisesRegex(ValueError, "donors changed before A"):
                green_inputs.verify(out)

    def test_foreign_and_ambiguous_directories_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "elsewhere"
            parent.mkdir()
            arguments = [
                "rustc",
                "--crate-name",
                "ruff_workspace",
                "-C",
                f"incremental={parent}",
            ]
            with self.assertRaisesRegex(ValueError, "unowned incremental directory"):
                green_inputs.roots(arguments, root)
            with self.assertRaisesRegex(ValueError, "ambiguous incremental path"):
                green_inputs.roots(arguments + ["-C", f"incremental={parent}"], root)


if __name__ == "__main__":
    unittest.main()
