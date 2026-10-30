"""Keep every complete returned CLI byte using content-addressed 256 KiB chunks."""
import gzip
import json

from study import compress_bytes, digest, need, save


def blocks(body):
    for offset in range(0, len(body), 256 * 1024):
        b = body[offset:offset+256*1024]
        yield digest(b), b


def keep(root, body):
    bucket = root / "receipts" / "objc2-cli-images"
    parts = bucket / "chunks"
    parts.mkdir(parents=True, exist_ok=True)
    step = 256 * 1024
    chunks = []
    for key, chunk in blocks(body):
        path = parts / (key + ".gz")
        if not path.exists():
            compress_bytes(path, chunk)
        chunks.append(key)
    idx = {"sha256": digest(body), "bytes": len(body), "chunk_size": step, "chunks": chunks}
    index = bucket / (idx["sha256"] + ".json")
    if index.is_file():
        need(json.loads(index.read_bytes()) == idx, "inconsistent Mach-O archive index")
    else:
        save(index, idx)
    # Validate once at independent readback and before accepting any source phase.
    return idx["sha256"]


def reopen(read, raw):
    base = "objc2-cli-images/"
    item = json.loads(read(base + raw + ".json"))
    need(item["sha256"] == raw and item["chunk_size"] == 256*1024 and item["bytes"] > 0,
         "invalid complete CLI archive")
    output = bytearray()
    for key in item["chunks"]:
        b = gzip.decompress(read(base + "chunks/" + key + ".gz"))
        need(digest(b) == key and len(b) == min(256*1024, item["bytes"] - len(output)), "altered CLI chunk")
        output.extend(b)
    need(len(output) == item["bytes"] and digest(output) == raw, "incomplete returned CLI")
    return bytes(output)
