"""Decode a signed core's dense/sparse stable identities and definition parent paths."""

import hashlib, json, struct, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(
    0, str(HERE.parent / "ruff-linter-check-attribution/evidence/field-visibility")
)
import scope_rdr as m


def objects(p, rust_source, targets):
    sy, names = m.schema(rust_source)
    raw = p.read_bytes()
    r = m.Reader(raw, sy)
    root = int.from_bytes(raw[8:16], "little")
    r.pos = 16
    version = r.string()
    r.pos = root
    last = None

    def position():
        nonlocal last
        d = r.var()
        new = root - d if last is None else last + d
        assert 0 < new <= root and (last is None or last <= new)
        last = new
        return new

    def arr():
        n = r.var()
        return n, position() if n else None

    def table():
        return r.var(), r.var(), position()

    assert r.symbol() == "x86_64-unknown-linux-gnu"
    r.take(32)
    assert r.symbol() == "core" and r.byte() == r.byte() == 0
    r.string()
    stable = int.from_bytes(r.take(8), "little")
    assert stable == 0x94F40D7DEFB754B5
    assert [r.var() for _ in range(7)] == [0, 0, 3, 0, 0, 0, 0]
    _ = [arr() for _ in range(13)]
    assert r.byte() == 0
    _ = [arr() for _ in range(3)]
    assert r.byte() == 0
    _ = [arr() for _ in range(5)]
    assert r.byte() in (0, 1)
    tables = {
        k: table() for k in (*names, "syntax_contexts", "expn_data", "expn_hashes")
    }

    def slots(k):
        code, n, at = tables[k]
        w = code & 127
        assert n <= 2**22 and w <= 17
        if code < 128:
            assert at + w * n <= root
            for i in range(n):
                data = raw[at + i * w : at + (i + 1) * w]
                if any(data):
                    yield i, data
        else:
            groups = (n + 63) // 64
            off = at + groups * 12
            seen = 0
            for g in range(groups):
                bits, rank = struct.unpack_from("<QI", raw, at + 12 * g)
                assert rank == seen and bits.bit_length() <= min(64, n - 64 * g)
                while bits:
                    low = bits & -bits
                    yield (
                        g * 64 + low.bit_length() - 1,
                        raw[off + w * seen : off + w * (seen + 1)],
                    )
                    seen += 1
                    bits ^= low

    ids = {int.from_bytes(v, "little"): i for i, v in slots("def_path_hashes")}
    keys = dict(slots("def_keys"))
    assert len(ids) == tables["def_path_hashes"][1]
    wanted = {int(k, 16) for k in targets}
    results = {}
    for lookup in sorted(wanted):
        i = ids[lookup]
        seen = set()
        path = []
        rawkeys = []
        while True:
            assert i not in seen
            seen.add(i)
            r.pos = int.from_bytes(keys[i], "little")
            before = r.pos
            parent = r.byte()
            if parent:
                parent = r.var()
            else:
                parent = None
            tag = r.byte()
            name = r.symbol() if tag in (5, 6, 7, 8) else "tag" + str(tag)
            ordinal = r.var()
            rawkeys.append((i, parent, tag, name, ordinal, raw[before : r.pos].hex()))
            path.append(name + "#" + str(ordinal) if ordinal else name)
            if parent is None:
                break
            i = parent
        results[f"{lookup:016x}"] = dict(path="::".join(reversed(path)), walk=rawkeys)
    return results
