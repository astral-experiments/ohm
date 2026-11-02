"""Decode checked archive member names and x86-64 ELF sections, symbols and relocations."""

import collections, hashlib, re, struct


def sha(b):
    return hashlib.sha256(b).hexdigest()


def require(test, explanation):
    if not test:
        raise ValueError(explanation)


def iter_archive(body, owner):
    # Browsable/piped library hash is checked by the caller. ELF data remain zero-copy here.
    v = memoryview(body)
    table = b""
    seen = set()
    at = 8
    require(v[:8] == b"!<arch>\n", "invalid archive")
    while at < len(v):
        header = bytes(v[at : at + 60])
        require(len(header) == 60 and header[-2:] == b"\x60\n", "ar header")
        length = int(header[48:58].strip())
        name = header[:16].decode("ascii").rstrip()
        first = at + 60
        end = first + length
        require(length >= 0 and end <= len(v), "ar extent")
        at = end + length % 2
        piece = v[first:end]
        if name == "//":
            require(not table, "duplicate strings")
            table = bytes(piece)
            continue
        if name in ("/", "/SYM64/"):
            continue
        if name.startswith("/") and name[1:].isdigit():
            begin = int(name[1:])
            end_name = table.find(b"/\n", begin)
            require(0 <= begin < end_name, "string table member")
            name = table[begin:end_name].decode("ascii")
        elif name.startswith("#1/"):
            count = int(name[3:])
            require(0 < count < len(piece), "BSD name")
            name = bytes(piece[:count]).rstrip(b"\0").decode("ascii")
            piece = piece[count:]
        else:
            name = name.removesuffix("/")
        require(name not in seen, "duplicate ar member")
        seen.add(name)
        if name in ("lib.rmeta", "lib.rmeta-link"):
            continue
        match = re.fullmatch(
            re.escape(owner)
            + r"-([a-f0-9]{16})\.([a-z0-9]{25})(?:\.[a-z0-9]{7})?\.rcgu\.o",
            name,
        )
        require(match, ("unexpected native member", name))
        yield ".".join((owner, match[1], match[2])), piece
    require(at == len(v) and "lib.rmeta" in seen, "incomplete native archive")


def elf(b):
    h = struct.unpack_from("<16sHHIQQQIHHHHHH", b)
    assert h[0][:7] == b"\x7fELF\x02\x01\x01" and h[1:3] == (1, 62)
    s = [struct.unpack_from("<IIQQQQIIQQ", b, h[6] + i * 64) for i in range(h[-2])]

    def dat(i):
        r = s[i]
        return b[r[4] : r[4] + r[5]] if r[1] != 8 else b""

    def name(tab, k):
        return tab[k : tab.index(b"\0", k)].decode("latin1")

    names = [name(dat(h[-1]), r[0]) for r in s]
    (si,) = [i for i, r in enumerate(s) if r[1] == 2]
    tab = dat(s[si][6])

    def index(x):
        return names[x] if 0 < x < len(s) else x

    syms = [
        (name(tab, n), info, oth, index(ndx), val, size)
        for n, info, oth, ndx, val, size in struct.iter_unpack("<IBBHQQ", dat(si))
    ]
    raw = collections.defaultdict(list)
    rel = collections.defaultdict(list)
    for idx, r in enumerate(s):
        nm = names[idx]
        raw[nm].append((r[1], r[2], r[5], r[8], r[9], sha(dat(idx))))
        if r[1] == 4:
            for off, info, add in struct.iter_unpack("<QQq", dat(idx)):
                rel[names[r[7]]].append((off, info & 0xFFFFFFFF, syms[info >> 32], add))
    return {k: sorted(v) for k, v in raw.items()}, syms, rel
