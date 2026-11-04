"""Losslessly combine the eight original GitHub Actions ZIPs, sharing repeated compressed spans."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from zipfile import ZIP_DEFLATED, ZipFile

here = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("originals", type=Path, help="Directory with RUN/LABEL.zip for each record")
parser.add_argument("output", type=Path)
args = parser.parse_args()
assert __debug__

slabs = bytearray()
blobs = {}
index = {"runs": [], "blobs": blobs}
def piece(raw):
    key = hashlib.sha256(raw).hexdigest()
    if key in blobs:
        offset, size = blobs[key]
        assert slabs[offset:offset + size] == raw
    else:
        blobs[key] = [len(slabs), len(raw)]
        slabs.extend(raw)
    return key

registry = json.loads((here / "originals.json").read_bytes())
for phase in ("pilot", "confirm"):
    study = registry["studies"][phase]
    group = {"run": study["run"], "head": study["head"], "records": []}
    index["runs"].append(group)
    for row in study["records"]:
        path = args.originals / str(study["run"]) / (row["label"] + ".zip")
        raw = path.read_bytes()
        assert len(raw) == row["original_bytes"]
        assert hashlib.sha256(raw).hexdigest() == row["original_sha256"]
        parts = []
        end = 0
        with ZipFile(path) as z:
            for m in sorted(z.infolist(), key=lambda m: m.header_offset):
                start = m.header_offset
                assert start >= end and raw[start:start + 4] == b"PK\x03\x04"
                name_size, extra_size = struct.unpack_from("<HH", raw, start + 26)
                body = start + 30 + name_size + extra_size
                parts.append(piece(raw[end:body]))
                end = body + m.compress_size
                if end != body:
                    parts.append(piece(raw[body:end]))
            parts.append(piece(raw[end:]))
        group["records"].append({**row, "pieces": parts})
with ZipFile(args.output, "x", ZIP_DEFLATED, compresslevel=9) as z:
    z.writestr("index.json", json.dumps(index, sort_keys=True, separators=(",", ":")))
    z.writestr("bytes.bin", slabs)
print(f"Saved {args.output.stat().st_size:,} bytes in {len(blobs):,} distinct spans.")
