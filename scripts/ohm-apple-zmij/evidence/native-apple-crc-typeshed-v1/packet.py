"""Store an entire Actions artifact in a deterministic solid XZ archive for offline replay."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def add(tar, name, data):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def pack(source, expected, output):
    with source.open("rb") as f:
        assert hashlib.file_digest(f, "sha256").hexdigest() == expected
    with zipfile.ZipFile(source) as z, tarfile.open(output, "x:xz", preset=7) as tar:
        names = sorted(i.filename for i in z.infolist() if not i.is_dir())
        assert len(names) == len(set(names)) and z.testzip() is None
        assert "MANIFEST.json" not in names
        files = {}
        for name in names:
            data = z.read(name)
            if name.endswith(".gz"):
                data = gzip.decompress(data)
            files[name] = digest(data)
            add(tar, name, data)
        manifest = dict(source_zip_sha256=expected, decoded_members=files)
        add(tar, "MANIFEST.json", json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())


class Packet:
    """Provide the decoded artifact members under their original names without writing on disk."""

    def __init__(self, path, expected):
        self.members = {}
        with tarfile.open(path, "r|xz") as tar:
            for item in tar:
                assert item.isfile() and item.name not in self.members
                self.members[item.name] = tar.extractfile(item).read()
        manifest = json.loads(self.members.pop("MANIFEST.json"))
        assert manifest["source_zip_sha256"] == expected
        assert manifest["decoded_members"] == {k: digest(v) for k, v in self.members.items()}

    def read(self, name):
        return self.members[name]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("source_sha256")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    pack(args.source, args.source_sha256, args.output)
