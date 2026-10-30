"""Storage and receipt helpers shared with the existing archive verifier."""
import gzip
import hashlib
import json
from pathlib import Path

ROOT_NAMES = ("target", "build")


def require(condition, message):
    if not condition:
        raise RuntimeError(str(message))


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def publish(path, obj):
    data = (json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if path.suffix == ".gz":
        data = gzip.compress(data, compresslevel=2, mtime=0)
    with path.open("xb") as out:
        out.write(data)
