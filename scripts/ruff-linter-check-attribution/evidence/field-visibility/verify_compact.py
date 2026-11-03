"""Check the permanent compact control packet and execute its original and independently linked clients."""

import hashlib
import json
from pathlib import Path
import sys
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import verify_scope_native


def file_sha(path):
    with path.open("rb") as body:
        return hashlib.file_digest(body, "sha256").hexdigest()


def main():
    path = HERE / "raw-controls.tar.xz"
    assert (
        file_sha(path)
        == "396b523c8c457ae36849a24237602ef27517dc30f8cdaf76aead068bf3ad3302"
    )
    report_path = HERE / "report.json"
    assert (
        file_sha(report_path)
        == "259267f38548f7580aa3bee37bb32d1e08ac2976c87a21bd1d356e0541bc82c1"
    )
    report = json.loads(report_path.read_bytes())
    with tarfile.open(path, "r:xz") as tar, tempfile.TemporaryDirectory() as tmp:
        raw = {member.name: tar.extractfile(member).read() for member in tar}

        class Packet:
            def read(self, name):
                return raw[name]

        for role in ("P", "C"):
            prefix = f"inline-{role}/"
            folder = Path(tmp) / role
            folder.mkdir()
            native = verify_scope_native.verify(Packet(), prefix, folder)
            assert native == report["roles"][role]["native"]
            stages = ("scope-old", "scope-edit", "scope-empty-new")
            metadata = []
            for stage in stages:
                inventory = json.loads(raw[prefix + stage + "/cargo.json"])["metadata"]
                metadata.append({tuple(row[:3]): row[3] for row in inventory})
            assert metadata[0].keys() == metadata[1].keys() == metadata[2].keys()
            assert len(metadata[0]) == 255
            dirty = sorted(
                key[1] for key in metadata[1] if metadata[0][key] != metadata[1][key]
            )
            assert dirty == native["raw_rustc"]
            clean = sum(value == metadata[2][key] for key, value in metadata[1].items())
            assert clean == {"P": 227, "C": 255}[role]
            print(
                role,
                "actual compiler processes",
                dirty,
                "clean metadata",
                clean,
                "/ 255",
            )
        assert (
            json.loads(raw["adt-rsic-upgrade/terminal.json"])
            == report["format_crossover"]
        )


if __name__ == "__main__":
    main()
