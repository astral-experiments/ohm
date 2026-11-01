"""Read actual stable definition keys, RDR hashes and MIR allocation record intervals."""

from pathlib import Path
import collections, gzip, hashlib, json, re, sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from symbol_reader import Reader, symbols

R = Path(__file__).resolve().parent / "inputs"
pre = symbols(gzip.decompress((R / "symbols.rs.gz").read_bytes()).decode())
TABLES = re.findall(
    r"^\s*(\w+):\s*Table<",
    gzip.decompress((R / "rmeta.rs.gz").read_bytes())
    .decode()
    .split("define_tables! {", 1)[1]
    .split("\n}", 1)[0],
    re.M,
)
K = [
    "crate",
    "impl",
    "extern",
    "use",
    "global_asm",
    "type",
    "value",
    "macro",
    "lifetime",
    "closure",
    "ctor",
    "anon_const",
    "opaque",
    "opaque_lifetime",
    "anon_assoc",
    "corout",
    "nested",
]


def sha(b):
    return hashlib.sha256(b).hexdigest()


def load(p):
    return json.loads(gzip.decompress(p.read_bytes()))


def open_obj(blob, listing):
    b = blob
    rd = Reader(b, pre)
    assert rd.take(8) == b"rust\0\0\0\n"
    root = int.from_bytes(rd.take(8), "little")
    assert rd.string() == "rustc 1.99.0-dev (Ohm metadata 1)"
    rd.pos = root
    assert rd.byte() == 0 and rd.string() == "x86_64-unknown-linux-gnu"
    private, pub = (rd.take(16)[::-1].hex() for _ in range(2))
    name = rd.sym()
    assert rd.take(2) == b"\0\0"
    ext = rd.string()
    stable = int.from_bytes(rd.take(8), "little")
    assert (
        "name " + name + ext + "\n" in listing
        and ("private hash " + private + " stable_crate_id StableCrateId(" + str(stable) + ")\n") in listing
        and "public_hash " + pub + "\n" in listing
    )
    assert rd.take(7) in [b"\0\0\3\0\0\0\0", b"\0\0\2\0\0\0\0", b"\0\0\0\0\0\0\0", b"\0\0\1\0\0\0\0"]
    last = None

    def lazy():
        nonlocal last
        d = rd.var()
        last = root - d if last is None else last + d
        assert 0 < last < root
        return last

    def arr():
        n = rd.var()
        return (n, lazy() if n else None)

    def tab():
        return (rd.var(), rd.var(), lazy())

    head_fields = [arr() for _ in range(13)]
    impls = rd.byte()
    assert impls in [0, 1]
    # Cohort uses ByTrait=1 (and ordinary helper exercises its actual variant too).
    arr()
    arr()
    alloc = arr()
    assert rd.byte() == 0
    for j in range(5):
        arr()
    assert rd.byte() in [0, 1]
    tabs = {n: tab() for n in [*TABLES, "syntax_contexts", "expn_data", "expn_hashes"]}
    inverse = lazy()
    tabs["source_map"] = tab()
    arr()
    arr()
    flags = rd.take(10)
    assert flags[-2:] == bytes((1, 1)), flags
    tabs["rdr_local"] = tab()
    tabs["rdr_expn"] = tab()
    global_fp = rd.take(16).hex()
    assert rd.take(len(b) - rd.pos) == b"rust-end-file"

    def slot(n, i):
        width, count, start = tabs[n]
        if i >= count:
            return None
        if width & 128:
            width -= 128
            at = start + (i // 64) * 12
            mask = int.from_bytes(b[at : at + 8], "little")
            bit = 1 << (i % 64)
            if not mask & bit:
                return None
            rank = int.from_bytes(b[at + 8 : at + 12], "little") + (mask & (bit - 1)).bit_count()
            at = start + ((count + 63) // 64) * 12 + rank * width
        else:
            at = start + i * width
        return b[at : at + width]

    def fp(n, i):
        v = slot(n, i)
        if not v or v[0] == 0:
            return None
        assert v[0] == 1 and len(v) == 17, (n, i, v.hex())
        return v[1:].hex()

    def_count = tabs["def_keys"][1]
    assert def_count == tabs["def_path_hashes"][1]
    defmap = {}
    keys = {}
    by_id = []
    for i in range(def_count):
        v = slot("def_keys", i)
        assert v
        rd.pos = int.from_bytes(v, "little")
        hasparent = rd.byte()
        assert hasparent in (0, 1)
        parent = rd.var() if hasparent else None
        kind = rd.var()
        assert kind < len(K)
        nm = rd.sym() if kind in [5, 6, 7, 8, 13, 14] else None
        ordinal = rd.var()
        assert (parent is None and i == 0 and kind == 0) or parent < i
        seg = (K[kind], nm, ordinal)
        path = (keys[parent] + [seg]) if parent is not None else [seg]
        keys[i] = path
        raw = slot("def_path_hashes", i)
        assert len(raw) == 8
        # An optional fixed-size little-endian pointer; definitions retain their content identity even if their local index moves.
        k = raw.hex()
        assert k not in defmap
        d = dict(id=i, path=path, fp=fp("rdr_local", i))
        defmap[k] = d
        by_id.append(k)
    exps = {i: f for i in range(tabs["rdr_expn"][1]) if (f := fp("rdr_expn", i)) is not None}
    if alloc[0]:
        rd.pos = alloc[1]
        offsets = [rd.var() for _ in range(alloc[0])]
        assert offsets == sorted(set(offsets))
        am = [b[a:z] for a, z in zip(offsets, offsets[1:] + [alloc[1]])]
        assert all(0 < len(v) < 1048576 for v in am)
    else:
        offsets = []
        am = []
    return dict(
        name=name,
        private=private,
        public=pub,
        global_fp=global_fp,
        stable=stable,
        tables=tabs,
        allocs=am,
        offsets=offsets,
        defs=defmap,
        exps=exps,
        by_id=by_id,
        alloc_field=alloc,
        raw=b,
    )


def expansions(a):
    data = a["raw"]
    encoded_width, count, base = a["tables"]["expn_hashes"]
    assert 128 < encoded_width <= 136
    width = encoded_width - 128
    by_hash = {}
    for idx, value in a["exps"].items():
        at = base + (idx // 64) * 12
        mask = int.from_bytes(data[at : at + 8], "little")
        bit = 1 << (idx % 64)
        assert idx < count and mask & bit
        rank = int.from_bytes(data[at + 8 : at + 12], "little") + (mask & (bit - 1)).bit_count()
        slot = base + ((count + 63) // 64) * 12 + rank * width
        loc = int.from_bytes(data[slot : slot + width], "little")
        assert 0 < loc < base and len(data[loc : loc + 16]) == 16
        ident = data[loc : loc + 16]
        assert (idx == 0 and not any(ident)) or int.from_bytes(ident[:8], "little") == a["stable"]
        assert ident not in by_hash
        by_hash[ident] = (idx, value)
    return by_hash
