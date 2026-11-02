"""Read module-level retired instruction intervals from measureme's v9 wire."""
from functools import lru_cache
import json
import struct


def intervals(raw):
    version = struct.pack("<I", 9)
    assert raw[:8] == b"MMPD" + version
    streams = [bytearray(), bytearray(), bytearray()]
    pos = 8
    while pos < len(raw):
        kind, length = struct.unpack_from("<BI", raw, pos)
        pos += 5
        assert kind < 3 and 0 < length <= len(raw) - pos
        streams[kind].extend(raw[pos:pos + length])
        pos += length
    events, strings, index = streams
    assert [s[:8] for s in streams] == [tag + version for tag in (b"MMES", b"MMSD", b"MMSI")]
    offsets = dict(struct.iter_unpack("<QQ", index[8:]))

    @lru_cache(None)
    def word(key):
        offset = offsets.get(key) if key < 100000003 else key - 100000003
        if offset is None:
            return b"<unresolved>"
        assert 8 <= offset < len(strings)
        result = bytearray()
        while strings[offset] != 255:
            if strings[offset] == 254:
                result.extend(word(struct.unpack_from("<Q", strings, offset + 1)[0]))
                offset += 9
            else:
                result.append(strings[offset])
                offset += 1
        return bytes(result)

    metadata = json.loads(word(100000001))
    records = []
    for kind, key, thread, lo, hi, top in struct.iter_unpack("<QQIIII", events[8:]):
        start = lo | ((top & 0xffff0000) << 16)
        end = hi | ((top & 0xffff) << 32)
        if end < 0xfffffffffffe:
            assert end >= start
            records.append((word(kind).decode(), word(key).decode().split("\x1e"), thread, start, end))
    return metadata, records


def module_counts(raw, units):
    metadata, records = intervals(raw)
    assert "instructions:u" in json.dumps(metadata["counter"]), metadata["counter"]
    methods = ("LLVM_module_codegen_emit_obj", "LLVM_module_optimize", "LLVM_module_codegen")
    counts = {method: {} for method in methods}
    for kind, parts, thread, start, end in records:
        if parts[0] in counts:
            assert kind == "GenericActivity" and len(parts) == 2, (kind, parts)
            hits = [unit for unit in units if unit in parts[1]]
            assert len(hits) == 1 and hits[0] not in counts[parts[0]], parts
            assert end > start
            counts[parts[0]][hits[0]] = {"thread":thread, "start":start, "end":end, "instructions":end-start}
    assert set(counts["LLVM_module_codegen_emit_obj"]) == set(units), counts
    assert set(counts["LLVM_module_optimize"]) == set(units)
    return {"counter":metadata["counter"], "events":counts}
