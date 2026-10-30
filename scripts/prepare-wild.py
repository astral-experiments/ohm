#!/usr/bin/env python3
"""Fetch the checksum-pinned Wild payload used by a Linux release."""

import hashlib
import io
import json
import pathlib
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.request

TARGET = "x86_64-unknown-linux-gnu"
FILES = ("wild", "LICENSE-APACHE", "LICENSE-MIT")


def prepare(manifest, target, destination):
    wild = manifest.get("bundled_tools", {}).get("wild")
    if target != TARGET or wild is None:
        return None
    version = wild["version"]
    checksum = wild["sha256"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("invalid Wild version")
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("invalid Wild SHA-256")
    name = f"wild-linker-{version}-{TARGET}"
    url = f"https://github.com/wild-linker/wild/releases/download/{version}/{name}.tar.gz"
    with urllib.request.urlopen(url, timeout=120) as response:
        payload = response.read()
    if hashlib.sha256(payload).hexdigest() != checksum:
        raise ValueError("Wild archive checksum mismatch")

    destination = pathlib.Path(destination)
    destination = destination.parent.resolve() / destination.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Extract only the expected regular files; do not follow archive links or
    # interpret paths supplied by the archive as filesystem destinations.
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        staged = pathlib.Path(temporary) / "wild"
        staged.mkdir()
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            members = archive.getmembers()
            for filename in FILES:
                matches = [m for m in members if m.name == f"{name}/{filename}"]
                if len(matches) != 1 or not matches[0].isfile():
                    raise ValueError(f"missing or unsafe Wild archive member: {filename}")
                with archive.extractfile(matches[0]) as source:
                    with (staged / filename).open("wb") as output:
                        shutil.copyfileobj(source, output)
                (staged / filename).chmod(0o755 if filename == "wild" else 0o644)
        # Fail on an existing destination instead of reusing unverified bytes.
        if destination.is_symlink() or destination.exists():
            raise FileExistsError(f"Wild destination already exists: {destination}")
        staged.rename(destination)
    return destination


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("usage: prepare-wild.py MANIFEST TARGET DESTINATION")
    result = prepare(json.loads(pathlib.Path(sys.argv[1]).read_text()), *sys.argv[2:])
    if result is not None:
        print(result)
