"""Keep addressable original object bytes and the corresponding physical incremental session."""
import hashlib
import json
import struct
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def archive(data):
    assert data[:8] == b"!<arch>\n"
    offset = 8
    names = None
    members = {}
    while offset < len(data):
        header = data[offset:offset + 60]
        assert header[58:] == b"`\n"
        name = header[:16].decode().strip()
        size = int(header[48:58])
        start = offset + 60
        body = data[start:start + size]
        assert len(body) == size
        if name == "//":
            names = body
        elif name.startswith("/") and name[1:].isdigit():
            index = int(name[1:])
            name = names[index:names.index(b"/\n", index)].decode()
        else:
            name = name.removesuffix("/")
        assert name not in members
        members[name] = body
        offset = start + size + size % 2
    assert offset == len(data)
    return members


def snapshot(stdout, env, pool):
    msgs = [json.loads(line) for line in stdout.splitlines()]
    assert msgs[-1] == {"reason": "build-finished", "success": True}
    assert not any(m.get("message", {}).get("level") == "error" for m in msgs)
    row, = (m for m in msgs if m["reason"] == "compiler-artifact"
            and m["target"]["name"] == "annotate_snippets" and m["target"]["kind"] == ["lib"])
    lib, = (Path(f) for f in row["filenames"] if f.endswith(".rlib"))
    raw = lib.read_bytes()
    members = archive(raw)
    objects = {n.split(".")[-4] + ".o": b for n, b in members.items() if n.endswith(".rcgu.o")}
    assert len(objects) == 42 and "lib.rmeta" in members
    roots = [Path(env[key]) for key in ["CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR"]]
    session, = (w for root in roots for w in root.rglob("work-products.bin")
                if w.parent.parent.name.startswith("annotate_snippets-") and not w.parent.name.endswith("-working"))
    indexed = session.read_bytes()
    physical = {}
    for name, body in objects.items():
        path = session.parent / name
        st = path.stat()
        assert path.is_file() and not path.is_symlink() and path.read_bytes() == body and name.encode() in indexed
        h = digest(body)
        dest = pool / h
        if dest.exists():
            assert dest.read_bytes() == body
        else:
            with dest.open("xb") as f:
                f.write(body)
        physical[name] = [h, st.st_dev, st.st_ino]
    return {"archive": digest(raw), "metadata": digest(members["lib.rmeta"]), "cgu": physical,
            "fresh": row["fresh"], "session": str(session), "library": str(lib)}


def sections(data):
    assert data[:7] == b"\x7fELF\x02\x01\x01"
    header = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    assert header[:3] == (1, 62, 1) and header[10] == 64
    table = [struct.unpack_from("<IIQQQQIIQQ", data, header[5] + n*64) for n in range(header[11])]
    tab = table[header[12]]
    names = data[tab[4]:tab[4]+tab[5]]
    seen = {}
    out = {}
    for off, typ, flags, addr, pos, size, link, info, align, ent in table:
        name = names[off:names.index(0, off)].decode()
        n = seen.get(name, 0)
        seen[name] = n + 1
        body = data[pos:pos+size] if typ != 8 else b""
        out[(name, n)] = (typ, flags, addr, size, align, ent, digest(body))
    return out


def compare(states, read):
    old, edit, repeat, clean = (states[n] for n in ["old", "edit", "repeat", "empty"])
    assert not old["fresh"] and not edit["fresh"] and repeat["fresh"] and not clean["fresh"]
    assert edit["cgu"] == repeat["cgu"] and edit["archive"] == repeat["archive"]
    assert set(old["cgu"]) == set(edit["cgu"]) == set(clean["cgu"])
    kinds = {}
    for name, (h, dev, ino) in old["cgu"].items():
        k, d2, i2 = edit["cgu"][name]
        assert k == clean["cgu"][name][0] and ((h == k) == ((dev, ino) == (d2, i2)))
        if h == k:
            kinds[name] = "copy"
            continue
        a, b = sections(read(h)), sections(read(k))
        changed = [s for s in a.keys() | b.keys() if a.get(s) != b.get(s)]
        assert changed
        if all(s[0].startswith((".debug_", ".rela.debug_")) for s in changed):
            kinds[name] = "debug"
        else:
            assert any(((a.get(s) or b[s])[1] & 2) for s in changed)
            kinds[name] = "native"
    assert list(kinds.values()).count("copy") == 36 and list(kinds.values()).count("debug") == 2
    assert list(kinds.values()).count("native") == 4
    return kinds
