import hashlib
import importlib.util
import io
import pathlib
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

    def test_build_checked_source_in_pinned_image(self):
        payload = b"source archive"
        executable = b"#!/bin/sh\necho 'Wild 0.11.0 non-git-build'\n"
        source = {
            "revision": "a" * 40,
            "builder_sha256": "b" * 64,
            "binary_sha256": hashlib.sha256(executable).hexdigest(),
        }
        wild = {"version": "0.11.0", "sha256": hashlib.sha256(payload).hexdigest(), "source": source}
        manifest = {"bundled_tools": {"wild": wild}}

        def build(command, **kwargs):
            self.assertIn("docker.io/library/rust@sha256:" + "b" * 64, command)
            mount = command[command.index("--mount") + 1]
            work = pathlib.Path(mount.removeprefix("type=bind,src=").removesuffix(",dst=/work"))
            self.assertEqual((work / "source.tar.gz").read_bytes(), payload)
            if "patch_sha256" in source:
                self.assertEqual((work / "source.patch").read_bytes(), b"patch fixture")
            staged = work / "wild"
            staged.mkdir()
            (staged / "wild").write_bytes(executable)
            (staged / "wild").chmod(0o755)

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(module, "PATCH_DIRECTORY", pathlib.Path(temporary)),
            patch.object(module.urllib.request, "urlopen") as download,
            patch.object(module.subprocess, "run", side_effect=build) as docker,
            patch.object(module.subprocess, "check_output", return_value="Wild 0.11.0 non-git-build"),
        ):
            destination = pathlib.Path(temporary) / "staged"
            download.return_value = io.BytesIO(payload)
            self.assertEqual(module.prepare(manifest, module.TARGET, destination), destination)
            download.assert_called_once_with(
                "https://codeload.github.com/wild-linker/wild/tar.gz/" + "a" * 40, timeout=120
            )
            digest = hashlib.sha256(b"patch fixture").hexdigest()
            source["patch_sha256"] = digest
            patch_file = pathlib.Path(temporary) / f"{digest}.patch"
            patch_file.write_bytes(b"patch fixture")
            download.return_value = io.BytesIO(payload)
            patched = pathlib.Path(temporary) / "patched"
            self.assertEqual(module.prepare(manifest, module.TARGET, patched), patched)
            patch_file.write_bytes(b"corrupt patch")
            download.return_value = io.BytesIO(payload)
            with self.assertRaisesRegex(ValueError, "patch checksum"):
                module.prepare(manifest, module.TARGET, patched)
            del source["patch_sha256"]
            source["binary_sha256"] = "0" * 64
            download.return_value = io.BytesIO(payload)
            with self.assertRaisesRegex(ValueError, "binary checksum"):
                module.prepare(manifest, module.TARGET, destination)
            download.return_value = io.BytesIO(b"other source")
            with self.assertRaisesRegex(ValueError, "archive checksum"):
                module.prepare(manifest, module.TARGET, destination)
            self.assertEqual(docker.call_count, 3)

    def test_old_manifests_and_other_platforms_do_not_download(self):
        with patch.object(module.urllib.request, "urlopen") as download:
            self.assertIsNone(module.prepare({}, module.TARGET, "/unused"))
            self.assertIsNone(module.prepare({"bundled_tools": {"wild": {}}}, "aarch64-apple-darwin", "/unused"))
            download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
