"""Escrow complete outputs and inventory real BSD/GNU ar framing and Mach-O/ELF sections."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct


def need(ok, message):
    if not ok:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def block(data, off, size):
    need(0 <= off <= len(data) and 0 <= size <= len(data) - off, "invalid object file extent")
    return data[off : off + size]


def zname(raw):
    return raw.split(b"\0", 1)[0].decode("utf-8")


def describe_object(data):
    magic = data[:4]
    mach = {
        bytes.fromhex(v): (end, bits)
        for v, end, bits in (
            ("cffaedfe", "<", 64),
            ("cefaedfe", "<", 32),
            ("feedfacf", ">", 64),
            ("feedface", ">", 32),
        )
    }
    sections = []

    def add(name, group, offset, size):
        if size:
            sections.append(
                {
                    "name": name,
                    "group": group,
                    "offset": offset,
                    "bytes": size,
                    "sha256": digest(block(data, offset, size)),
                }
            )

    def uint(fmt, off):
        return struct.unpack_from(end + fmt, data, off)[0]

    if magic in mach:
        end, bits = mach[magic]
        cpu, subtype, ftype, ncmd, cmdbytes = struct.unpack_from(end + "IIIII", data, 4)
        header = 32 if bits == 64 else 28
        add("Mach-O header and load commands", "object-header", 0, header + cmdbytes)
        cursor = header
        for _ in range(ncmd):
            cmd, n = struct.unpack_from(end + "II", data, cursor)
            need(n >= 8 and cursor + n <= header + cmdbytes, "truncated Mach-O load command")
            if (bits, cmd) in ((64, 0x19), (32, 1)):
                wide = bits == 64
                base, stride = (72, 80) if wide else (56, 68)
                count = uint("I", cursor + (64 if wide else 48))
                need(base + count * stride == n, "malformed Mach-O section roster")
                for i in range(count):
                    pos = cursor + base + i * stride
                    name = zname(block(data, pos, 16))
                    seg = zname(block(data, pos + 16, 16))
                    size = uint("Q" if wide else "I", pos + (40 if wide else 36))
                    off, _, rel, nrel, flags = struct.unpack_from(end + "IIIII", data, pos + (48 if wide else 40))
                    group = (
                        "metadata"
                        if name in ("__rustc", "__rustc_meta", "__rmeta", ".rmeta", ".rmeta-link")
                        else "debug"
                        if seg == "__DWARF"
                        else "code"
                        if name == "__text" or flags & 0x80000400
                        else "data"
                    )
                    if flags & 255 not in (1, 12, 18):
                        add(seg + "," + name, group, off, size)
                    if nrel:
                        add(seg + "," + name + " relocations", "relocations", rel, nrel * 8)
            elif cmd == 2:
                sym, nsym, strings, nstrings = struct.unpack_from(end + "IIII", data, cursor + 8)
                add("symbol table", "symbols", sym, nsym * (16 if bits == 64 else 12))
                add("symbol names", "symbols", strings, nstrings)
            cursor += n
        need(cursor == header + cmdbytes, "incomplete Mach-O load command traversal")
        kind = {"format": "Mach-O", "bits": bits, "endian": end, "cpu": cpu, "subtype": subtype, "type": ftype}
    elif magic == b"\x7fELF":
        need(data[4] in (1, 2) and data[5] in (1, 2), "unsupported ELF identification")
        bits = 32 if data[4] == 1 else 64
        end = "<" if data[5] == 1 else ">"
        size = 64 if bits == 64 else 52
        add("ELF header", "object-header", 0, size)
        shoff = uint("Q" if bits == 64 else "I", 40 if bits == 64 else 32)
        stride, count, names = struct.unpack_from(end + "HHH", data, 58 if bits == 64 else 46)
        fmt = end + ("IIQQQQIIQQ" if bits == 64 else "IIIIIIIIII")
        need(
            0 < count <= 65534 and 0 <= names < count and stride == struct.calcsize(fmt),
            "unsupported ELF section roster",
        )
        add("ELF section headers", "object-header", shoff, count * stride)
        rows = [struct.unpack_from(fmt, data, shoff + i * stride) for i in range(count)]
        strings = block(data, rows[names][4], rows[names][5])
        for row in rows:
            start, typ, flags, _, off, n = row[:6]
            need(start < len(strings), "ELF section name outside string table")
            name = zname(strings[start:])
            group = (
                "metadata"
                if name in (".rmeta", ".rustc", ".rmeta-link")
                else "debug"
                if name.startswith((".debug", ".zdebug"))
                else "relocations"
                if typ in (4, 9)
                else "symbols"
                if typ in (2, 3, 11)
                else "code"
                if flags & 4
                else "data"
            )
            if typ not in (0, 8):
                add(name, group, off, n)
        kind = {"format": "ELF", "bits": bits, "endian": end, "cpu": uint("H", 18), "type": uint("H", 16)}
    else:
        fmt = (
            "LLVM bitcode"
            if magic in (b"BC\xc0\xde", b"\xde\xc0\x17\x0b")
            else "Rust metadata"
            if magic == b"rust"
            else "opaque"
        )
        return {"format": fmt, "magic": data[:16].hex()}
    # Account for bytes between all decoded extents too. No opaque difference is
    # silently called a section, debug change or harmless archive bookkeeping.
    cursor = 0
    gaps = []
    for sec in sorted(sections, key=lambda s: s["offset"]):
        start, n = sec["offset"], sec["bytes"]
        if start > cursor:
            gaps.append([cursor, start - cursor, digest(data[cursor:start])])
        cursor = max(cursor, start + n)
    if cursor < len(data):
        gaps.append([cursor, len(data) - cursor, digest(data[cursor:])])
    return kind | {"magic": magic.hex(), "sections": sections, "unclassified_extents": gaps}


def archive(data, metadata):
    need(
        data.startswith(b"!<arch>\n") and metadata.startswith(b"rust\0"),
        "not a full ar archive/standalone Rust metadata",
    )
    members = []
    strings = b""
    pos = 8
    while pos < len(data):
        head = block(data, pos, 60)
        need(head[58:] == b"`\n", "bad ar header")
        token = head[:16].rstrip(b" ")
        size = int(head[48:58])
        payload = block(data, pos + 60, size)
        prefix = 0
        if token.startswith(b"#1/"):
            prefix = int(token[3:])
            name = zname(block(payload, 0, prefix))
        elif token.startswith(b"/") and token[1:].isdigit():
            offset = int(token[1:])
            need(offset < len(strings), "missing GNU ar string")
            name = strings[offset:].split(b"/\n", 1)[0].decode()
        else:
            name = (token if token in (b"/", b"//", b"/SYM64/") else token.removesuffix(b"/")).decode()
        raw = payload[prefix:]
        if token == b"//":
            strings = raw
        special = name in ("/", "//", "/SYM64/") or name.startswith("__.SYMDEF")
        embedded = raw.find(metadata) if len(raw) >= len(metadata) else -1
        role = (
            "archive-index"
            if special
            else "rust-metadata"
            if name == "lib.rmeta"
            else "metadata-link-map"
            if name.endswith(".rmeta-link")
            else "member"
        )
        item = {
            "ordinal": len(members),
            "name": name,
            "role": role,
            "header_offset": pos,
            "header_hex": head.hex(),
            "name_prefix_hex": payload[:prefix].hex(),
            "payload_offset": pos + 60 + prefix,
            "bytes": len(raw),
            "sha256": digest(raw),
            "embedded_standalone_offset": embedded,
            "object": describe_object(raw) if not special else {"format": "archive table"},
        }
        pos += 60 + size
        item["padding_hex"] = block(data, pos, size % 2).hex()
        pos += size % 2
        members.append(item)
    need(pos == len(data) and sum(m["name"] == "lib.rmeta" for m in members) <= 1, "incomplete or ambiguous rlib")
    need(
        any(
            m["name"].endswith(".o") and m["object"]["format"] in ("Mach-O", "ELF", "LLVM bitcode") for m in members
        ),
        "no physical native codegen members",
    )
    return {
        "archive": [len(data), digest(data)],
        "standalone_metadata": [len(metadata), digest(metadata)],
        "members": members,
    }


def outputs(argv):
    names = [a.split("=", 1)[1] for a in argv if a.startswith("extra-filename=")]
    need(len(names) == 1 and names[0].startswith("-") and names[0][1:].isalnum(), "unexpected crate filename")
    out = Path(argv[argv.index("--out-dir") + 1])
    return [out / ("libdiesel" + names[0] + ext) for ext in (".rlib", ".rmeta")]


def save(argv, cwd, directory):
    directory.mkdir()
    files = outputs(argv)
    need(
        all(p.resolve().is_relative_to(cwd) and p.is_file() and not p.is_symlink() for p in files), "foreign result"
    )
    bodies = []
    for path in files:
        before = path.stat()
        need(0 < before.st_size < 128 << 20, "native output budget")
        raw = path.read_bytes()
        after = path.stat()
        need(
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            "output moved during custody",
        )
        with (directory / path.name).open("xb") as f:
            f.write(raw)
        bodies.append(raw)
    inventory = archive(*bodies)
    inventory["paths"] = [str(p) for p in files]
    with (directory / "members.json").open("x") as out:
        json.dump(inventory, out, indent=2, sort_keys=True)
    return inventory


def compare(before, after):
    def rows(value):
        return [(m["name"], m["sha256"]) for m in value["members"] if m["role"] != "archive-index"]

    changes = []
    for idx, (a, b) in enumerate(zip(before["members"], after["members"])):
        if a == b:
            continue

        def groups(m):
            return [(s["name"], s["group"], s["bytes"], s["sha256"]) for s in m["object"].get("sections", [])]

        aa, bb = groups(a), groups(b)
        changes.append(
            {
                "ordinal": idx,
                "before": a["name"],
                "after": b["name"],
                "role": [a["role"], b["role"]],
                "headers_equal": a["header_hex"] == b["header_hex"],
                "name_prefix_equal": a["name_prefix_hex"] == b["name_prefix_hex"],
                "payload_equal": a["sha256"] == b["sha256"],
                "section_inventory_equal": aa == bb,
                "changed_section_groups": sorted(
                    {v[1] for v in (Counter(aa) - Counter(bb)) + (Counter(bb) - Counter(aa))}
                ),
                "unclassified_equal": a["object"].get("unclassified_extents")
                == b["object"].get("unclassified_extents"),
            }
        )
    left, right = rows(before), rows(after)
    return {
        "archive_equal": before["archive"] == after["archive"],
        "standalone_equal": before["standalone_metadata"] == after["standalone_metadata"],
        "ordered_member_names_and_bodies_equal": left == right,
        "ordered_nonindex_bodies_equal": [h for _, h in left] == [h for _, h in right],
        "unordered_nonindex_bodies_equal": Counter(h for _, h in left) == Counter(h for _, h in right),
        "member_counts": [len(before["members"]), len(after["members"])],
        "differences_by_ordinal": changes,
    }


def rust_object_names(section):
    """Read both serialized vectors in the pinned RmetaLink schema, including the footer."""
    cursor = 0

    def usize():
        nonlocal cursor
        value = 0
        for shift in range(0, 64, 7):
            byte = block(section, cursor, 1)[0]
            cursor += 1
            value |= (byte & 127) << shift
            if byte < 128:
                need(shift == 0 or byte != 0, "noncanonical RmetaLink length")
                return value
        raise ValueError("invalid RmetaLink length")

    def string():
        nonlocal cursor
        n = usize()
        start = cursor
        value = block(section, start, n)
        cursor += n
        need(block(section, cursor, 1) == b"\xc1", "wrong Rust string sentinel")
        cursor += 1
        return start, value

    count = usize()
    need(count <= len(section), "RmetaLink length beyond physical member")
    names = [string() for _ in range(count)]
    native = usize()
    need(native <= len(section), "invalid native library list")
    for _ in range(native):
        tag = block(section, cursor, 1)[0]
        cursor += 1
        need(tag in (0, 1), "invalid native library option")
        if tag == 1:
            string()
    need(section[cursor:] == b"rust-end-file", "invalid RmetaLink footer")
    return names


def reencode_names(raw, target, a, b):
    """Change only proven ar filename fields and corresponding typed RmetaLink string values."""
    need(a["standalone_metadata"] == b["standalone_metadata"], "standalone metadata differs")
    need(len(raw) == len(target), "full archive lengths differ")
    left, right = a["members"], b["members"]
    need(len(left) == len(right), "archive member counts differ")
    changes = {}
    positions = []
    tokens = set()
    all_cgus = 0

    def register(offset, old, new, field):
        need(block(raw, offset, len(old)) == old and len(old) == len(new), "incorrect source field")
        positions.append((offset, old, new, field))

    for old, new in zip(left, right, strict=True):
        name, replacement = old["name"].encode(), new["name"].encode()
        if name.endswith(b".rcgu.o"):
            need(
                old["object"]["format"] in ("Mach-O", "ELF") and old["sha256"] == new["sha256"],
                "a native CGU payload or format differs",
            )
            all_cgus += 1
        if name == replacement:
            continue
        u = re.fullmatch(rb"(.+)[.]([a-z0-9]{7})[.]rcgu[.]o", name)
        v = re.fullmatch(rb"(.+)[.]([a-z0-9]{7})[.]rcgu[.]o", replacement)
        need(u and v and u[1] == v[1] and name not in changes, "unregistered member name/order change")
        tokens.add((u[2], v[2]))
        changes[name] = replacement
        h = old["header_offset"]
        header = raw[h : h + 16].rstrip(b" ")
        if header.startswith(b"#1/"):
            need(len(name) <= int(header[3:]), "truncated BSD extended name")
            register(h + 60, name, replacement, "BSD ar member name")
        else:
            need(header.startswith(b"/") and header[1:].isdigit(), "unsupported ar name encoding")
            tables = [m for m in left if m["name"] == "//"]
            need(len(tables) == 1, "missing GNU name table")
            table = tables[0]
            n = int(header[1:])
            need(n + len(name) + 2 <= table["bytes"], "invalid GNU name reference")
            off = table["payload_offset"] + n
            need(raw[off + len(name) : off + len(name) + 2] == b"/\n", "wrong GNU name terminator")
            register(off, name, replacement, "GNU ar member name")
    need(len(tokens) == 1 and all_cgus, "no one-to-one invocation suffix change")
    wrappers = [m for m in left if m["name"] == "lib.rmeta-link"]
    need(len(wrappers) == 1, "no unique late-metadata wrapper")
    wrapper = wrappers[0]
    sections = [
        s for s in wrapper["object"].get("sections", []) if s["name"] in (".rmeta-link", "__DWARF,.rmeta-link")
    ]
    need(len(sections) == 1, "no unique typed late-metadata section")
    base = wrapper["payload_offset"] + sections[0]["offset"]
    names = rust_object_names(block(raw, base, sections[0]["bytes"]))
    seen = []
    for n, name in names:
        if name in changes:
            register(base + n, name, changes[name], "RmetaLink Rust object filename")
            seen.append(name)
    need(Counter(seen) == Counter(changes.keys()), "late-metadata names do not match changed CGUs exactly once")
    built = bytearray(raw)
    end = 0
    for start, old, new, _ in sorted(positions):
        need(start >= end, "overlapping name fields")
        end = start + len(old)
        built[start:end] = new
    need(built == target, "additional bytes differ outside all proven name fields")
    old_token, new_token = next(iter(tokens))
    return {
        "source": digest(raw),
        "target": digest(target),
        "reencoded": digest(built),
        "suffix": [old_token.decode(), new_token.decode()],
        "all_native_cgus": all_cgus,
        "renamed_native_cgus": len(changes),
        "edits": [[s, old.decode(), new.decode(), kind] for s, old, new, kind in sorted(positions)],
    }


def suffix_proof(before, after, a, b):
    if before == after:
        return {"result": "archive bytes already identical"}
    try:
        forward = reencode_names(before, after, a, b)
        backward = reencode_names(after, before, b, a)
    except ValueError as e:
        return {"result": "literal reconstruction unavailable", "reason": str(e)}
    return {
        "result": "full byte-for-byte reconstruction in both directions",
        "forward": forward,
        "reverse": backward,
    }
