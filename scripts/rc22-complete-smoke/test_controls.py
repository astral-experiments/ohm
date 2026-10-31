"""Host-independent preflight. These fixtures do not count as platform smoke results."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media import CFG, HERE, REPO, archive_origin, sha, unpack
from reopen import complete, expected_outer, observed
from run import AFTER, GATE, SWAP, stage, stopped_at_link


class Controls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.outer = HERE.parent / "smoke-test-release.sh"
        self.helper = HERE.parent / "smoke-test-relink.sh"

    def test_unmodified_outer_and_scoped_substitute(self):
        self.assertEqual(stage(self.outer, self.helper, self.root / "unused", "packaged", False), self.outer)
        for role in ("packaged", "fourfix"):
            for residual in (False, True):
                p = stage(self.outer, self.helper, self.root / (role + str(residual)), role, residual)
                code = p.read_text()
                self.assertEqual(code.count(SWAP), int(role == "fourfix"))
                self.assertEqual(code.count(GATE), int(not residual))
                self.assertEqual(sha(p.parent / self.helper.name), CFG["helper_sha256"])
                if not residual:
                    self.assertEqual(sha(p), expected_outer(role))
                if role == "fourfix":
                    self.assertIn(AFTER + SWAP, code)

    def test_edited_helper_fails_closed(self):
        f = self.root / "changed"
        f.write_bytes(self.helper.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "unregistered"):
            stage(self.outer, f, self.root / "out", "packaged", False)

    def test_actual_bash_exit_classification(self):
        stub = self.root / "smoke-test-relink.sh"
        outer = self.root / "smoke-test-release.sh"
        for status, after, expected in [(7, ":", True), (0, "false", False), (0, ":", False)]:
            stub.write_text(f"exit {status}\n")
            outer.write_text(
                "set -eu\ntrap 'rm -rf \"$TMPDIR/ohm-smoke.unit\"' EXIT\n"
                'bash "$TMPDIR/smoke-test-relink.sh" ohm-1.99.0-22 "$TMPDIR/relink"\n' + after + "\n"
            )
            script = (
                "PS4='+QA "
                + "$"
                + "{BASH_SOURCE[0]:-none}:"
                + "$"
                + "{LINENO}: '\nset -ex\nsource "
                + str(outer)
            )
            p = subprocess.run(
                ["bash", "-c", script], env=dict(os.environ, TMPDIR=str(self.root)), capture_output=True
            )
            self.assertEqual(
                bool(p.returncode and stopped_at_link(p.stderr, outer)), expected, p.stderr.decode()
            )

    def test_residual_never_passes_as_full(self):
        (self.root / "full").mkdir()
        (self.root / "outcome.json").write_text('{"role":"packaged","statuses":{"full":7,"residual":0}}')
        with self.assertRaisesRegex(ValueError, "partial"):
            complete(self.root, "packaged", {}, "x86_64-unknown-linux-gnu", "ignored")
        with self.assertRaisesRegex(ValueError, "missing original"):
            observed("+QA /only/drive.sh:8: echo lld analyzer diagnostics", "aarch64-apple-darwin")

    def test_zip_duplicates_and_external_names(self):
        out = self.root / "out"
        out.mkdir()
        for members in (["dup", "dup"], ["../outside"], ["good", "extra"]):
            z = self.root / "original.zip"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(z, "w") as f:
                    for n in members:
                        f.writestr(n, b"fixture")
            with self.assertRaises(ValueError):
                unpack(z, out, ["../outside"] if members == ["../outside"] else [members[0]])
        self.assertFalse((self.root / "outside").exists())

    def test_wrong_official_origin_type_head_and_step(self):
        spec = CFG["global"]
        run = {
            "id": spec["run"],
            "head_sha": spec["head"],
            "repository": {"full_name": REPO},
            "head_repository": {"full_name": REPO},
            "event": "workflow_dispatch",
            "run_attempt": 1,
            "conclusion": "failure",
            "path": ".github/workflows/release.yml",
            "head_branch": "main",
        }
        step = "Retain global release assets"
        job = {
            "id": spec["job"],
            "run_id": spec["run"],
            "head_sha": spec["head"],
            "run_attempt": 1,
            "conclusion": "success",
            "steps": [{"name": step, "conclusion": "success"}],
        }
        art = {
            "id": spec["artifact"],
            "name": spec["name"],
            "size_in_bytes": spec["bytes"],
            "expired": False,
            "digest": "sha256:" + spec["sha256"],
            "workflow_run": {"id": spec["run"], "head_sha": spec["head"]},
        }
        archive_origin(spec, run, job, art, step)
        for item, changes in [
            (run, {"path": ".github/workflows/ci.yml"}),
            (job, {"run_attempt": 2}),
            (art, {"expired": True}),
            (art, {"digest": "sha256:" + "0" * 64}),
            (art, {"workflow_run": {"id": spec["run"], "head_sha": "0" * 40}}),
            (job, {"steps": [{"name": step, "conclusion": "failure"}]}),
        ]:
            inputs = [v | changes if v is item else v for v in (run, job, art)]
            with self.assertRaises(ValueError):
                archive_origin(spec, *inputs, step)

    def test_checked_source_and_readonly_dispatch(self):
        root = HERE.parents[1]
        workflow = (root / ".github/workflows/ci.yml").read_text()
        self.assertIn("contents: read", workflow)
        self.assertIn("actions: read", workflow)
        self.assertNotIn("environment:", workflow)
        self.assertNotIn("permissions: write", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertEqual(workflow.count("GH_TOKEN:"), 2)
        self.assertIn("inputs.reviewed_head == github.sha", workflow)
        self.assertIn("inputs.source == '41237680370'", workflow)
        expected = {HERE / "SHA256SUMS"}
        for row in (HERE / "SHA256SUMS").read_text().splitlines():
            digest, path = row.split("  ", 1)
            file = root / path
            self.assertTrue(file.is_file())
            self.assertEqual(sha(file), digest, path)
            expected.add(file)
        self.assertTrue({root / ".github/workflows/ci.yml", self.outer, self.helper} <= expected)
        self.assertTrue({p for p in HERE.iterdir() if p.is_file()} <= expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
