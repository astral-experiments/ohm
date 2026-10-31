"""Reopen an original OHMO1 stream, its canonical name, its internal owner and its ELF bytes."""

import gzip
import hashlib
import json
import re
import subprocess
import zlib


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def dump(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def unpack(raw, filename, session):
    m = re.fullmatch(r"ohm-packed-object-([a-z0-9]+\.o)-blake3=([0-9a-f]{64})", filename)
    need(m is not None, "invalid packed object filename")
    d = zlib.decompressobj()
    data = d.decompress(raw, 8 << 20)
    need(d.eof and not d.unconsumed_tail and not d.unused_data, "malformed or oversized object frame")
    prefix = b"OHMO1" + session.rsplit("-", 1)[0].encode() + b"\0" + m[1].encode() + b"\0"
    n = len(prefix)
    need(data.startswith(prefix) and len(data) > n + 8, "object header/owner differs")
    body = data[n + 8 :]
    need(
        len(body) == int.from_bytes(data[n : n + 8], "little")
        and body[:7] == b"\x7fELF\x02\x01\x01"
        and body[16:20] == b"\x01\x00\x3e\x00",
        "not a complete x86_64 native object",
    )
    h = subprocess.check_output(["b3sum", "--no-names"], input=body).decode().strip()
    need(h == m[2], "raw object digest differs from canonical filename")
    return m[1], body


def escrow(directory, name, body):
    directory.mkdir(exist_ok=True)
    dst = directory / (name + ".gz")
    if not dst.exists():
        dst.write_bytes(gzip.compress(body, compresslevel=1, mtime=0))
    need(gzip.decompress(dst.read_bytes()) == body, "different escrowed bytes")
    return digest(body)
