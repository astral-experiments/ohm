"""QA decoder for the exact Ruff AST on Ohm d52336754e01.

Decode the fork's metadata table layouts (compiler/rustc_metadata/src/rmeta).
Only the ten named nodes.rs captured self-borrows in the enrolled source are movable.
Every byte outside the re-encoded DefIndex-dependent fields stays in place.
"""
from collections import Counter
from hashlib import sha256
import re

if not __debug__:
    raise RuntimeError("metadata qualification requires Python assertions")

# Generated from define_tables! in mod.rs and DefPathData in rustc_hir_id.
TABLES = """intrinsic is_macro_rules type_alias_is_checked attr_flags def_path_hashes explicit_item_bounds
explicit_item_self_bounds inferred_outlives_of explicit_super_clauses_of
explicit_implied_clauses_of explicit_implied_const_bounds inherent_impls opt_rpitit_info
module_children_reexports ambig_module_children cross_crate_inlinable asyncness constness safety
defaultness impl_is_fully_generic_for_reflection is_exportable is_reachable_non_generic
is_reachable_non_generic_with_export_level_c attributes module_children_non_reexports
associated_item_or_field_def_ids def_kind visibility def_span def_ident_span lookup_stability
lookup_const_stability lookup_default_body_stability lookup_deprecation_entry
explicit_clauses_of generics_of type_of variances_of fn_sig codegen_fn_attrs impl_trait_header
const_param_default object_lifetime_default optimized_mir mir_for_ctfe trivial_const
closure_saved_names_of_captured_variables mir_coroutine_witnesses mir_coroutine_runtime_info
promoted_mir thir_abstract_const impl_parent const_conditions coerce_unsized_info
mir_const_qualif rendered_const rendered_precise_capturing_args fn_arg_idents coroutine_kind
coroutine_for_closure adt_destructor adt_async_destructor coroutine_by_move_body_def_id
eval_static_initializer trait_def expn_that_defined default_fields params_in_repr repr_options
def_keys proc_macro_quoted_spans variant_data assoc_container macro_definition
deduced_param_attrs collect_return_position_impl_trait_in_trait_tys doc_link_resolutions
doc_link_traits_in_scope assumed_wf_types_for_rpitit opaque_ty_origin anon_const_kind
const_of_item associated_types_for_impl_traits_in_trait_or_impl
live_args_for_alias_from_outlives_bounds args_known_to_outlive_alias_params mut_restriction
proc_macro""".split()
KIND = """CrateRoot Impl ForeignMod Use GlobalAsm TypeNs ValueNs MacroNs LifetimeNs Closure Ctor AnonConst
OpaqueTy OpaqueLifetime AnonAssocTy SyntheticCoroutineBody NestedStatic""".split()

# Each stable path is tied to the exact owner, receiver token and immutable Ruff source.
NODES_SHA256 = "4427c5f979dedcd490ef3e02031c1366341eb80de2137ecf3a11bfbc1bef6cba"
CAPTURES = {
    "0c99f4ef08b3504d": ("Parameters", 125, "iter_non_variadic_params", 3328, 109559),
    "41b754b8a7e89144": ("BytesLiteralValue", 82, "bytes", 2082, 68702),
    "a1dc95229fd5234b": ("StringLiteralValue", 67, "chars", 1636, 52836),
    "7503ca197aa5ef7c": ("InterpolatedStringElements", 55, "literals", 1409, 45251),
    "6ba6667c4ab0846e": ("InterpolatedStringElements", 55, "interpolations", 1414, 45514),
    "adfb715dfc7f26d4": ("TStringValue", 44, "elements", 924, 28379),
    "509d3d60f672e4ed": ("ExprCompare", 2, "iter", 159, 5300),
    "deb311e9263a3c0a": ("FStringValue", 26, "literals", 608, 18150),
    "e14ffa155b761e6a": ("FStringValue", 26, "f_strings", 624, 18727),
    "82cd800d5f969338": ("FStringValue", 26, "elements", 642, 19436),
}
LINES = {lo:line for owner, impl, method, line, lo in CAPTURES.values()}
POINTER_FIELDS = {"def_keys","def_span","def_ident_span"}
def sha(value):
    return sha256(value).hexdigest()

class Cursor:
    def __init__(self, raw, pos):
        self.raw, self.pos = raw, pos

    def take(self, n):
        p = self.pos
        self.pos += n
        assert 0 <= p <= self.pos <= len(self.raw)
        return self.raw[p:self.pos]

    def uint(self):
        value = 0
        for shift in range(0, 64, 7):
            byte = self.take(1)[0]
            value |= (byte & 127) << shift
            if byte < 128:
                return value
        raise ValueError("invalid LEB128")

    def string(self):
        value = self.take(self.uint()).decode()
        assert self.take(1) == b"\xc1"
        return value

    def symbol(self):
        tag = self.uint()
        if tag == 0:
            return self.string()
        if tag == 1:
            return Cursor(self.raw, self.uint()).string()
        assert tag == 2
        i = self.uint()
        return {56:"'_", 1063:"iter"}.get(i, f"predefined#{i}")

class Table:
    def __init__(self, raw, width, count, position):
        self.raw, self.width, self.count, self.position = raw, width, count, position

    def slot(self, i):
        assert i >= 0
        if i >= self.count:
            return None, 0
        w = self.width & 127
        base = self.position
        if self.width & 128:
            buckets = (self.count + 63) // 64
            h = base + 12 * (i // 64)
            bitmap = int.from_bytes(self.raw[h:h+8], "little")
            bit = 1 << (i % 64)
            if not bitmap & bit:
                return None, 0
            i = int.from_bytes(self.raw[h+8:h+12], "little") + (bitmap & (bit-1)).bit_count()
            base += 12 * buckets
        return base + w * i, w

    def get(self, i):
        p, w = self.slot(i)
        return self.raw[p:p+w] if p is not None else b""

class Metadata:
    def __init__(self, raw):
        self.raw = raw
        assert raw[:8] == b"rust\0\0\0\n"
        self.root = int.from_bytes(raw[8:16], "little")
        c = Cursor(raw, self.root)
        assert c.uint() == 0 and c.string() == "x86_64-unknown-linux-musl"
        self.crate_hashes = c.take(32)
        assert c.symbol() == "ruff_python_ast" and c.take(2) == bytes(2)
        extra = c.string()
        assert re.fullmatch(r"-[0-9a-f]{16}", extra)
        self.stable_crate_id = c.take(8)
        assert c.take(7) == bytes([0, 0, 3, 0, 0, 0, 0])
        self.previous = None
        def lazy():
            delta = c.uint()
            now = self.root - delta if self.previous is None else self.previous + delta
            assert 0 < now <= self.root
            self.previous = now
            return now
        def array():
            return lazy() if c.uint() else None
        def table():
            width, length = c.uint(), c.uint()
            return Table(raw, width, length, lazy())
        for _ in range(13): # externally_implementable_items through traits
            array()
        assert c.uint() == 1 # EncodedTraitImpls::DefPathHash
        for _ in range(3): # impls, incoherent_impls, interpret_alloc_index
            array()
        assert c.uint() == 0 # no ProcMacroData
        for _ in range(5): # debugger_visualizers through exported_generic_symbols
            array()
        assert c.uint() in (0, 1)
        self.tables = {key: table() for key in TABLES}
        for key in ("syntax_contexts", "expn_data", "expn_hashes"):
            self.tables[key] = table()
        self.hash_map = lazy()
        self.tables["source_map"] = table()
        array()
        array()
        assert all(v <= 1 for v in c.take(6))
        c.uint() # symbol mangling version
        assert c.uint() in (0, 1) and c.uint() == 1 and c.uint() == 1
        self.tables["public_item_hashes"] = table()
        self.tables["expansion_hashes"] = table()
        self.global_fingerprint = c.take(16)
        assert raw[c.pos:] == b"rust-end-file"
        self.table_count = self.tables["def_keys"].count
        assert self.table_count == self.tables["def_path_hashes"].count

    def pointer(self, table, index):
        return int.from_bytes(self.tables[table].get(index), "little")

    def defkey(self, index):
        offset = self.pointer("def_keys", index)
        c = Cursor(self.raw, offset)
        has_parent = c.uint()
        assert has_parent in (0, 1)
        parent = c.uint() if has_parent else None
        tag = c.uint()
        kind = KIND[tag]
        name = c.symbol() if tag in (5, 6, 7, 8, 13, 14) else ""
        disambiguator = c.uint()
        return parent, kind, name, disambiguator, (offset, c.pos-offset)

    def path(self, index):
        parts = []
        while index is not None:
            index, kind, name, d, _ = self.defkey(index)
            parts.append((kind, name, d))
            assert len(parts) <= 64
        return list(reversed(parts))

    def span(self, index, field):
        p = self.pointer(field, index)
        tag = self.raw[p]
        assert tag & 3 == 3 and tag >> 3 in range(1, 9)
        n = tag >> 3
        v = int.from_bytes(self.raw[p+1:p+1+n], "little")
        target = p-v if tag & 4 else v
        assert 0 < target < p
        c = Cursor(self.raw, target)
        t = c.uint()
        assert t & 7 == 4 # local source, root syntax context
        lo = c.uint()
        length = t >> 3 if t >> 3 < 31 else c.uint()
        source_index = c.uint()
        file_entry = self.pointer("source_map", source_index)
        file = Cursor(self.raw, file_entry)
        assert file.take(2) == bytes(2) and file.string() == "crates/ruff_python_ast/src/nodes.rs"
        return (p,n+1), {"direct_offset":target, "source_index":source_index,
            "source_entry":file_entry, "lo":lo, "hi":lo+length,
            "nodes_line":LINES[lo], "text":"&"}

    def indices(self):
        c = Cursor(self.raw, self.hash_map)
        n = c.uint()
        header = c.take(32)
        assert header[:8] == b"ODHT\x01\x08\x04\x20" and header[24:28] == b"\0\0\0\x02"
        count = int.from_bytes(header[8:16], "little")
        slots = int.from_bytes(header[16:24], "little")
        assert count == self.table_count and n == 32 + 13*slots + 16
        occupied = self.raw[c.pos+12*slots:c.pos+13*slots]
        self.reverse = {}
        for i, state in enumerate(occupied):
            if state & 128: # empty or deleted marker
                continue
            p = c.pos + 12*i
            h = self.raw[p:p+8]
            index = int.from_bytes(self.raw[p+8:p+12], "little")
            assert h not in self.reverse and self.tables["def_path_hashes"].get(index) == h
            self.reverse[h] = (p+8, index)
        assert len(self.reverse) == count

def validate_source(nodes):
    """Tie every recognized lifetime to a distinct receiver in the pinned nodes.rs."""
    assert sha(nodes) == NODES_SHA256 and len(CAPTURES) == len(LINES) == 10
    for _, (owner, _, method, line, lo) in CAPTURES.items():
        assert nodes[lo:lo+5] == b"&self" and nodes.count(b"\n", 0, lo) + 1 == line
        owner_decl = list(re.finditer(rb"^impl (\w+) \{", nodes[:lo], re.M))[-1].group(1)
        decl = list(re.finditer(rb"^    pub fn (\w+)\(", nodes[:lo], re.M))[-1]
        header = nodes[decl.start():nodes.index(b"{", lo)]
        assert owner_decl.decode() == owner and decl.group(1).decode() == method
        assert b"-> impl " in header and b"Iterator" in header
    return NODES_SHA256


# These seven are present in this exact crate but never eligible to move.
EXCLUDED = frozenset("""
d3cb2ab977013937 08a5653edf8e2595 5cc4a62c4f9d0c25 a8a6736cb3218a67
a4c3491111a48405 928205b8d050738f e4a3c7db5cdbd1b2
""".split())


def verify_inventory(data):
    """Recover every opaque lifetime in the crate and identify each enrolled receiver."""
    assert data.table_count == 18159
    eligible = {}
    excluded = set()
    for h, (_, i) in data.reverse.items():
        if data.defkey(i)[1] != "OpaqueLifetime":
            continue
        key = h.hex()
        path = data.path(i)
        if key in EXCLUDED:
            assert path[1][1] != "nodes"
            excluded.add(key)
            continue
        owner, impl, method, line, lo = CAPTURES[key]
        assert path == [("CrateRoot","",0), ("TypeNs","nodes",0), ("Impl","",impl),
                        ("ValueNs",method,0), ("OpaqueTy","",0), ("OpaqueLifetime","'_",0)]
        assert data.tables["def_kind"].get(i) == bytes([25])
        for name in ("def_span","def_ident_span"):
            _, pos = data.span(i, name)
            assert (pos["nodes_line"], pos["lo"], pos["hi"]) == (line, lo, lo + 1)
        eligible[i] = key
    assert set(eligible) == set(range(18149, 18159)) and set(eligible.values()) == CAPTURES.keys()
    assert excluded == EXCLUDED
    return eligible


def canonical(raw):
    """Put the ten source-validated captures in stable order and re-encode positional fields."""
    data = Metadata(raw)
    data.indices()
    verify_inventory(data)
    rows = {}
    positions = set()
    for hex_hash, (owner, impl, method, line, column_in_file) in CAPTURES.items():
        h = bytes.fromhex(hex_hash)
        bucket, index = data.reverse[h]
        path = data.path(index)
        assert path == [("CrateRoot","",0), ("TypeNs","nodes",0), ("Impl","",impl),
                        ("ValueNs",method,0), ("OpaqueTy","",0), ("OpaqueLifetime","'_",0)]
        assert data.tables["def_kind"].get(index) == bytes([25])
        assert index not in positions
        positions.add(index)
        key_at, key_width = data.defkey(index)[-1]
        spans = {}
        for field in ("def_span","def_ident_span"):
            span, record = data.span(index, field)
            assert record["lo"] == column_in_file and record["hi"] == column_in_file + 1
            assert record["nodes_line"] == line and record["text"] == "&"
            spans[field] = span, record["direct_offset"]
        assert spans["def_span"][1] == spans["def_ident_span"][1]
        rows[index] = dict(method=method, hash=h, bucket=bucket, key_slot=(key_at,key_width),
                           spans=spans, fingerprint=data.tables["public_item_hashes"].get(index))
        assert len(rows[index]["fingerprint"]) == 17 and rows[index]["fingerprint"][0] == 1
    for field in TABLES:
        if field in ("def_keys","def_span","def_ident_span","def_path_hashes","proc_macro_quoted_spans"):
            continue
        assert len({data.tables[field].get(i) for i in rows}) == 1, field
    result = bytearray(raw)
    modified = set()
    def write(slot, content):
        pos, width = slot
        assert pos is not None and width == len(content)
        for p in range(pos, pos+width):
            assert p not in modified
            modified.add(p)
        result[pos:pos+width] = content
    for dest, src in zip(sorted(rows), sorted(rows, key=lambda i:rows[i]["hash"])):
        origin, target = rows[src], rows[dest]
        old, width = origin["key_slot"]
        write(target["key_slot"], raw[old:old+width])
        write(data.tables["def_path_hashes"].slot(dest), origin["hash"])
        write((origin["bucket"],4), dest.to_bytes(4,"little"))
        write(data.tables["public_item_hashes"].slot(dest), origin["fingerprint"])
        for field in ("def_span","def_ident_span"):
            (old, n), direct = origin["spans"][field]
            (new, m), _ = target["spans"][field]
            assert n == m and raw[old] == raw[new] and raw[old] & 7 == 7
            write((new,m), raw[old:old+1]+(new-direct).to_bytes(m-1,"little"))
    return bytes(result)


def prove_permutation(before, after):
    if len(before) != len(after):
        raise ValueError("file size changed")
    a, b = Metadata(before), Metadata(after)
    a.indices()
    b.indices()
    verify_inventory(a)
    verify_inventory(b)
    assert (a.root, a.table_count, a.stable_crate_id, a.crate_hashes, a.global_fingerprint) == (
        b.root, b.table_count, b.stable_crate_id, b.crate_hashes, b.global_fingerprint)
    assert a.reverse.keys() == b.reverse.keys()
    draft = bytearray(before)
    expected = {}
    counts = Counter()
    changed_indices = []
    rows = []
    def write(where, value, label):
        position, width = where
        assert position is not None and len(value) == width
        for i, byte in enumerate(value, position):
            assert i not in expected
            expected[i] = label
            if draft[i] != byte:
                counts[label] += 1
            draft[i] = byte
    for h, (source_bucket, source_index) in a.reverse.items():
        dest_bucket, dest_index = b.reverse[h]
        assert source_bucket == dest_bucket
        if source_index != dest_index:
            changed_indices.append((source_index, dest_index, h))
    for source_index, dest_index, h in sorted(changed_indices):
        path = a.path(source_index)
        assert path == b.path(dest_index)
        method = path[-3][1]
        owner, impl, enrolled_method, line, lo = CAPTURES[h.hex()]
        assert method == enrolled_method
        assert path == [("CrateRoot","",0), ("TypeNs","nodes",0), ("Impl","",impl),
                        ("ValueNs",method,0), ("OpaqueTy","",0), ("OpaqueLifetime","'_",0)]
        akey, bkey = a.defkey(source_index), b.defkey(dest_index)
        assert akey[:4] == bkey[:4] and a.tables["def_kind"].get(source_index) == bytes([25])
        for table in TABLES:
            if table in POINTER_FIELDS or table == "proc_macro_quoted_spans":
                continue
            assert a.tables[table].get(source_index) == b.tables[table].get(dest_index), table
        slot, width = akey[-1]
        write(bkey[-1], before[slot:slot+width], "DefKey")
        write(b.tables["def_path_hashes"].slot(dest_index), h, "DefPathHash")
        bucket, _ = a.reverse[h]
        write((bucket,4), dest_index.to_bytes(4,"little"), "reverse_index")
        fingerprint = a.tables["public_item_hashes"].get(source_index)
        assert fingerprint[0:1] == b"\1" and len(fingerprint) == 17
        write(b.tables["public_item_hashes"].slot(dest_index), fingerprint, "item_fingerprint")
        spans = {}
        for field in ("def_span","def_ident_span"):
            (old, nbytes), description = a.span(source_index, field)
            (new, new_bytes), other = b.span(dest_index, field)
            assert description == other and description["nodes_line"] == line and description["lo"] == lo and description["hi"] == lo+1
            assert nbytes == new_bytes and before[old] == after[new] and before[old] & 7 == 7
            displacement = new - description["direct_offset"]
            write((new, new_bytes), before[old:old+1]+displacement.to_bytes(new_bytes-1,"little"), field)
            spans[field] = description
        rows.append({"owner":owner, "method":method, "from":source_index, "to":dest_index, "stable_hash_bytes":h.hex(),
                     "public_fingerprint":fingerprint[1:].hex(), "span":spans["def_span"]})
    if draft != after:
        first = next(i for i, (v, w) in enumerate(zip(draft, after)) if v != w)
        raise ValueError(f"unexplained byte at {first}")
    assert sum(counts.values()) == sum(x != y for x, y in zip(before, after))
    return {"rows":rows, "file_bytes":len(after), "definitions":a.table_count,
            "def_index_tables":len(TABLES)-1, "by_field":dict(counts), "differing_bytes":sum(counts.values()),
            "source_sha256":sha(before), "reencoded_sha256":sha(draft), "destination_sha256":sha(after)}

