import hashlib
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "prepare_wild", pathlib.Path(__file__).with_name("prepare-wild.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PrepareWildTests(unittest.TestCase):
    def archive(self, unsafe=False):
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:gz") as archive:
            for name in module.FILES:
                member = tarfile.TarInfo(f"wild-linker-0.10.0-{module.TARGET}/{name}")
                if unsafe and name == "wild":
                    member.type = tarfile.SYMTYPE
                    member.linkname = "/tmp/elsewhere"
                    archive.addfile(member)
                else:
                    data = b"fixture"
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
        return payload.getvalue()

    def prepare(self, payload, checksum=None):
        manifest = {"bundled_tools": {"wild": {
            "version": "0.10.0",
            "sha256": checksum or hashlib.sha256(payload).hexdigest(),
        }}}
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = pathlib.Path(temporary.name) / "wild"
        with patch.object(module.urllib.request, "urlopen", return_value=io.BytesIO(payload)):
            return module.prepare(manifest, module.TARGET, output)

    def test_payload_and_licenses(self):
        output = self.prepare(self.archive())
        self.assertEqual(set(p.name for p in output.iterdir()), set(module.FILES))
        self.assertEqual((output / "wild").stat().st_mode & 0o777, 0o755)
        self.assertEqual((output / "LICENSE-MIT").stat().st_mode & 0o777, 0o644)

    def test_checksum_and_archive_links(self):
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.prepare(self.archive(), "0" * 64)
        with self.assertRaisesRegex(ValueError, "unsafe"):
            self.prepare(self.archive(unsafe=True))

    def test_old_manifests_and_other_platforms_do_not_download(self):
        with patch.object(module.urllib.request, "urlopen") as download:
            self.assertIsNone(module.prepare({}, module.TARGET, "/unused"))
            self.assertIsNone(module.prepare({"bundled_tools": {"wild": {}}}, "aarch64-apple-darwin", "/unused"))
            download.assert_not_called()

    def source_fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = pathlib.Path(temporary.name)
        checkout = root / "source"
        (checkout / "compact-artifact").mkdir(parents=True)
        (checkout / "compact-artifact/Cargo.toml").write_text("fixture")
        for name in module.FILES[1:]:
            (checkout / name).write_text("fixture license")
        for args in (
            ["init", "--quiet"], ["add", "."],
            ["-c", "user.name=Wild fixture", "-c", "user.email=fixture@example.invalid",
             "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "-m", "Source fixture"],
            ["remote", "add", "origin", module.SOURCE_REPOSITORY],
        ):
            subprocess.run(["git", "-C", str(checkout), *args], check=True)
        revision = subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True,
        ).strip()
        wild = {"version": "0.10.0", "source": {
            "repository": module.SOURCE_REPOSITORY, "revision": revision,
            "rust_toolchain": "1.98.0",
        }}
        return root, checkout, wild

    def test_source_build_uses_pin_and_records_binary(self):
        root, checkout, wild = self.source_fixture()
        tools = root / "tools"
        tools.mkdir()
        rustup = tools / "rustup"
        rustup.write_text("""#!/usr/bin/env python3
import pathlib, sys
assert sys.argv[1:3] == ['run', '1.98.0'], sys.argv
if sys.argv[3:5] == ['cargo', 'build']:
    assert '--locked' in sys.argv and '--release' in sys.argv
    output = pathlib.Path(sys.argv[sys.argv.index('--target-dir') + 1])
    target = sys.argv[sys.argv.index('--target') + 1]
    binary = output / target / 'release/wild'
    binary.parent.mkdir(parents=True)
    binary.write_text('#!/bin/sh\\necho "Wild 0.10.0 fixture"\\n')
    binary.chmod(0o755)
elif sys.argv[3:5] == ['cargo', '-V']:
    print('cargo 1.98.0 fixture')
elif sys.argv[3:5] == ['rustc', '-vV']:
    print('rustc 1.98.0 fixture')
else:
    raise AssertionError(sys.argv)
""")
        rustup.chmod(0o755)
        with patch.dict(os.environ, {"PATH": f"{tools}{os.pathsep}{os.environ['PATH']}"}):
            output = module.prepare(
                {"bundled_tools": {"wild": wild}}, module.TARGET, root / "payload", checkout,
            )
        self.assertEqual(set(p.name for p in output.iterdir()), {
            *module.FILES, "provenance.json", module.COMPACT_CAPABILITY,
        })
        self.assertEqual((output / module.COMPACT_CAPABILITY).read_bytes(), module.COMPACT_FORMAT)
        provenance = json.loads((output / "provenance.json").read_text())
        self.assertEqual(provenance["binary_sha256"], hashlib.sha256((output / "wild").read_bytes()).hexdigest())
        self.assertEqual(provenance["rustc_version"], "rustc 1.98.0 fixture")
        self.assertEqual(module.verify_source(wild, checkout), checkout.resolve())

    def test_source_rejects_wrong_revision_dirty_tree_and_wrong_repository(self):
        root, checkout, wild = self.source_fixture()
        with self.assertRaisesRegex(ValueError, "requires a source checkout"):
            module.prepare({"bundled_tools": {"wild": wild}}, module.TARGET, root / "payload")
        pinned = wild["source"]["revision"]
        wild["source"]["revision"] = "1" * 40
        with self.assertRaisesRegex(ValueError, "revision mismatch"):
            module.verify_source(wild, checkout)
        wild["source"]["revision"] = pinned
        untracked = checkout / "injected.rs"
        untracked.write_text("unexpected input")
        with self.assertRaisesRegex(ValueError, "not clean"):
            module.verify_source(wild, checkout)
        untracked.unlink()
        subprocess.run(["git", "-C", str(checkout), "remote", "set-url", "origin",
                        "https://github.com/example/wild"], check=True)
        with self.assertRaisesRegex(ValueError, "repository mismatch"):
            module.verify_source(wild, checkout)


if __name__ == "__main__":
    unittest.main()
