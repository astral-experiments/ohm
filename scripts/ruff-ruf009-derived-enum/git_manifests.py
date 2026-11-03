"""Verify the four typed Git manifest paths against their actual locked commits, also off-host."""

import base64
import functools
import hashlib
import json
from pathlib import Path
import tomllib

HERE = Path(__file__).resolve().parent


@functools.cache
def records():
    return json.loads((HERE / "locked-manifests.json").read_bytes())


def object_bytes(proof, kind, oid):
    raw = base64.b64decode(proof["objects"][oid], validate=True)
    assert hashlib.sha1(kind.encode() + b" " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == oid
    return raw


def tree_entry(raw, requested):
    pos = 0
    entries = {}
    while pos < len(raw):
        end = raw.index(0, pos)
        mode, name = raw[pos:end].split(b" ", 1)
        assert mode in (b"40000", b"100644", b"100755", b"120000", b"160000")
        assert name and name not in entries and b"/" not in name and len(raw[end + 1 : end + 21]) == 20
        entries[name] = (mode, raw[end + 1 : end + 21].hex())
        pos = end + 21
    assert pos == len(raw)
    return entries[requested.encode()]


def verify(pid, path, home, revision, name, physical, proof=None):
    data = records() if proof is None else proof
    full = path.relative_to(home / "git/checkouts")
    assert len(full.parts) >= 3 and ".." not in full.parts and path.name == "Cargo.toml"
    case = data["packages"][pid]
    relative = Path(*full.parts[2:])
    assert case == {"revision": revision, "relative": relative.as_posix()} and revision.startswith(
        full.parts[1]
    )
    commit = object_bytes(data, "commit", revision)
    header = commit.split(b"\n", 1)[0]
    assert header.startswith(b"tree ") and len(header) == 45
    oid = header[5:].decode()
    for i, part in enumerate(relative.parts):
        mode, oid = tree_entry(object_bytes(data, "tree", oid), part)
        assert mode in ((b"100644", b"100755") if i + 1 == len(relative.parts) else (b"40000",))
    manifest = object_bytes(data, "blob", oid)
    assert tomllib.loads(manifest.decode())["package"]["name"] == name
    if physical:
        assert path.is_file() and not path.is_symlink() and path.read_bytes() == manifest
    return oid
