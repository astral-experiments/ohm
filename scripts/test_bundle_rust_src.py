import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from bundle_rust_src import bundle


class BundleRustSrcTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.extended = self.directory / "rust-1.98.1-dev-aarch64-apple-darwin.tar.gz"
        self.sources = self.directory / "rust-src-1.98.1-dev.tar.gz"
        self.output = self.directory / "ohm-1.98.1-3-aarch64-apple-darwin.tar.gz"
        self.root = self.extended.name.removesuffix(".tar.gz")
        self.toolchain_files = {
            "components": b"rustc\nrust-std-aarch64-apple-darwin\n",
            "rust-installer-version": b"3\n",
            "git-commit-hash": b"a" * 40 + b"\n",
            "install.sh": b"#!/bin/sh\nexit 0\n",
            "rustc/bin/rustc": b"compiler payload",
            "rust-std-aarch64-apple-darwin/lib/rustlib/target/lib/libstd.rlib": b"stdlib",
        }
        self.source_files = {
            "components": b"rust-src\n",
            "rust-installer-version": b"3\n",
            "git-commit-hash": b"a" * 40 + b"\n",
            "install.sh": b"source-only installer must not replace the combined installer",
            "rust-src/manifest.in": b"dir:lib/rustlib/src/rust\n",
            "rust-src/lib/rustlib/src/rust/library/core/src/lib.rs": b"core source",
            # Exercise extended tar headers, which also store the original path.
            "rust-src/lib/rustlib/src/rust/library/"
            + "long/" * 30
            + "lib.rs": b"dependency",
        }
        self.write_archive(self.extended, self.toolchain_files)
        self.write_archive(self.sources, self.source_files)

    @staticmethod
    def write_archive(path, files):
        root = path.name.removesuffix(".tar.gz")
        with tarfile.open(path, "w:gz") as archive:
            directory = tarfile.TarInfo(root)
            directory.type = tarfile.DIRTYPE
            archive.addfile(directory)
            for name, data in files.items():
                info = tarfile.TarInfo(f"{root}/{name}")
                info.size = len(data)
                info.mode = 0o755 if name == "install.sh" else 0o644
                info.mtime = 1234567890
                archive.addfile(info, io.BytesIO(data))

    def test_bundles_installable_component_without_changing_existing_payloads(self):
        bundle(self.extended, self.sources, self.output)
        with tarfile.open(self.output) as archive:
            expected = dict(self.toolchain_files)
            expected["components"] += b"rust-src\n"
            expected.update(
                (name, data)
                for name, data in self.source_files.items()
                if name.startswith("rust-src/")
            )
            actual = {
                member.name: archive.extractfile(member).read()
                for member in archive
                if member.isfile()
            }
            self.assertEqual(
                actual, {f"{self.root}/{name}": data for name, data in expected.items()}
            )
            self.assertEqual(archive.getmember(f"{self.root}/install.sh").mode, 0o755)
            self.assertEqual(
                archive.getmember(f"{self.root}/install.sh").mtime, 1234567890
            )
        first = self.output.read_bytes()
        bundle(self.extended, self.sources, self.output)
        self.assertEqual(first, self.output.read_bytes())

    def test_rejects_mismatched_sources_without_replacing_output(self):
        for name, value in [
            ("git-commit-hash", b"b" * 40 + b"\n"),
            ("rust-installer-version", b"4\n"),
            ("components", b"rustc\n"),
        ]:
            with self.subTest(name=name):
                files = self.source_files | {name: value}
                self.write_archive(self.sources, files)
                self.output.write_bytes(b"existing artifact")
                with self.assertRaises(ValueError):
                    bundle(self.extended, self.sources, self.output)
                self.assertEqual(self.output.read_bytes(), b"existing artifact")

    def test_rejects_duplicate_source_component(self):
        self.toolchain_files["components"] += b"rust-src\n"
        self.write_archive(self.extended, self.toolchain_files)
        with self.assertRaisesRegex(ValueError, "already contains rust-src"):
            bundle(self.extended, self.sources, self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
