import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import smoke_test_compact as smoke


def archive(payload):
    return (b"!<arch>\n" + b"member.o/".ljust(16) + b"0".ljust(12)
            + b"0".ljust(6) * 2 + b"644".ljust(8) + str(len(payload)).encode().ljust(10)
            + b"`\n" + payload + b"\n" * (len(payload) % 2))


class CompactSmokeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        self.toolchain = self.root / "toolchain"
        self.marker = self.toolchain / "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/compact-artifacts-v1"
        self.marker.parent.mkdir(parents=True)
        self.manifest = {"bundled_tools": {"wild": {"source": {"revision": "a" * 40}}}}
        self.baseline = self.root / "defaults-target/debug/libohm_smoke.rlib"
        self.baseline.parent.mkdir(parents=True)
        self.baseline.write_bytes(archive(b"\x7fELFordinary"))

    def run_smoke(self, manifest=None, target="x86_64-unknown-linux-gnu"):
        smoke.smoke(self.manifest if manifest is None else manifest, target,
                    self.toolchain, self.root / "crate", self.root)

    def test_historical_releases_and_macos_skip(self):
        with patch.object(smoke.subprocess, "run") as run:
            self.run_smoke({"bundled_tools": {"wild": {"sha256": "b" * 64}}})
            self.run_smoke({})
            self.run_smoke(target="aarch64-apple-darwin")
            run.assert_not_called()

    def test_source_release_requires_exact_capability(self):
        with patch.object(smoke.subprocess, "run") as run:
            for contents in (None, b"wrong\n"):
                if contents is not None:
                    self.marker.write_bytes(contents)
                with self.assertRaisesRegex(ValueError, "capability marker"):
                    self.run_smoke()
            run.assert_not_called()

    def test_installed_compiler_run_and_archive_contract(self):
        self.marker.write_bytes(b"RCOBJ001\n")
        compact = self.root / "compact-target/debug/libohm_smoke.rlib"
        compact.parent.mkdir(parents=True)
        for payload, linker, error in ((b"RCOBJ001object", "Wild", None),
                                       (b"\x7fELFordinary", "Wild", "no compact archive"),
                                       (b"RCOBJ001object", "LLD", "not linked by Wild")):
            compact.write_bytes(archive(payload))
            with patch.object(smoke.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 0, stdout=linker)) as run:
                if error:
                    with self.assertRaisesRegex(ValueError, error):
                        self.run_smoke()
                else:
                    with patch.dict(os.environ, {"RUSTC_WRAPPER": "/unexpected-wrapper"}):
                        self.run_smoke()
                    command = run.call_args_list[0]
                    self.assertEqual(command.args[0][:3], [str(self.toolchain / "bin/cargo"),
                                                          "-Zohm-compact-artifacts=yes", "run"])
                    self.assertEqual(command.kwargs["env"]["RUSTC"], str(self.toolchain / "bin/rustc"))
                    self.assertNotIn("RUSTC_WRAPPER", command.kwargs["env"])
        self.baseline.write_bytes(archive(b"RCOBJ001unexpected"))
        with self.assertRaisesRegex(ValueError, "without the Cargo opt-in"):
            self.run_smoke()


if __name__ == "__main__":
    unittest.main()
