"""Read a source-selected OSP3 or OSP4 entry without substituting any key, placement, checksum or object bytes."""

import hashlib
import struct

MAGIC = b"OHMSPL02"
END = b"rust-end-file"


def parse(raw, version=4):
    if version not in (3, 4) or not raw.startswith(b"RSIC") or not raw.endswith(END):
        raise ValueError("unrecognized physical work-product index")
    end = len(raw) - len(END)
    pos = raw.find(MAGIC, 0, end)
    if pos < 0:
        return None
    cursor = pos + len(MAGIC)
    slots = []
    prior = -1
    while cursor < end:
        if cursor + 8 > end:
            raise ValueError("partial optional header")
        slot, size = struct.unpack_from("<II", raw, cursor)
        cursor += 8
        if slot <= prior or size < 4 + 32 + 17 + 32 or cursor + size > end:
            raise ValueError("incorrect optional entry bound")
        if (
            raw[cursor : cursor + 4] != b"OSP" + bytes([version])
            or raw[cursor + 36 : cursor + 53] != b"CGU-GLOBAL-LINES\x01"
        ):
            raise ValueError("different physical placement protocol")
        slots.append(
            [
                slot,
                size,
                raw[cursor + 4 : cursor + 36].hex(),
                raw[cursor + size - 32 : cursor + size].hex(),
            ]
        )
        cursor += size
        prior = slot
    if not slots or cursor != end:
        raise ValueError("truncated or empty optional table")
    return {
        "offset": pos,
        "bytes": end - pos,
        "prefix_sha256": hashlib.sha256(raw[:pos]).hexdigest(),
        "entries": slots,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
