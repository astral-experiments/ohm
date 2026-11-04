"""Retain every byte of the submitted original Actions ZIPs, sharing repeated compressed spans."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from bits import expand


def sha(data):
    return hashlib.sha256(data).hexdigest()


def add_original(path, registration, blobs, store, groups):
    with path.open("rb") as source:
        assert hashlib.file_digest(source, "sha256").hexdigest() == registration["sha256"]
        length = path.stat().st_size
        assert length == registration["bytes"]
        pieces = []

        def retain(start, stop, group=None):
            assert 0 <= start <= stop <= length
            if start == stop:
                return
            source.seek(start)
            data = source.read(stop - start)
            assert len(data) == stop - start
            digest = sha(data)
            if digest not in blobs:
                store.seek(0, 2)
                blobs[digest] = [store.tell(), len(data)]
                store.write(data)
            else:
                offset, n = blobs[digest]
                store.seek(offset)
                assert n == len(data) and store.read(n) == data
            if group is not None:
                groups.setdefault(digest, group)
            pieces.append(digest)

        previous = 0
        with ZipFile(path) as archive:
            assert archive.testzip() is None
            products = {}
            for name in archive.namelist():
                fields = name.split("/")
                if len(fields) == 4 and fields[3] == "result.json" and fields[1] in ("check", "build"):
                    result = json.loads(archive.read(name))
                    suffix = ".rmeta" if fields[1] == "check" else ".rlib"
                    key = "products/" + result["product_sha256"] + suffix
                    products.setdefault(key, (fields[0], fields[1], result["commit"]))
            for member in sorted(archive.infolist(), key=lambda m: m.header_offset):
                start = member.header_offset
                source.seek(start)
                header = source.read(30)
                assert header[:4] == b"PK\x03\x04" and start >= previous
                name_bytes, extra_bytes = struct.unpack_from("<HH", header, 26)
                body = start + 30 + name_bytes + extra_bytes
                retain(previous, body)
                previous = body + member.compress_size
                retain(body, previous, products.get(member.filename))
            retain(previous, length)
    return pieces


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", type=Path)
    parser.add_argument("input", type=Path, help="Original Actions ZIPs in RUN/BLOCK.zip")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    registry = json.loads(args.registry.read_bytes())
    blobs, records, groups = {}, [], {}
    with tempfile.TemporaryFile() as store, tempfile.TemporaryFile() as encoded, tempfile.TemporaryDirectory() as scratch:
        for study in registry["studies"]:
            for block, owner in study["originals"].items():
                path = args.input / str(study["run"]) / (block + ".zip")
                parts = add_original(path, owner, blobs, store, groups)
                records.append({"run": study["run"], "block": block, "pieces": parts})
        bases = {}
        packed = {}
        for key, (start, length) in blobs.items():
            store.seek(start)
            raw = store.read(length)
            assert sha(raw) == key
            group = groups.get(key)
            base = bases.get(group) if group is not None else None
            encoded_bytes = raw
            form = None
            if base is not None:
                def delta(ref, value):
                    return subprocess.check_output(["zstd", "-q", "-5", "--patch-from="+str(ref),
                        "--stream-size="+str(len(value)), "-c", "-"], input=value, stderr=subprocess.DEVNULL)
                ref = Path(scratch)/base
                patch = delta(ref, raw)
                if len(patch) < len(encoded_bytes):
                    encoded_bytes, form = patch, "bytes"
                if len(encoded_bytes) > len(raw)//100:
                    bit_ref = Path(scratch)/(base+".bits")
                    if not bit_ref.exists():
                        bit_ref.write_bytes(expand(ref.read_bytes()))
                    patch = delta(bit_ref, expand(raw))
                    if len(patch) < len(encoded_bytes):
                        encoded_bytes, form = patch, "bits"
                if form is None:
                    base = None
            elif group is not None:
                (Path(scratch)/key).write_bytes(raw)
                bases[group] = key
            packed[key] = [encoded.tell(), len(encoded_bytes), length, base, form]
            encoded.write(encoded_bytes)
        index = {"blobs": packed, "records": records, "registry": sha(args.registry.read_bytes())}
        with ZipFile(args.output, "x", ZIP_DEFLATED, compresslevel=9) as packet:
            packet.writestr("index.json", json.dumps(index, sort_keys=True, separators=(",", ":")))
            encoded.seek(0)
            with packet.open("bytes.bin", "w", force_zip64=True) as output:
                shutil.copyfileobj(encoded, output, 1024*1024)
    print(f"Retained {len(records)} complete originals in {args.output.stat().st_size:,} bytes.")


if __name__ == "__main__":
    assert __debug__
    main()
