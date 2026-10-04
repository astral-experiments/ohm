#!/usr/bin/env python3
"""Restore checksum-addressed raw captures, preserving their original bytes."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tarfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("archive", type=Path)
parser.add_argument("manifest", type=Path)
parser.add_argument("destination", type=Path)
args = parser.parse_args()
manifest = json.loads(args.manifest.read_text())
with args.archive.open("rb") as source:
    assert hashlib.file_digest(source, "sha256").hexdigest() == manifest["sha256"]
assert not args.destination.exists() or not any(args.destination.iterdir())
args.destination.mkdir(parents=True, exist_ok=True)
with tarfile.open(args.archive, "r:gz") as archive:
    index_bytes = archive.extractfile("index.json").read()
    assert hashlib.sha256(index_bytes).hexdigest() == manifest["index_sha256"]
    index = json.loads(index_bytes)
    assert index["format"] == "sha256-content-addressed-v1"
    assert len(index["files"]) == manifest["files"]
    restored = {}
    for row in index["files"]:
        relative = PurePosixPath(row["path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        destination = args.destination.joinpath(*relative.parts)
        assert not destination.exists()
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = row["sha256"]
        if digest in restored:
            os.link(restored[digest], destination)
        else:
            member = archive.getmember(f"blobs/{digest}")
            assert member.isfile() and member.size == row["size_bytes"]
            content = archive.extractfile(member).read()
            assert hashlib.sha256(content).hexdigest() == digest
            destination.write_bytes(content)
            restored[digest] = destination
        assert destination.stat().st_size == row["size_bytes"]
print(json.dumps({"files": len(index["files"]), "unique_files": len(restored), "original_bytes_verified": True}))
