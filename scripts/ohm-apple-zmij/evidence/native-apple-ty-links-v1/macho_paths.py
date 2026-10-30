"""Compare Apple test executables across Cargo's per-compiler output directories."""

from bisect import bisect_left
import hashlib
import re
import struct

def need(ok, message):
    if not ok:
        raise ValueError(message)

NAMESPACE = re.compile(
    rb"^(?P<base>/[^()\x00]+/workspaces/[0-9a-f]{16}/v2-)(?P<key>[0-9a-f]{16})/"
)
N_OSO = 0x66


def u32pair(data, offset):
    return struct.unpack_from("<II", data, offset)


def canonical(data, returned, linker):
    """Change only the namespace of authenticated debug-object paths and their page hashes in memory."""
    need(
        data[:8] == bytes.fromhex("cffaedfe0c000001") and u32pair(data, 12)[0] == 2,
        "wrong Apple ARM64 executable",
    )
    operands = set(linker)
    emitted = [b for a, b in zip(linker, linker[1:]) if a == "-o"]
    need(emitted == [returned], "linker did not produce the Cargo test executable")
    ns = NAMESPACE.match(returned.encode())
    need(ns is not None, "Cargo output namespace was not identified")
    count, size = u32pair(data, 16)
    cursor = 32
    tables = []
    signatures = []
    for _ in range(count):
        cmd, length = u32pair(data, cursor)
        need(
            length >= 8 and cursor + length <= 32 + size <= len(data),
            "invalid load command",
        )
        if cmd == 2:
            need(length == 24, "invalid LC_SYMTAB")
            tables.append(struct.unpack_from("<IIII", data, cursor + 8))
        if cmd == 0x1D:
            need(length == 16, "invalid LC_CODE_SIGNATURE")
            signatures.append(u32pair(data, cursor + 8))
        cursor += length
    need(
        cursor == 32 + size and len(tables) == len(signatures) == 1,
        "ambiguous Mach-O layout",
    )
    sym, nsyms, start, ssize = tables[0]
    sig, sigsize = signatures[0]
    need(
        cursor <= sym
        and sym + nsyms * 16 <= start < start + ssize <= sig
        and sig + sigsize == len(data),
        "unexpected symbol or signature ranges",
    )
    refs = {}
    for idx, kind, sect, desc, val in struct.iter_unpack(
        "<IBBHQ", data[sym : sym + nsyms * 16]
    ):
        need(idx < ssize, "bad string reference")
        refs.setdefault(idx, []).append((kind, sect, desc, val))
    offsets = sorted(refs)
    buf = bytearray(data)
    pos = start
    paths = []
    for entry in data[start : start + ssize].split(b"\0"):
        this = pos - start
        pos += len(entry) + 1
        if not entry.startswith(ns[0]):
            continue
        # No code or non-debug symbol may refer to any part of this string.
        owners = offsets[
            bisect_left(offsets, this) : bisect_left(offsets, this + len(entry))
        ]
        need(
            owners == [this] and all(r == (N_OSO, 0, 1, 0) for r in refs[this]),
            "object path is not an exclusive N_OSO symbol",
        )
        path = entry.decode()
        input_file = path.split("(", 1)[0]
        need(
            input_file in operands
            and (
                path.endswith(".o")
                if path == input_file
                else input_file.endswith(".rlib") and path.endswith(".o)")
            ),
            "debug path was not passed to this physical linker",
        )
        key = start + this + ns.start("key")
        need(
            data[key : key + 16] == ns["key"],
            "debug symbol namespace differs from its Cargo output",
        )
        buf[key : key + 16] = b"0" * 16
        paths.append(path[len(ns[0]) :])
    need(pos == start + ssize + 1 and paths, "missing N_OSO paths")
    # A linker-signed ad-hoc Mach-O has a SuperBlob containing one SHA-256
    # CodeDirectory. Validate every original page against its stored digest before
    # recomputing those hashes over the canonical debug strings.
    magic, package_length, count = struct.unpack_from(">III", data, sig)
    slot, relative = struct.unpack_from(">II", data, sig + 12)
    need(
        (magic, count, slot, relative) == (0xFADE0CC0, 1, 0, 20)
        and package_length <= sigsize
        and not any(data[sig + package_length :]),
        "unsupported ad-hoc code signature",
    )
    base = sig + relative
    cd, length, version, flags, hash_offset, identifier, special, codes, limit = (
        struct.unpack_from(">9I", data, base)
    )
    digest_len, digest_type, platform, page_log2 = struct.unpack_from(
        "4B", data, base + 36
    )
    need(
        (cd, version, flags, special, digest_len, digest_type, platform, page_log2)
        == (0xFADE0C02, 0x20400, 0x20002, 0, 32, 2, 0, 12),
        "unexpected CodeDirectory",
    )
    page = 1 << page_log2
    need(
        relative + length == package_length
        and limit == sig
        and codes == (limit + page - 1) // page
        and 44 <= identifier < hash_offset
        and hash_offset + codes * 32 == length,
        "invalid CodeDirectory page table",
    )
    changed = []
    for i in range(codes):
        lo, hi = i * page, min((i + 1) * page, limit)
        at = base + hash_offset + 32 * i
        previous = hashlib.sha256(data[lo:hi]).digest()
        need(
            previous == data[at : at + 32],
            "original code signature does not match the executable",
        )
        replacement = hashlib.sha256(buf[lo:hi]).digest()
        if previous != replacement:
            changed.append(i)
        buf[at : at + 32] = replacement
    return bytes(buf), {
        "base": ns["base"].decode(),
        "key": ns["key"].decode(),
        "paths": paths,
        "code_pages": codes,
        "path_pages": changed,
        "raw": hashlib.sha256(data).hexdigest(),
    }


def compare(arms):
    p, c = [canonical(*arms[role]) for role in "PC"]
    need(
        p[0] == c[0],
        "cross-compiler Mach-O differs outside the actual Cargo namespace and verified page hashes",
    )
    need(
        p[1]["base"] == c[1]["base"] and p[1]["paths"] == c[1]["paths"],
        "unmatched linker debug provenance",
    )
    return {
        "canonical_sha256": hashlib.sha256(p[0]).hexdigest(),
        "P": p[1],
        "C": c[1],
        "raw_difference_bytes": sum(a != b for a, b in zip(arms["P"][0], arms["C"][0])),
    }
