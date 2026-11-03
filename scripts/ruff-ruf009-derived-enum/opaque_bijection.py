"""Prove a stable opaque-lifetime permutation for one compiler on one source.

Reject changes outside the forward table, reverse lookup and fully decoded
key/span payloads of the same opaque lifetimes. Cross-compiler images and other
crates are outside this auxiliary same-source check.
"""

import collections
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ruff-module-16149"))
import lens


def diff(a, b):
    return set(i for i, (u, v) in enumerate(zip(a, b)) if u != v)


def key(raw, at):
    r = lens.scope_rdr.Reader(raw, lens.SCHEMA["symbols"])
    r.pos = at
    assert r.byte() == 1
    parent = r.var()
    variant = r.var()
    assert variant == 13
    sym = r.symbol()
    ord_ = r.var()
    return (parent, variant, sym, ord_), set(range(at, r.pos))


def span(raw, at):
    if not at:
        return None, set()
    r = lens.scope_rdr.Reader(raw, lens.SCHEMA["symbols"])
    r.pos = at
    tag = r.byte()
    kind = tag & 3
    ctxt = None if not tag & 4 else 0
    ln = tag >> 3
    if kind == 3:
        assert 0 < ln <= 8
        dist = int.from_bytes(r.take(ln), "little")
        ptr = at - dist if tag & 4 else dist
        assert 0 < ptr < at
        value, _ = span(raw, ptr)
        return value, set(range(at, r.pos))
    if ctxt is None:
        ctxt = r.var()
    if kind == 2:
        return (kind, ctxt), set(range(at, r.pos))
    assert kind in (0, 1)
    lo = r.var()
    if ln == 31:
        ln = r.var()
    f = r.var()
    crate = r.var() if kind == 1 else 0
    return (kind, ctxt, lo, ln, f, crate), set(range(at, r.pos))


def all_original(t, p):
    return dict(t["slots"](p))


def table_pos(raw, t, p, i):
    coded, n, at = t["wire_tables"][p]
    w = coded % 128
    if coded < 128:
        return at + i * w, w
    pos = at + 12 * (i // 64)
    bits, rank = struct.unpack_from("<QI", raw, pos)
    assert bits & (1 << (i % 64))
    return at + 12 * ((n + 63) // 64) + (rank + (bits & ((1 << (i % 64)) - 1)).bit_count()) * w, w


def compare(a, b, role, version, edition):
    assert a != b and len(a) == len(b)

    def load(raw):
        wire = {}
        header, _, rows, expansions, dependencies = lens.scope_rdr.decode(
            raw,
            lens.SCHEMA["symbols"],
            lens.SCHEMA["tables"],
            "ruff_linter",
            version,
            edition=edition,
            typed=wire,
            physical_layout=True,
        )
        return wire, header, rows, expansions, dependencies

    ta, ha, ra, ea, da = load(a)
    tb, hb, rb, eb, db = load(b)
    assert ra == rb and ea == eb and da == db
    assert all(ha[k] == hb[k] for k in ("private", "public", "global_hash", "stable"))
    idx = diff(a, b)
    obs = {}
    old = ta["path_by_index"]
    new = tb["path_by_index"]
    inv = {v[0]: i for i, v in new.items()}
    assert len(old) == len(new) == len(inv) and {h: k[1] for i, k in old.items() for h in [k[0]]} == {
        v[0]: v[1] for v in new.values()
    }
    perm = {i: inv[v[0]] for i, v in old.items() if inv[v[0]] != i}
    assert (
        0 < len(perm) <= 256
        and set(perm) == set(perm.values())
        and all("::{opaque#" in old[i][1] for i in perm)
    )
    areas = collections.defaultdict(set)
    keys_seen = {}
    details = []
    categories = ["def_keys", "def_span", "def_ident_span", "def_path_hashes", "rdr_local"]
    AA = {name: all_original(ta, name) for name in categories}
    BB = {name: all_original(tb, name) for name in categories}
    for i, j in perm.items():
        assert old[i] == new[j]
        fields = {}
        for n, fun in [("def_keys", key), ("def_span", span), ("def_ident_span", span)]:
            x = int.from_bytes(AA[n].get(i, b""), "little")
            y = int.from_bytes(BB[n].get(j, b""), "little")
            xval, xa = fun(a, x)
            yval, ya = fun(b, y)
            assert xval == yval, (role, i, j, n, xval, yval)
            areas[n + " payload"] |= xa | ya
            fields[n] = xval
            if n == "def_keys":
                parent, kind, symbol, _ = xval
                assert (
                    kind == 13
                    and symbol.startswith("'")
                    and parent not in perm
                    and old[parent] == new[parent]
                )
        assert AA["def_path_hashes"][i] == BB["def_path_hashes"][j] and AA["rdr_local"].get(i) == BB[
            "rdr_local"
        ].get(j)
        # Actual odht encoded fixed-size key/value pair. The backing array holds the hash and the little-endian physical index side by side.
        h = bytes.fromhex(old[i][0])
        left = h + i.to_bytes(4, "little")
        right = h + j.to_bytes(4, "little")
        start = ta["decode_positions"]["def_path_hash_map"]
        end = ta["wire_tables"]["source_map"][2]
        assert a.count(left, start, end) == b.count(right, start, end) == 1, (role, i)
        at = a.index(left, start, end)
        assert at == b.index(right, start, end)
        areas["DefPathHash -> DefIndex reverse lookup"] |= set(range(at, at + 12))
        details.append(
            {
                "stable": old[i][0],
                "name": old[i][1],
                "warm_index": i,
                "empty_index": j,
                "binder": fields["def_keys"],
                "def_span": fields["def_span"],
                "identifier_span": fields["def_ident_span"],
            }
        )
    for n in categories:
        assert ta["wire_tables"][n] == tb["wire_tables"][n]
        for i in AA[n].keys() | BB[n].keys():
            if AA[n].get(i) == BB[n].get(i):
                continue
            assert i in perm, (role, n, i)
            for raw, t, values in ((a, ta, AA), (b, tb, BB)):
                if i in values[n]:
                    pos, w = table_pos(raw, t, n, i)
                    areas[n + " physical table slot"] |= set(range(pos, pos + w))
    # Before/after an ordinal permutation a byte can serve a definition versus identifier span.
    areas["definition and identifier span payload"] = areas.pop("def_span payload") | areas.pop(
        "def_ident_span payload"
    )
    matched = set().union(*areas.values())
    remaining = sorted(idx - matched)
    ret = {
        "scope": role,
        "bytes_each": len(a),
        "original": [ha["full"], hb["full"]],
        "different_bytes": len(idx),
        "unattributed": remaining,
        "actual_reordered_synthetic_definitions": details,
        "classified": {n: len(v & idx) for n, v in areas.items()},
        "all": len(old),
        "public_rows": len(ra),
        "expansions": len(ea),
        "dependencies": len(da),
        "public_rows_byte_equal_by_identity": ra == rb,
        "expansions_exact_by_identity": ea == eb,
        "dep_edges_exact": da == db,
        "all_header_hashes_equal": all(
            ha[k] == hb[k] for k in ("private", "public", "global_hash", "stable")
        ),
    }
    ret["physical_field_witnesses"] = {kind: min(group & idx) for kind, group in areas.items() if group & idx}
    assert not remaining, (role, remaining[:25])
    assert sum(ret["classified"].values()) == len(idx)
    return ret
