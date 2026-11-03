"""Census physical previous graphs and normal Cargo macro closure without executing a new compiler."""

from collections import Counter, defaultdict
from pathlib import Path
import argparse, hashlib, json, mmap, re, struct, zipfile, subprocess, tempfile, os

HERE = Path(__file__).resolve().parent
schema = HERE / "signed22-query-kinds.json"
assert (
    hashlib.sha256(schema.read_bytes()).hexdigest()
    == "c82f93d1c0ba144a5f16da25096cc77f4b04d75ee9b2070becc11c1d91f1dc0d"
)
names = json.loads(schema.read_bytes())["names"]
categories = "type_of generics_of def_kind explicit_clauses_of inferred_outlives_of clauses_of fn_sig inherent_impls trait_impls_of module_children associated_item_def_ids lookup_deprecation_entry".split()


def sha_file(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def leb(raw, off):
    v = 0
    for shift in range(0, 64, 7):
        b = raw[off]
        off += 1
        v |= (b & 127) << shift
        if b < 128:
            return v, off
    raise ValueError("oversize graph field")


def census(file, sha):
    assert sha_file(file) == sha
    keys = defaultdict(set)
    counts = Counter()
    zero = Counter()
    forced = {
        "analysis",
        "analysis_interfaces",
        "crate_for_resolver",
        "resolver_for_lowering_raw",
    }
    with file.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as g:
        assert g[:4] == b"RSIC"
        offset = 7 + g[6] + 8
        end = len(g) - 13
        start, nroots, magic, slots, nodes, edges = struct.unpack_from(
            "<QQ8sQQQ", g, end - 48
        )
        assert magic == b"OHMIDX01" and start + 8 * slots + 4 * nroots == end - 48
        bits = (len(names) - 1).bit_length()
        total = 0
        for _ in range(nodes):
            flags, index = struct.unpack_from("<HI", g, offset)
            kind = names[flags & ((1 << bits) - 1)]
            assert struct.unpack_from("<Q", g, start + 8 * index)[0] == offset
            if kind in categories or kind in (
                "typeck_root",
                "extern_def_public_hash",
                "external_metadata_input_hash",
                "public_global_hash",
            ):
                keys[kind].add(g[offset + 6 : offset + 22])
            offset += 38
            width = 1 + ((flags >> bits) & 3)
            count = (flags >> (bits + 2)) - 1
            if count < 0:
                count, offset = leb(g, offset)
            offset += width * count
            total += count
            counts[kind] += 1
            if not count and kind in forced:
                zero[kind] += 1
        for name in names:
            actual, offset = leb(g, offset)
            assert actual == counts[name]
        _, offset = leb(g, offset)
        assert offset == start and sum(counts.values()) == nodes and total == edges
        rootk = Counter()
        for i in range(nroots):
            idx = struct.unpack_from("<I", g, start + 8 * slots + 4 * i)[0]
            ptr = struct.unpack_from("<Q", g, start + 8 * idx)[0]
            rootk[names[struct.unpack_from("<H", g, ptr)[0] & ((1 << bits) - 1)]] += 1
    local = {k[:8] for k in keys["typeck_root"]}
    assert len(local) == 1
    (local,) = local
    ext = {n: {k for k in keys[n] if k[:8] != local} for n in categories}
    union = set().union(*ext.values())
    public = {k for k in keys["extern_def_public_hash"] if k[:8] != local}
    return dict(
        sha256=sha,
        local_stable_crate=local.hex(),
        nodes=nodes,
        edges=edges,
        previous_roots=rootk,
        eval_always_with_no_edges=zero,
        external_ids_by_kind={n: len(v) for n, v in ext.items()},
        unique_selected_external_defs=len(union),
        selected_with_previous_extern_def_public_hash=len(union & public),
        all_recorded_extern_def_public_hashes=len(public),
        external_whole_crate_input_hashes=len(keys["external_metadata_input_hash"]),
        public_global_hashes=len(keys["public_global_hash"]),
        counts_by_kind={
            n: counts[n]
            for n in sorted(
                set(categories)
                | forced
                | {
                    "typeck_root",
                    "mir_borrowck",
                    "external_metadata_input_hash",
                    "extern_def_public_hash",
                    "public_global_hash",
                    "module_children",
                }
            )
        },
    )


def actual_native_macro(artifact):
    assert (
        sha_file(artifact)
        == "df3081a35e1daffbafe4ce38956515ea52ff7355d72c837cf5265ff722ab46dd"
    )
    with zipfile.ZipFile(artifact) as z:
        raw_id = json.loads(z.read("profile/raw-identity.json"))
        signed = z.read("profile/perf.data.zst")
        assert hashlib.sha256(signed).hexdigest() == raw_id["compressed_sha256"]
        raw = subprocess.run(
            ["zstd", "-dc"], input=signed, stdout=subprocess.PIPE, check=True
        ).stdout
        assert (
            len(raw) == raw_id["bytes"]
            and hashlib.sha256(raw).hexdigest() == raw_id["sha256"]
        )
        roster = json.loads(z.read("profile/owner-epochs.json"))
        owner = roster["ty_python_semantic"]
        assert len(roster) == 12 and owner["pid"] == 7002
        with tempfile.NamedTemporaryFile() as f:
            f.write(raw)
            f.flush()
            text = subprocess.run(
                [
                    "perf",
                    "script",
                    "--no-inline",
                    "-G",
                    "-i",
                    f.name,
                    "-F",
                    "pid,tid,event,ip,dso",
                ],
                capture_output=True,
                check=True,
            ).stdout.decode()
        rows = []
        for line in text.splitlines():
            found = re.fullmatch(
                r"\s*(\d+)/(\d+)\s+instructions:u:\s+[0-9a-f]+\s+\((.*)\)", line
            )
            if found and int(found[1]) == owner["pid"]:
                assert int(found[2]) in owner["threads"]
                rows.append(found[3])
        counts = Counter(os.path.basename(r) for r in rows)
        macro = "libsalsa_macros-1490b2847bcc7d8e.so"
        assert len(rows) == 14488 and counts[macro] == 2014
        ids = [
            line
            for line in z.read("profile/buildids.txt").decode().splitlines()
            if line.endswith("/" + macro)
        ]
        assert len(ids) == 1
    return dict(
        zip_sha256=sha_file(artifact),
        perf_raw=raw_id,
        rustcs=len(roster),
        owner=owner,
        all_owner_samples=len(rows),
        salsa_macro_samples=counts[macro],
        salsa_build_id=ids[0].split()[0],
        per_dso=dict(sorted(counts.items())),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("ast-graph", "parser-graph", "scope-zip", "perf-zip"):
        parser.add_argument("--" + option, type=Path, required=True)
    args = parser.parse_args()
    record = {
        "ruff_python_ast": census(
            args.ast_graph,
            "61ac7ddc9923db2cd7fe4183b1d94556aafbb5f837910042efeca6921032833c",
        ),
        "ruff_python_parser": census(
            args.parser_graph,
            "7ce73523495b580ffde2a2a6f5c626f905155c550453203ecade6a2d1cea33a7",
        ),
    }
    actual = args.scope_zip
    assert (
        sha_file(actual)
        == "8474cc422216800f8a7fd467827f8afbe874cc1488f38aa1c97717b6eebc447f"
    )
    macros = {}
    owners = ("ruff_linter", "ruff_graph", "ruff_workspace", "ruff_markdown")
    with zipfile.ZipFile(actual) as z:
        u = json.loads(z.read("scope-unit-graph.json"))["units"]
        assert len(u) == 337
        for owner in owners:
            (start,) = [
                i
                for i, v in enumerate(u)
                if v["target"]["name"] == owner and v["mode"] == "check"
            ]
            todo = [start]
            seen = set()
            while todo:
                i = todo.pop()
                if i not in seen:
                    seen.add(i)
                    todo.extend(x["index"] for x in u[i]["dependencies"])
            proc = sorted(
                u[i]["target"]["name"]
                for i in seen
                if u[i]["target"]["kind"] == ["proc-macro"]
            )
            direct = sorted(
                u[x["index"]]["target"]["name"]
                for x in u[start]["dependencies"]
                if u[x["index"]]["target"]["kind"] == ["proc-macro"]
            )
            macros[owner] = dict(
                closure_units=len(seen), reachable_macros=proc, direct_macros=direct
            )
    measured = dict(
        graphs=record,
        macro_closure=macros,
        signed_23_separate_edit=actual_native_macro(args.perf_zip),
    )
    assert measured == json.loads((HERE / "census.json").read_bytes())
    print(json.dumps(measured, sort_keys=True, indent=1))


if __name__ == "__main__":
    main()
