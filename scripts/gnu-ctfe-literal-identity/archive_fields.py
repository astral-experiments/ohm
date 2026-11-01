"""Account for exact archive byte differences solely at two verified sets of object-name fields."""

from pathlib import Path
import gzip, hashlib, json, re, struct, sys

H = lambda x: hashlib.sha256(x).hexdigest()
PAT = re.compile(rb"^(ruff_python_ast-[0-9a-f]{16}\.([0-9a-z]+))\.([0-9a-z]{7})\.rcgu\.o$")


def need(x, msg):
    if not x:
        raise ValueError(msg)


def uleb(data, idx):
    val = 0
    p = idx
    while p < len(data) and p < idx + 9:
        b = data[p]
        val |= (b & 127) << (7 * (p - idx))
        p += 1
        if b < 128:
            return val, p
    raise ValueError("unterminated uleb")


def analyze(data):
    need(bytes(data[:8]) == b"!<arch>\n", "not a full GNU ar")
    raw = bytes(data)
    data = bytearray(data)
    pos = 8
    stabs = None
    ln = None
    rows = []
    obj = []
    fix = []
    other = {}
    members = {}
    offsetbase = 0
    while pos < len(data):
        hdr = data[pos : pos + 60]
        need(len(hdr) == 60 and hdr[58:] == b"`\n", "malformed ar")
        name = bytes(hdr[:16]).strip()
        sz = int(hdr[48:58].strip())
        start = pos + 60
        end = start + sz
        need(end <= len(data), "short archive")
        pos = end + (sz % 2)
        if name == b"//":
            need(stabs is None, "duplicate long table")
            stabs = bytes(data[start:end])
            offsetbase = start
            continue
        if name in (b"/", b"/SYM64/"):
            other["archive-index"] = H(data[start:end])
            continue
        if name.startswith(b"/") and name[1:].isdigit():
            i = int(name[1:])
            stop = stabs.index(b"/\n", i)
            name = stabs[i:stop]
            m = PAT.fullmatch(name)
            need(m is not None, ("unexpected CGU name", name))
            fix.append((offsetbase + i + m.start(3), offsetbase + i + m.end(3), m[3], "ar-name"))
        else:
            name = name.removesuffix(b"/")
        if name == b"lib.rmeta-link":
            need(ln is None, "duplicate late metadata")
            ln = (start, end)
        elif name == b"lib.rmeta":
            other["regular-metadata-wrapper"] = H(data[start:end])
        else:
            need(
                PAT.fullmatch(name)
                and data[start : start + 6] == b"\x7fELF\x02\x01"
                and data[start + 16 : start + 20] == b"\x01\x00\x3e\x00",
                "not AMD64 native .o",
            )
            obj.append((name, H(data[start:end])))
        rows.append(name)
        members[name.decode()] = H(data[start:end])
    need(
        pos == len(data) and ln and len(rows) == len(set(rows)) and len(other) == 2 and len(obj) > 1,
        "incomplete archive",
    )
    start, end = ln
    elf = data[start:end]
    need(elf[:6] == b"\x7fELF\x02\x01" and elf[16:20] == b"\x01\x00\x3e\x00", "wrong late object")
    shoff = struct.unpack_from("<Q", elf, 40)[0]
    entsize, count, shstr = struct.unpack_from("<HHH", elf, 58)
    need(entsize == 64 and count > shstr, "section headers")

    def sh(i):
        return struct.unpack_from("<IIQQQQIIQQ", elf, shoff + i * entsize)

    h = sh(shstr)
    strings = elf[h[4] : h[4] + h[5]]
    sections = {}
    for i in range(1, count):
        v = sh(i)
        n = bytes(strings[v[0] : strings.index(0, v[0])])
        need(n not in sections, "duplicate section")
        sections[n] = (v[4], v[5])
    need(b".rmeta-link" in sections, "missing authentic late section")
    off, length = sections[b".rmeta-link"]
    body = bytes(elf[off : off + length])
    cnt, i = uleb(body, 0)
    need(cnt == len(obj), "late CGU count differs")
    late = []
    for _ in range(cnt):
        size, i = uleb(body, i)
        n = body[i : i + size]
        m = PAT.fullmatch(n)
        need(m and body[i + size] == 0xC1, "invalid rustc string")
        base = start + off + i
        fix.append((base + m.start(3), base + m.end(3), m[3], "late-name"))
        late.append(n)
        i += size + 1
    native, p = uleb(body, i)
    need(
        native == 0 and body[p:] == b"rust-end-file" and late == [n for n, _ in obj],
        "link table does not name every physical CGU or has other inputs",
    )
    tokens = {t for _, _, t, _ in fix}
    need(
        len(tokens) == 1 and len(fix) == 2 * len(obj) and len({a for a, _, _, _ in fix}) == len(fix),
        "invalid or partial per-invocation identity",
    )
    for a, b, t, _ in fix:
        need(data[a:b] == t, "different original substring")
        data[a:b] = b"0" * len(t)
    canonical_obj = {PAT.fullmatch(n)[1].decode(): h for n, h in obj}
    need(len(canonical_obj) == len(obj), "ambiguous CGU")
    return {
        "raw_sha256": H(raw),
        "bytes": len(raw),
        "normalized_sha256": H(data),
        "token": tokens.pop().decode(),
        "object_sha256": canonical_obj,
        "object_order": list(canonical_obj),
        "members": members,
        "other": other,
        "ar_tokens": len(obj),
        "late_tokens": len(late),
    }, bytes(data)


def controls(raw):
    a, norm = analyze(raw)
    buf = bytearray(raw)
    # Alter one field outside both allowed name ranges through the intact native ELF.
    header = raw.find(b"\x7fELF\x02\x01", raw.find(b"lib.rmeta-link/"))
    need(header != -1, "no real ELF")
    buf[header + 48] ^= 1
    arr, _ = analyze(buf)
    need(a["normalized_sha256"] != arr["normalized_sha256"], "altered ELF header admitted")
    # Changing only one side of a valid CGU filename must invalidate the physical link-name table.
    at = raw.rfind(b"." + a["token"].encode() + b".rcgu.o") + 1
    buf = bytearray(raw)
    buf[at] = ord("z") if buf[at] != ord("z") else ord("y")
    try:
        analyze(buf)
    except ValueError:
        return
    raise ValueError("singleton rewritten CGU name admitted")
