"""Verify byte-reversible held programs, including detection of an altered last chunk."""
import gzip
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cli_images import blocks, reopen
from study import digest


def check(body):
    raw = digest(body)
    store = {}
    names = []
    for key, value in blocks(body):
        names.append(key)
        store["objc2-cli-images/chunks/"+key+".gz"] = gzip.compress(value, compresslevel=1, mtime=0)
    index = "objc2-cli-images/"+raw+".json"
    store[index] = json.dumps({"sha256":raw, "chunk_size":256*1024, "bytes":len(body), "chunks":names}).encode()
    assert reopen(store.__getitem__, raw) == body
    key = "objc2-cli-images/chunks/"+names[-1]+".gz"
    store[key] = gzip.compress(b"altered", mtime=0)
    try:
        reopen(store.__getitem__, raw)
    except RuntimeError:
        pass
    else:
        raise AssertionError("accepted mutated full CLI")
    return raw, len(names)


if __name__ == "__main__":
    raw, count = check(bytes(range(256))*3072 + b"one last byte")
    print(raw, count)
