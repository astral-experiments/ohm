#!/usr/bin/env python3
"""Exercise rustc-dev release matching with tiny archives, without compiling Rust."""

import hashlib
import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "stage_rustc_dev", Path(__file__).with_name("stage-rustc-dev.py")
)
packaging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packaging)


class RustcDevTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ohm-rustc-dev-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.toolchain = "ohm-1.98.0-3"
        self.target = "x86_64-unknown-linux-gnu"
        self.driver = "librustc_driver-a123.so"
        self.combined = self.root / "compiler.tar.gz"
        self.development = self.root / "development.tar.gz"
        self.provenance = self.root / "provenance.json"
        self.output = self.root / "output"

    def archive(self, path, members):
        with tarfile.open(path, "w:gz") as archive:
            for name, contents in members:
                entry = tarfile.TarInfo(name)
                if contents is None:
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = "elsewhere"
                    archive.addfile(entry)
                else:
                    entry.size = len(contents)
                    archive.addfile(entry, io.BytesIO(contents))

    def fixture(
        self,
        *,
        contents=b"post-BOLT driver",
        duplicate=False,
        metadata=True,
        extra_members=(),
    ):
        compiler_prefix = f"rust-1.98.0-dev-{self.target}/rustc/lib"
        dev_prefix = f"rustc-dev-1.98.0-dev-{self.target}/rustc-dev/lib/rustlib/{self.target}/lib"
        self.archive(
            self.combined, [(f"{compiler_prefix}/{self.driver}", b"post-BOLT driver")]
        )
        members = [(f"{dev_prefix}/{self.driver}", contents)]
        if duplicate:
            members.append(members[0])
        if metadata:
            members.extend(
                (f"{dev_prefix}/lib{crate}-a123.rmeta", b"metadata")
                for crate in ("rustc_session", "rustc_driver_impl")
            )
        dev_root = f"rustc-dev-1.98.0-dev-{self.target}"
        private_source = "lib/rustlib/rustc-src/rust/compiler/private.rs"
        members.extend(
            [
                (f"{dev_root}/components", b"rustc-dev\n"),
                (f"{dev_root}/install.sh", b"#!/bin/sh\n"),
                (f"{dev_root}/unexpected.rs", b"private root source"),
                (f"{dev_root}/builder-config", b"private build settings"),
                (f"{dev_root}/git-commit-info", b"private source provenance"),
                (f"{dev_root}/rustc-dev/{private_source}", b"private compiler source"),
                (
                    f"{dev_root}/rustc-dev/manifest.in",
                    f"file:{private_source}\n".encode(),
                ),
            ]
        )
        members.extend(extra_members)
        self.archive(self.development, members)
        self.provenance.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "toolchain": self.toolchain,
                    "target": self.target,
                    "sources": {"rust": {"revision": "a" * 40}},
                }
            )
        )

    def stage(self):
        return packaging.stage(
            self.toolchain,
            self.target,
            self.combined,
            self.development,
            self.provenance,
            self.output,
        )

    def test_matching_linux_and_macos_archives_preserve_provenance_and_checksums(self):
        for target, suffix in [
            ("x86_64-unknown-linux-gnu", ".so"),
            ("aarch64-apple-darwin", ".dylib"),
        ]:
            with self.subTest(target=target):
                self.target = target
                self.driver = "librustc_driver-a123" + suffix
                self.fixture()
                name, driver_hash = self.stage()
                self.assertEqual(name, self.driver)
                self.assertEqual(
                    driver_hash, hashlib.sha256(b"post-BOLT driver").hexdigest()
                )
                archive_name = f"{self.toolchain}-rustc-dev-{target}.tar.gz"
                provenance_name = f"{self.toolchain}-rustc-dev-{target}-provenance.json"
                with tarfile.open(self.output / archive_name) as archive:
                    names = archive.getnames()
                    self.assertFalse(any("rustc-src" in name for name in names))
                    for excluded in (
                        "unexpected.rs",
                        "builder-config",
                        "git-commit-info",
                    ):
                        self.assertFalse(
                            any(name.endswith("/" + excluded) for name in names)
                        )
                    root = f"rustc-dev-1.98.0-dev-{target}/rustc-dev"
                    driver_path = f"{root}/lib/rustlib/{target}/lib/{self.driver}"
                    self.assertEqual(
                        archive.extractfile(driver_path).read(), b"post-BOLT driver"
                    )
                    manifest = (
                        archive.extractfile(f"{root}/manifest.in").read().decode()
                    )
                    libraries = [
                        name.removeprefix(root + "/")
                        for name in names
                        if name.startswith(root + "/lib/")
                    ]
                    self.assertEqual(
                        manifest.splitlines(),
                        [f"file:{name}" for name in sorted(libraries)],
                    )
                with tarfile.open(self.development) as original:
                    self.assertTrue(
                        any("rustc-src" in name for name in original.getnames())
                    )
                provenance = json.loads((self.output / provenance_name).read_text())
                self.assertEqual(provenance["sources"]["rust"]["revision"], "a" * 40)
                self.assertEqual(provenance["compiler_driver"]["sha256"], driver_hash)
                self.assertFalse(provenance["compiler_sources_included"])
                self.assertEqual(
                    provenance["compiler_archive"]["sha256"],
                    packaging.digest(self.combined),
                )
                for artifact in [archive_name, provenance_name]:
                    self.assertEqual(
                        (self.output / (artifact + ".sha256")).read_text(),
                        f"{packaging.digest(self.output / artifact)}  {artifact}\n",
                    )

    def test_driver_mismatch_fails_before_staging(self):
        self.fixture(contents=b"pre-BOLT driver")
        with self.assertRaisesRegex(ValueError, "final optimized compiler"):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_duplicate_or_linked_driver_fails(self):
        for options in [{"duplicate": True}, {"contents": None}]:
            with self.subTest(options=options):
                self.fixture(**options)
                with self.assertRaises(ValueError):
                    self.stage()
                self.assertFalse(self.output.exists())

    def test_missing_metadata_fails(self):
        self.fixture(metadata=False)
        with self.assertRaisesRegex(ValueError, "compiler metadata"):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_unsafe_archive_paths_fail_before_staging(self):
        prefix = f"rustc-dev-1.98.0-dev-{self.target}/rustc-dev/lib/rustlib/{self.target}/lib"
        for name in ("/private.rs", f"{prefix}/../private.rs"):
            with self.subTest(name=name):
                self.fixture(extra_members=[(name, b"private source")])
                with self.assertRaisesRegex(ValueError, "unsafe archive member"):
                    self.stage()
                self.assertFalse(self.output.exists())

    def test_duplicate_retained_library_fails(self):
        prefix = f"rustc-dev-1.98.0-dev-{self.target}/rustc-dev/lib/rustlib/{self.target}/lib"
        member = (f"{prefix}/librustc_middle-a123.rmeta", b"metadata")
        self.fixture(extra_members=[member, member])
        with self.assertRaisesRegex(ValueError, "duplicate retained"):
            self.stage()

    def test_wrong_target_provenance_fails(self):
        self.fixture()
        value = json.loads(self.provenance.read_text())
        value["target"] = "aarch64-apple-darwin"
        self.provenance.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "provenance"):
            self.stage()
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
