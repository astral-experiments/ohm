"""Offline controls for the builder's exact source and compiler transport."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build
import capsule as c


class Protocol(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cap = self.root / "capsule"
        self.obj = self.cap / "objects"
        self.obj.mkdir(parents=True)
        signed = {
            p: [p, 0o755, len(p), hashlib.sha256(p.encode()).hexdigest()]
            for p in ("bin/cargo", "lib/rustlib/" + c.HOST + "/bin/wild-ld/ld.bfd")
        }
        self.addCleanup(patch.stopall)
        patch.dict(c.REG, {"signed_cargo": {"members": signed}}).start()
        for path, (_member, mode, size, key) in signed.items():
            (self.obj / key).write_bytes(path.encode())
        for role, d in c.REG["roles"].items():
            files = {}
            for n in (
                "bin/rustc",
                "bin/rustdoc",
                "lib/librustc_driver-test.so",
                "lib/libLLVM-test.so",
                *(
                    "lib/rustlib/" + c.HOST + "/lib/lib" + n + "-f00.rlib"
                    for n in ("core", "std", "test", "proc_macro")
                ),
            ):
                b = (n + (role if "driver" in n else "")).encode()
                key = hashlib.sha256(b).hexdigest()
                (self.obj / key).write_bytes(b)
                files[n] = [key, len(b), 0o755 if n in ("bin/rustc", "bin/rustdoc") else 0o644]
            r = {
                "role": role,
                "commit": d["revision"],
                "compiler_tree": d["compiler"],
                "files": files,
                **{name: "0" * 64 for name in ("stage0_rustc", "stage0_cargo", "stage0_source")},
            }
            c.save(self.cap / (role + ".json"), r)
        self.receipt()
        c.seal(self.cap)

    def receipt(self):
        p = self.cap / "qualified.json"
        p.write_text(
            json.dumps(
                {
                    "schema": "ohm-remat-rustc-capsule-v1",
                    "registration": c.sha(c.HERE / "registration.json"),
                    "manifests": {r: c.sha(self.cap / (r + ".json")) for r in ("P", "C")},
                }
            )
        )

    def alter(self, fn):
        p = self.cap / "C.json"
        d = json.loads(p.read_bytes())
        fn(d)
        p.write_text(json.dumps(d))
        self.receipt()

    def test_no_duplicate_storage_or_changed_mode(self):
        baseline = {p: p.stat().st_nlink for p in self.obj.iterdir()}
        out = self.root / "compiler"
        m = c.reopen(self.cap, out)
        self.assertEqual(m["schema"], "ohm-matched-rustcs-v1")
        for name, key in m["arms"]["normal"]["files"].items():
            if key == m["arms"]["defer"]["files"][name]:
                self.assertTrue((out / "normal" / name).samefile(out / "defer" / name))
                self.assertTrue((out / "normal" / name).samefile(self.obj / key))
                self.assertEqual((self.obj / key).stat().st_nlink, baseline[self.obj / key] + 2)
        with self.assertRaises(FileExistsError):
            c.reopen(self.cap, out)
        with self.assertRaisesRegex(ValueError, "overlapping"):
            c.reopen(self.cap, self.cap / "nested")

    def test_bundle_registration(self):
        b = c.HERE / "candidate.bundle"
        self.assertEqual(c.sha(b), c.REG["bundle"]["sha256"])
        header = b.read_bytes().split(b"\n\n", 1)[0].decode().splitlines()
        self.assertEqual(header[1].split()[0], "-" + c.REG["bundle"]["prerequisite"])
        self.assertEqual(header[2], c.REG["roles"]["C"]["revision"] + " " + c.REG["bundle"]["branch"])
        self.assertEqual(len(header), 3)

    def test_immutable_workflow_helper_matches_registration(self):
        workflow = (HERE.parents[1] / ".github/workflows/ci.yml").read_text()
        self.assertIn("ref: " + c.REG["kit"]["commit"] + "\n        path: packed\n", workflow)

    def test_mutated_common_llvm(self):
        self.alter(lambda d: d["files"]["lib/libLLVM-test.so"].__setitem__(0, "a" * 64))
        with self.assertRaisesRegex(ValueError, "different standard library"):
            c.admit(self.cap)

    def test_no_op_candidate(self):
        parent = json.loads((self.cap / "P.json").read_bytes())
        k = "lib/librustc_driver-test.so"
        self.alter(lambda d: d["files"].__setitem__(k, parent["files"][k]))
        with self.assertRaisesRegex(ValueError, "unchanged compiler"):
            c.admit(self.cap)

    def test_unsafe_path(self):
        self.alter(lambda d: d["files"].__setitem__("../escape", d["files"]["bin/rustc"]))
        with self.assertRaisesRegex(ValueError, "unexpected compiler member"):
            c.admit(self.cap)

    def test_tampered_manifest(self):
        with (self.cap / "P.json").open("a") as f:
            print(" ", file=f)
        with self.assertRaisesRegex(ValueError, "changed compiler manifest"):
            c.admit(self.cap)

    def test_wrong_object_mode(self):
        f = next(self.obj.iterdir())
        f.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "invalid physical compiler object"):
            c.admit(self.cap)

    def test_symlink(self):
        f = next(self.obj.iterdir())
        f.rename(self.root / "not-owned")
        f.symlink_to(self.root / "not-owned")
        with self.assertRaisesRegex(ValueError, "invalid physical compiler object"):
            c.admit(self.cap)

    def test_extra_object(self):
        (self.obj / ("f" * 64)).write_text("different")
        with self.assertRaisesRegex(ValueError, "unregistered"):
            c.admit(self.cap)


def source_control(clean):
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "rust"
        subprocess.run(["git", "init", "-q", "--bare", repo], check=True)
        common = Path(build.git(clean, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        (repo / "objects/info/alternates").write_text(str(common / "objects") + "\n")
        prerequisite = c.REG["bundle"]["prerequisite"]
        (repo / "shallow").write_text(prerequisite + "\n")
        build.git(repo, "update-ref", "refs/heads/base", prerequisite)
        build.bundle(repo)
        print(
            "Exact parent, child, compiler trees, worktree blobs, sole candidate ref and direct-parent bundle passed."
        )


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--rust-source":
        source_control(Path(sys.argv[2]).resolve(strict=True))
    else:
        unittest.main()
