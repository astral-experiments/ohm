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

    def test_old_manifests_and_other_platforms_do_not_download(self):
        with patch.object(module.urllib.request, "urlopen") as download:
            self.assertIsNone(module.prepare({}, module.TARGET, "/unused"))
            self.assertIsNone(module.prepare({"bundled_tools": {"wild": {}}}, "aarch64-apple-darwin", "/unused"))
            download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
