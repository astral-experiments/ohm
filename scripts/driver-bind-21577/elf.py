"""Reproduce the registered local-binding image by its exact source-derived relocation ledger."""
import gzip
import hashlib
import json
import os
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
def sha(data):
    return hashlib.sha256(data).hexdigest()
def sections(raw):
    header = struct.unpack_from("<16sHHIQQQIHHHHHH", raw)
    assert header[0][:7] == b"\x7fELF\x02\x01\x01" and (header[1], header[2], header[11]) == (3, 62, 64)
    table = [struct.unpack_from("<IIQQQQIIQQ", raw, header[6] + i * 64) for i in range(header[12])]
    string = table[header[13]]
    names = raw[string[4]:string[4] + string[5]]
    return {names[t[0]:names.index(0, t[0])].decode(): t for t in table}, table
def produce(original, destination, layout=None, ledger=None):
    layout = layout or json.loads((HERE / "layout.json").read_bytes())
    compressed = (HERE / "rows.json.gz").read_bytes() if ledger is None else ledger
    assert sha(compressed) == layout["rows"]
    canonical = gzip.decompress(compressed)
    assert sha(canonical) == layout["uncompressed_rows"]
    rows = json.loads(canonical)
    raw = original.read_bytes()
    assert sha(raw) == layout["original"] and len(raw) == layout["bytes"]
    names, table = sections(raw)
    rel, dyn = names[".rela.dyn"], names[".dynsym"]
    string = table[dyn[6]]
    namestrings = raw[string[4]:string[4] + string[5]]
    records = list(struct.iter_unpack("<QQq", raw[rel[4]:rel[4] + rel[5]]))
    old = records.copy()
    pl = names[".rela.plt"]
    writes = sorted(x[0] for x in old + list(struct.iter_unpack("<QQq", raw[pl[4]:pl[4] + pl[5]])))
    assert len(writes) == 115272 and all(b - a >= 8 for a, b in zip(writes, writes[1:]))
    assert len(rows) == 8733 and len({r["name"] for r in rows}) == 7516
    assert len({r["i"] for r in rows}) == len(rows)
    for r in rows:
        i = r["i"]
        target, info, addend = records[i]
        sym, kind = divmod(info, 1 << 32)
        off, tag, vis, section, addr, _ = struct.unpack_from("<IBBHQQ", raw, dyn[4] + 24 * sym)
        name = namestrings[off:namestrings.index(0, off)].decode()
        assert (target, sym, kind, addend, addr, name) == (r["target"], r["symbol"], r["original_kind"], r["addend"], r["local_value"], r["name"])
        assert section and tag == 0x12 and vis == 0 and name.startswith("_R") and r["compiler_crates"] and kind in (1, 6)
        assert rel[4] + 24 * i == r["file"] and addr + addend == r["bound"]
        for label, value, flags in ((r["code_section"], addr + addend, 6), (r["slot_section"], target, 3)):
            s = names[label]
            assert s[2] & flags == flags and s[3] <= value < s[3] + s[5]
        records[i] = (target, 8, addr + addend)
    start = layout["positions"]["old_prefix"]
    count = start + len(rows)
    assert start == 100902 and count == 109635
    ordered = sorted(range(len(records)), key=lambda i: records[i][1] != 8)
    assert ordered[:start] == list(range(start))
    assert all(records[i][1] == 8 for i in ordered[:count]) and all(records[i][1] != 8 for i in ordered[count:])
    assert all(ordered[r["new_i"]] == r["i"] for r in rows)
    output = bytearray(raw)
    for j, i in enumerate(ordered):
        struct.pack_into("<QQq", output, rel[4] + 24*j, *records[i])
    field = layout["positions"]["count_field_file_offset"]
    assert struct.unpack_from("<QQ", raw, field - 8) == (0x6ffffff9, start)
    struct.pack_into("<Q", output, field, count)
    assert sha(output) == layout["prototype"] == "1e74533c72891d0c2b41ffdde1944ad0d4e8637309fdaa0bd14bfd471cbdbeb2"
    restored = bytearray(output)
    for i, row in enumerate(old):
        struct.pack_into("<QQq", restored, rel[4]+24*i, *row)
    struct.pack_into("<Q", restored, field, start)
    assert restored == raw
    assert not destination.exists()
    destination.write_bytes(output)
    destination.chmod(original.stat().st_mode & 0o777)
    return {"stock": sha(raw), "prototype": sha(output), "rows": len(rows), "symbols": 7516, "bytes": len(raw), "mode": destination.stat().st_mode & 0o777, "old_prefix": start, "new_prefix": count, "round_trip": sha(restored)}
