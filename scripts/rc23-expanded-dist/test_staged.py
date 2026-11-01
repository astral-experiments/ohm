"""Exercise the stock release assembler and the staged receipt reader using tiny QA files."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify

class Staging(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.release = Path(cls.temp.name)
        manifest = verify.coordinator(COORDINATOR)
        shutil.copyfile(COORDINATOR / "release/bootstrap.toml", cls.release / "bootstrap.toml")
        for target in verify.TARGETS:
            stem = f"{verify.TOOLCHAIN}-{target}"
            archive = cls.release / (stem + ".tar.gz")
            archive.write_bytes(b"QA packaging control " + target.encode())
            provenance = cls.release / (stem + "-provenance.json")
            provenance.write_text(json.dumps({
                "schema_version": 1, "target": target, "toolchain": verify.TOOLCHAIN,
                "coordinator": {"repository": "astral-experiments/ohm", "revision": verify.COORDINATOR},
                "manifest": {"path": verify.MANIFEST, "sha256": verify.MANIFEST_SHA},
                "sources": {key: {"revision": value} for key, value in verify.SOURCES.items()},
                "bundled_tools": manifest["bundled_tools"] if "linux" in target else {},
            }))
            for entry in (archive, provenance):
                entry.with_name(entry.name + ".sha256").write_text(verify.digest(entry) + "  " + entry.name + "\n")
        subprocess.run(["bash", COORDINATOR / "scripts/assemble-release.sh",
                        COORDINATOR / verify.MANIFEST, cls.release, verify.TOOLCHAIN], check=True)

    def platform(self, target):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        output = Path(temp.name)
        names = {"ohm-installer.sh", "SHA256SUMS", "bootstrap.toml", verify.TOOLCHAIN + ".json"}
        for src in self.release.iterdir():
            if src.name in names or target in src.name:
                shutil.copyfile(src, output / src.name)
        return output

    def test_assembled_layouts(self):
        for target in verify.TARGETS:
            p = self.platform(target)
            result = verify.staged(COORDINATOR, p, target)
            self.assertEqual(result["archive_bytes"], (p / f"{verify.TOOLCHAIN}-{target}.tar.gz").stat().st_size)
            self.assertEqual(len(result["global_checksums"]), 8)
            self.assertEqual(len(result["assets"]), 7)

    def test_unexpected_or_changed_checkout_file(self):
        target = verify.TARGETS[0]
        p = self.platform(target)
        bootstrap = p / "bootstrap.toml"
        bootstrap.unlink()
        with self.assertRaisesRegex(ValueError, "staged asset roster"):
            verify.staged(COORDINATOR, p, target)
        bootstrap.symlink_to(COORDINATOR / "release/bootstrap.toml")
        with self.assertRaisesRegex(ValueError, "regular file"):
            verify.staged(COORDINATOR, p, target)
        bootstrap.unlink()
        bootstrap.write_bytes(b"different\n")
        with self.assertRaisesRegex(ValueError, "changed coordinator bootstrap"):
            verify.staged(COORDINATOR, p, target)
        (p / "extra-archive").touch()
        with self.assertRaisesRegex(ValueError, "staged asset roster"):
            verify.staged(COORDINATOR, p, target)

    def test_wrong_component_with_valid_checksums(self):
        target = verify.TARGETS[1]
        p = self.platform(target)
        name = f"{verify.TOOLCHAIN}-{target}-provenance.json"
        record = p / name
        good_hash = verify.digest(record)
        record.write_bytes(record.read_bytes().replace(verify.SOURCES["rust"].encode(),
                           b"c034422aa64926e9a8c519f23074a8187e279f09"))
        new_hash = verify.digest(record)
        self.assertNotEqual(good_hash, new_hash)
        (p / (name + ".sha256")).write_text(new_hash + "  " + name + "\n")
        sums = p / "SHA256SUMS"
        sums.write_text(sums.read_text().replace(good_hash, new_hash))
        with self.assertRaisesRegex(ValueError, "source or tool provenance"):
            verify.staged(COORDINATOR, p, target)

    def test_corrupt_archive_and_missing_platform(self):
        target = verify.TARGETS[0]
        p = self.platform(target)
        path = p / f"{verify.TOOLCHAIN}-{target}.tar.gz"
        original = path.read_bytes()
        path.write_bytes(original + b"x")
        with self.assertRaisesRegex(ValueError, "staged asset bytes"):
            verify.staged(COORDINATOR, p, target)
        path.write_bytes(original)
        sums = p / "SHA256SUMS"
        sums.write_text("\n".join(line for line in sums.read_text().splitlines() if verify.TARGETS[1] not in line) + "\n")
        with self.assertRaisesRegex(ValueError, "global checksum list"):
            verify.staged(COORDINATOR, p, target)

if __name__ == "__main__":
    COORDINATOR = Path(sys.argv.pop(1)).resolve()
    main()
