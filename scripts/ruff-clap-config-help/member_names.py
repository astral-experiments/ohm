"""Match signed rustc native members without its seven-digit per-invocation filename nonce."""
import hashlib
import re
import struct


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_names(path, crate):
    """Read each named GNU archive member and resolve the symbol map to physical members."""
    pattern = re.compile(rf"({re.escape(crate)}-[0-9a-f]{{16}})\.([0-9a-z]{{25}})\.([0-9a-z]{{7}})\.rcgu\.o")
    rows = []
    metadata = []
    long_names = index = link_record = None
    word = None
    nonce = None
    offsets = {}
    archive_size = path.stat().st_size
    require(0 < archive_size < 512 * 2**20, "unexpected rlib size")
    with path.open("rb") as source:
        require(source.read(8) == b"!<arch>\n", "ordinary ar magic")
        while source.tell() < archive_size:
            offset = source.tell()
            header = source.read(60)
            require(len(header) == 60 and header[58:60] == b"`\n", "complete member header")
            field = header[:16].rstrip()
            size = int(header[48:58])
            require(0 <= size <= archive_size - source.tell(), "member extent")
            data = source.read(size)
            if size % 2:
                require(source.read(1) == b"\n", "GNU archive padding")
            if field in (b"/", b"/SYM64/"):
                require(index is None, "duplicate symbol map")
                index = data
                word = 4 if field == b"/" else 8
                continue
            if field == b"//":
                require(long_names is None, "duplicate GNU long-name table")
                long_names = data
                continue
            if field.startswith(b"/"):
                require(long_names is not None and field[1:].isdigit(), "long-name reference")
                pos = int(field[1:])
                require(0 <= pos < len(long_names) and (pos == 0 or long_names[pos-1:pos] == b"\n"), "middle of GNU long name")
                end = long_names.index(b"/\n", pos)
                raw = long_names[pos:end]
            else:
                require(field.endswith(b"/"), "unrecognized GNU member")
                raw = field[:-1]
            name = raw.decode("ascii")
            require(data.startswith(b"\x7fELF\x02\x01\x01"), "ordinary x86_64 ELF member")
            if name in ("lib.rmeta", "lib.rmeta-link"):
                require(len(rows) == 0 and name not in [r[0] for r in metadata], "unexpected metadata position")
                metadata.append([name, digest(data), size])
                if name == "lib.rmeta-link":
                    link_record = data
                offsets[offset] = name
                continue
            m = pattern.fullmatch(name)
            require(m is not None and int(m[3], 36) < 2**32, "unexpected native output filename")
            require(nonce is None or nonce == m[3], "mixed rustc invocation nonce")
            nonce = m[3]
            require(data[16:20] == b"\x01\x00\x3e\x00", "native object is not x86_64 ET_REL")
            canonical = f"{m[1]}.{m[2]}.rcgu.o"
            offsets[offset] = canonical
            rows.append([name, canonical, m[2], digest(data), size])
    require([r[0] for r in metadata] == ["lib.rmeta","lib.rmeta-link"] and rows, "missing native or metadata member")
    require(len(set(r[1] for r in rows)) == len(rows), "ambiguous canonical CGU")
    require(index is not None and len(index) >= word, "symbol index absent")
    count = int.from_bytes(index[:word], "big")
    names_at = (count + 1) * word
    require(0 < count <= 2_000_000 and names_at <= len(index), "malformed ar symbol index")
    data = index[names_at:]
    pos = 0
    symbol_map = hashlib.sha256()
    for i in range(count):
        start = (i + 1) * word
        member = offsets[int.from_bytes(index[start:start + word], "big")]
        end = data.index(b"\0", pos)
        require(end > pos, "empty archive symbol")
        symbol_map.update(member.encode("ascii") + b"\0" + data[pos:end+1])
        pos = end + 1
    require(data[pos:] in (b"", b"\0"), "trailing ar symtab bytes")
    # Every real native name must be named once in rustc's link wrapper. Hash the
    # entire ELF after replacing only these observed, fixed-width filename nonces.
    for name, canonical, cgu, sha, size in rows:
        actual = name.encode("ascii")
        fixed = name.replace("." + nonce + ".rcgu.o", ".0000000.rcgu.o").encode("ascii")
        require(link_record.count(actual) == 1 and len(actual) == len(fixed), "unbound link-wrapper member")
        link_record = link_record.replace(actual, fixed)
    return {"nonce": nonce, "members": rows, "metadata": metadata, "link_wrapper": digest(link_record),
            "symbols": count, "symbol_map": symbol_map.hexdigest()}


def native_identity(report):
    """Require identical order, stable full filename, complete ELF bytes, and symbol lookup."""
    return ([r[1:] for r in report["members"]], report["symbols"], report["symbol_map"], report["link_wrapper"])
