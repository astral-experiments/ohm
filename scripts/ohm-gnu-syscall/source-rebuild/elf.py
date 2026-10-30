"""Inventory the checked Cargo ELF and locate its vendored OpenSSL build timestamp."""
import hashlib
import re
import struct


def digest(data):
    return hashlib.sha256(data).hexdigest()


def describe(data):
    assert data[:7] == b"\x7fELF\x02\x01\x01" and struct.unpack_from("<H", data, 18)[0] == 62
    p_offset, s_offset = struct.unpack_from("<QQ", data, 32)
    p_size, p_count, s_size, s_count, names = struct.unpack_from("<HHHHH", data, 54)
    assert p_size == 56 and s_size == 64 and 0 < names < s_count
    sections = [struct.unpack_from("<IIQQQQIIQQ", data, s_offset + i * s_size) for i in range(s_count)]
    names_table = data[sections[names][4]:][:sections[names][5]]
    entries = {}
    for i, (name, kind, flags, addr, offset, size, link, info, align, entsize) in enumerate(sections):
        key = names_table[name:].split(b"\x00", 1)[0].decode("ascii")
        assert key not in entries
        body = data[offset:offset+size] if kind != 8 else b""
        assert kind == 8 or len(body) == size
        entries[key] = {"header": s_offset + i * s_size, "type": kind, "flags": flags, "address": addr,
                        "offset": offset, "size": size, "link": link, "info": info, "align": align,
                        "entry_size": entsize, "sha256": digest(body) if kind != 8 else None}
    segments = []
    for i in range(p_count):
        kind, flags, start, vaddr, paddr, size, memory, align = struct.unpack_from("<IIQQQQQQ", data, p_offset + i * p_size)
        body = data[start:start+size]
        assert len(body) == size
        segments.append({"type": kind, "flags": flags, "offset": start, "virtual_address": vaddr,
                         "physical_address": paddr, "size": size, "mem_size": memory, "align": align,
                         "sha256": digest(body)})
    clock, = list(re.finditer(rb"built on: [A-Z][a-z]{2} [A-Z][a-z]{2} [ 0-9][0-9] [0-9:]{8} [0-9]{4} UTC(?=\x00)", data))
    stamp = {"offset": clock.start(), "bytes": clock.group().decode("ascii")}
    ro = entries[".rodata"]
    assert ro["offset"] <= clock.start() <= clock.end() <= ro["offset"] + ro["size"]
    note = entries[".note.gnu.build-id"]
    start = note["offset"]
    namesize, descsize, note_type = struct.unpack_from("<III", data, start)
    assert (namesize, note_type) == (4, 3) and data[start+12:start+16] == b"GNU\x00"
    build_id = {"offset": start + 16, "bytes": data[start+16:start+16+descsize].hex()}
    return {"sha256": digest(data), "bytes": len(data), "sections": entries, "segments": segments,
            "openssl_build_time": stamp, "gnu_build_id": build_id}


def compare(pinned, control):
    original, other = describe(pinned), describe(control)
    assert original["bytes"] == other["bytes"]
    clock = original["openssl_build_time"]
    note = original["gnu_build_id"]
    ro = original["sections"][".rodata"]
    bands = {"OpenSSL timestamp": range(clock["offset"], clock["offset"] + len(clock["bytes"])),
             "GNU build ID": range(note["offset"], note["offset"] + len(bytes.fromhex(note["bytes"]))),
             ".rodata section entry size": range(ro["header"] + 56, ro["header"] + 64)}
    differing = {k: [] for k in bands}
    remaining = []
    for i, (a, b) in enumerate(zip(pinned, control)):
        if a != b:
            bucket = next((differing[n] for n, r in bands.items() if i in r), remaining)
            bucket.append(i)
    return {"pinned": original["sha256"], "control": other["sha256"], "original_clock": clock,
            "control_clock": other["openssl_build_time"], "difference_offsets": differing,
            "other_different_bytes": len(remaining), "first_other_differences": remaining[:64],
            "changed_sections": [n for n in original["sections"] if original["sections"][n] != other["sections"].get(n)],
            "changed_segments": [i for i, ph in enumerate(original["segments"]) if ph != other["segments"][i]]}
