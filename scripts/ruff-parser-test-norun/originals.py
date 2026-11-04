"""Losslessly pack and restore authenticated CI ZIPs with shared native entries."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import tempfile
import zipfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with path.open("rb") as data:
        return hashlib.file_digest(data, "sha256").hexdigest()


def checked_put(path, data):
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"refusing to replace different bytes in {path}")
    else:
        path.write_bytes(data)


def split(source, meta, payloads, cohort):
    number = str(int(meta["id"]))
    path = source / (number + ".zip")
    raw = path.read_bytes()
    assert len(raw) == meta["size_in_bytes"] and "sha256:" + sha(raw) == meta["digest"]
    shell = bytearray()
    regions = []
    cursor = 0
    with zipfile.ZipFile(path) as z:
        assert len(z.infolist()) == len(set(z.namelist()))
        for member in sorted(z.infolist(), key=lambda m: m.header_offset):
            matched = re.fullmatch(r"native/([0-9a-f]{64})\.zst", member.filename)
            if not matched:
                continue
            header = member.header_offset
            assert raw[header:header + 4] == b"PK\x03\x04" and member.compress_type == zipfile.ZIP_DEFLATED
            name_len, extra_len = struct.unpack_from("<HH", raw, header + 26)
            assert raw[header + 30:header + 30 + name_len].decode() == member.filename
            start = header + 30 + name_len + extra_len
            end = start + member.compress_size
            assert cursor <= start < end <= len(raw)
            shell.extend(raw[cursor:start])
            chunk = raw[start:end]
            key = sha(chunk)
            checked_put(payloads / key, chunk)
            regions.append({"prefix": start - cursor, "bytes": len(chunk), "compressed_sha256": key,
                            "native_sha256": matched.group(1)})
            cursor = end
    shell.extend(raw[cursor:])
    checked_put(cohort / (number + ".record"), shell)
    return {"record_sha256": sha(shell), "record_bytes": len(shell), "regions": regions}


def pack(source, store, label):
    payloads = store / "payloads"
    cohort = store / label
    payloads.mkdir(parents=True, exist_ok=True)
    cohort.mkdir(parents=True, exist_ok=True)
    official = (source / "artifacts.json").read_bytes()
    artifacts = json.loads(official)["artifacts"]
    index = {str(m["id"]): split(source, m, payloads, cohort) for m in artifacts}
    checked_put(cohort / "artifacts.json", official)
    checked_put(cohort / "index.json", (json.dumps(index, indent=2, sort_keys=True) + "\n").encode())


def restore(store, label, dest):
    cohort = store / label
    dest.mkdir(parents=True, exist_ok=True)
    official = (cohort / "artifacts.json").read_bytes()
    artifacts = json.loads(official)["artifacts"]
    index = json.loads((cohort / "index.json").read_bytes())
    assert set(index) == {str(m["id"]) for m in artifacts}
    for m in artifacts:
        number = str(int(m["id"]))
        row = index[number]
        record = (cohort / (number + ".record")).read_bytes()
        assert sha(record) == row["record_sha256"] and len(record) == row["record_bytes"]
        cursor = 0
        final = dest / (number + ".zip")
        if final.exists():
            assert final.stat().st_size == m["size_in_bytes"] and "sha256:" + file_sha(final) == m["digest"]
            continue
        with tempfile.TemporaryDirectory(dir=dest) as temp:
            pending = Path(temp) / "assembled.zip"
            with pending.open("xb") as stream:
                for region in row["regions"]:
                    key = region["compressed_sha256"]
                    assert re.fullmatch("[0-9a-f]{64}", key)
                    piece = (store / "payloads" / key).read_bytes()
                    assert sha(piece) == key and len(piece) == region["bytes"]
                    end = cursor + region["prefix"]
                    assert cursor <= end <= len(record)
                    stream.write(record[cursor:end]);stream.write(piece)
                    cursor = end
                stream.write(record[cursor:])
            assert pending.stat().st_size == m["size_in_bytes"] and "sha256:" + file_sha(pending) == m["digest"]
            pending.rename(final)
    checked_put(dest / "artifacts.json", official)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    a = sub.add_parser("pack")
    a.add_argument("source",type=Path);a.add_argument("store",type=Path);a.add_argument("label",choices=["pilot","confirmation"])
    b = sub.add_parser("restore")
    b.add_argument("store",type=Path);b.add_argument("label",choices=["pilot","confirmation"]);b.add_argument("destination",type=Path)
    args = p.parse_args()
    if args.action == "pack":
        pack(args.source,args.store,args.label)
    else:
        restore(args.store,args.label,args.destination)


if __name__ == "__main__":
    main()
