"""Host-independent preflight. These fixtures do not count as platform smoke results."""

import os
import json
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
        for role in ("packaged", "fourfix", "static-fourfix"):
            for residual in (False, True):
                p = stage(self.outer, self.helper, self.root / (role + str(residual)), role, residual)
                code = p.read_text()
                self.assertEqual(code.count(SWAP), int(role != "packaged"))
                self.assertEqual(code.count(GATE), int(not residual))
                self.assertEqual(sha(p.parent / self.helper.name), CFG["helper_sha256"])
                if not residual:
                    self.assertEqual(sha(p), expected_outer(role))
                if role != "packaged":
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

    def test_authenticated_bootstrap_and_native_archive_refusals(self):
        from static_cargo import policy, releases, zproof

        self.assertEqual(policy()["tool_rs_git_blob"], "17e71f71bb3bc0d41939440fd28e62adf6a8aa5e")
        healthy = "  0x1 (NEEDED) Shared library: [libc.so.6]"
        self.assertEqual(releases(healthy, "libc.so.6 => /lib/libc.so.6 (0x1)"), ["libc.so.6"])
        with self.assertRaises(ValueError):
            releases(healthy + "\\n  0x1 (NEEDED) Shared library: [libz.so.1]", "libc")
        with self.assertRaises(ValueError):
            releases(healthy, "libz.so.1 => /lib/libz.so.1 (0x123)")
        with self.assertRaises(ValueError):
            zproof(
                [
                    {
                        "reason": "build-script-executed",
                        "package_id": "registry+x#libz-sys@1",
                        "linked_libs": ["z"],
                        "out_dir": str(self.root),
                    }
                ],
                self.root,
            )

    def test_real_proxy_directory_for_both_registry_commands(self):
        from worktree import registry_path
        from unittest.mock import patch

        with patch("shutil.which", return_value="/isolated/.cargo/bin/cargo"):
            self.assertEqual(
                registry_path("/extra/vendor/path:/isolated/.cargo/bin:/usr/bin"),
                "/isolated/.cargo/bin:/usr/bin:/bin",
            )
        with patch("shutil.which", return_value=None), self.assertRaises(ValueError):
            registry_path("/unknown/vendor/path")

    def test_old_dynamic_cargo_does_not_satisfy_new_static_role(self):
        from installed import replacement_digest

        with self.assertRaises(ValueError):
            replacement_digest(self.root, "aarch64-apple-darwin", "static-fourfix")
        with self.assertRaises(FileNotFoundError):
            replacement_digest(self.root, "x86_64-unknown-linux-gnu", "static-fourfix")

    def test_successful_build_is_insufficient_if_file_identity_or_freshness_changes(self):
        from media import save
        from supplement import worktree

        f = "/private/shared/debug/build/registries/unit/libitoa-cafe.rlib"
        ident = [4, 7, 100, "a" * 64]
        owners = {"PATH": "/private/proxies:/usr/bin:/bin", "parent_assets": {f: ident}}
        proof = {
            "parent": 42,
            "child": [42, 73],
            "wrong_type": "E0277",
            "shared_itoa": [[f], [f]],
            "observed_identities": [{f: ident[:]}, {f: ident[:]}],
        }
        cli = ["cargo", "+" + CFG["release"]]
        itoa = {"target": {"name": "itoa"}, "fresh": True, "filenames": [f]}
        events = [
            {
                "argv": cli + ["build", "--locked", "--offline", "--message-format=json"],
                "status": 0,
                "stdout": json.dumps(itoa),
            }
            for _ in range(2)
        ]
        events.extend({"argv": ["/private/reader"], "status": 0, "stdout": str(i)} for i in [42, 73, 42])
        diag = {
            "message": {
                "code": {"code": "E0277"},
                "spans": [{"is_primary": True, "file_name": "src/main.rs"}],
            }
        }
        events.append({"argv": cli + ["check"], "status": 101, "stdout": json.dumps(diag)})
        save(self.root / "worktree-commands.json", events)
        save(self.root / "worktree-registry.json", owners)
        save(self.root / "worktree.json", proof)
        self.assertEqual(worktree(self.root)["native_outputs"], ["42", "73", "42"])
        proof["observed_identities"][1][f][1] += 1
        save(self.root / "worktree.json", proof)
        with self.assertRaisesRegex(ValueError, "shared file"):
            worktree(self.root)
        proof["observed_identities"][1][f][1] -= 1
        save(self.root / "worktree.json", proof)
        events[1]["stdout"] = json.dumps(itoa | {"fresh": False})
        save(self.root / "worktree-commands.json", events)
        with self.assertRaisesRegex(ValueError, "stale child"):
            worktree(self.root)

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
        self.assertIn("inputs.previous == '41249054242'", workflow)
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
