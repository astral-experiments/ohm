"""Independently decode both previous dep graphs, all published metadata, and the native substitution."""

import argparse, collections, hashlib, io, json, os, pathlib, re, shutil, struct, subprocess, sys, tarfile, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import scope_rdr as rdr


def graph_walk(raw, names):
    assert (
        raw[-13:] == b"rust-end-file"
        and raw[:4] == b"RSIC"
        and int.from_bytes(raw[4:6], "little") == 49126
    )
    offset = 7 + raw[6] + 8
    end = len(raw) - 13
    start, nroots, magic, slots, count, edges = struct.unpack_from(
        "<QQ8sQQQ", raw, end - 48
    )
    assert magic == b"OHMIDX01" and end - 48 == start + 8 * slots + 4 * nroots
    bits = (len(names) - 1).bit_length()
    rows = {}
    hist = [0] * len(names)
    seen_edges = 0
    for _ in range(count):
        flags, idx = struct.unpack_from("<HI", raw, offset)
        kind = flags & ((1 << bits) - 1)
        assert kind < len(names) and 0 <= idx < slots and idx not in rows
        key = raw[offset + 6 : offset + 22].hex()
        value = raw[offset + 22 : offset + 38].hex()
        offset += 38
        width = ((flags >> bits) & 3) + 1
        num = (flags >> (bits + 2)) - 1
        if num < 0:
            num = 0
            for shift in range(0, 64, 7):
                byte = raw[offset]
                offset += 1
                num |= (byte & 127) << shift
                if byte < 128:
                    break
            else:
                raise ValueError("excessive edge count")
        reach = [
            int.from_bytes(raw[i : i + width], "little")
            for i in range(offset, offset + width * num, width)
        ]
        offset += num * width
        hist[kind] += 1
        seen_edges += num
        rows[idx] = dict(kind=names[kind], key=key, value=value, edges=reach)
    for prior in hist:
        count = 0
        for shift in range(0, 64, 7):
            byte = raw[offset]
            offset += 1
            count |= (byte & 127) << shift
            if byte < 128:
                break
        assert count == prior
    assert raw[offset:start] == bytes([1]) and seen_edges == edges, (
        raw[offset:start],
        seen_edges,
        edges,
    )
    for n in rows.values():
        assert set(n["edges"]) <= rows.keys()
    return rows, nroots, edges


def source_arrays(body, crate, sy, tables):
    observed = {}
    h, defs, rows, exp, deps = rdr.decode(
        body,
        sy,
        tables,
        crate,
        "rustc 1.99.0-dev (Ohm metadata 3)",
        typed=observed,
        selected_tables=["inherent_impls"],
    )
    r = rdr.Reader(body, sy)
    r.pos = int.from_bytes(body[8:16], "little")
    assert r.symbol() == "x86_64-unknown-linux-gnu"
    r.take(32)
    assert r.symbol() == crate and r.byte() == 0 and r.byte() == 0
    r.string()
    r.take(8)
    assert [r.var() for _ in range(7)] == [0, 0, 3, 0, 0, 0, 0]

    def array():
        count = r.var()
        if count:
            r.var()
        return count

    before = [array() for _ in range(13)]
    assert r.byte() == 1
    groups, noncoherent, alloc = [array() for _ in range(3)]
    cohort = dict(
        local_traits=before[-1],
        trait_impl_groups=groups,
        incoherent_groups=noncoherent,
        inherent_slots=len(observed["selected_tables"]["inherent_impls"]),
    )
    assert all(v == 0 for v in cohort.values())
    return h, defs, rows, exp, deps, cohort


def recorded_events(data):
    events = [json.loads(row) for row in data.splitlines()]
    finish = [e["success"] for e in events if e["reason"] == "build-finished"]
    dirty = sorted(
        e["target"]["name"]
        for e in events
        if e["reason"] == "compiler-artifact" and not e["fresh"]
    )
    errors = [
        e["message"]["code"]["code"]
        for e in events
        if e["reason"] == "compiler-message"
        and e["message"]["level"] == "error"
        and e["message"].get("code")
    ]
    return finish, dirty, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust-source", type=Path, required=True)
    parser.add_argument(
        "--sdk",
        type=Path,
        help="Optionally repeat the genuine rustc metadata-load calls.",
    )
    args = parser.parse_args()
    sy, tables = rdr.schema(args.rust_source)
    archive = HERE / "originals.tar.xz"
    sha = lambda body: hashlib.sha256(body).hexdigest()
    assert (
        sha(archive.read_bytes())
        == "bb6b12f9c892b76c1fb1b694329d4c8cfe8d162cab06d311c5f5a7033c2d126f"
    )
    with tarfile.open(archive, "r:xz") as tar:
        raw = {m.name: tar.extractfile(m).read() for m in tar if m.isfile()}
    kinds = (HERE / "query-kinds.txt").read_bytes()
    assert (
        sha(kinds) == "8bae8ee1dd361a51f8012dc25a4c9597f67e727b6c3ae441f1a04ef8aa37cd22"
    )
    names = kinds.decode().splitlines()
    for kind, error, changed_names in [
        ("constant", "E0308", {"{{crate}}", "VALUE"}),
        ("glob", "E0659", {"{{crate}}", "second", "second::VALUE"}),
    ]:
        read = lambda file: raw[kind + "/" + file]
        meta = {}
        allbytes = {}
        for stage in (
            "original",
            "unchanged",
            "invalid",
            "clean-invalid",
            "repair",
            "clean-repair",
        ):
            finish, dirty, codes = recorded_events(read(stage + "/stdout"))
            invalid = "invalid" in stage
            assert finish == [not invalid] and codes == ([error] if invalid else [])
            if stage == "unchanged":
                assert not dirty
            meta[stage] = {}
            for n in ("origin", "facade", "consumer"):
                if invalid and n == "consumer":
                    continue
                body = read(stage + "/" + n + ".rmeta")
                allbytes[(stage, n)] = body
                meta[stage][n] = source_arrays(body, n, sy, tables)
        assert (
            meta["original"]["facade"][0]["public"]
            == meta["invalid"]["facade"][0]["public"]
        )
        a, b = meta["original"]["origin"], meta["invalid"]["origin"]
        assert (
            a[0]["global_hash"] == b[0]["global_hash"]
            and a[0]["public"] != b[0]["public"]
        )
        diff = {k: b[1][k][0] for k in b[2] if a[2].get(k) != b[2][k]}
        assert set(diff.values()) == changed_names
        for k, label in diff.items():
            occurrence = tuple(
                allbytes["original", crate].count(bytes.fromhex(k))
                for crate in ("facade", "consumer")
            )
            expected = (0, 1) if kind == "glob" and label == "{{crate}}" else (0, 0)
            assert occurrence == expected, (label, occurrence)
        assert all(a[2][k] == b[2][k] for k, v in a[1].items() if v[0] == "selected")
        for case in ("invalid", "repair"):
            assert all(
                allbytes[case, n] == allbytes["clean-" + case, n] for n in meta[case]
            )
        buf = read("original/consumer-graph.bin")
        graph, nroots, edges = graph_walk(buf, names)
        bound = next(
            k
            for k, v in a[1].items()
            if v[0] == ("VALUE" if kind == "constant" else "first::VALUE")
        )
        c = meta["original"]["consumer"]
        client_fn = next(k for k, v in c[1].items() if v[0] == "result")
        ids = lambda stable, local: {stable + local, local + stable}
        (typeck,) = [
            i
            for i, n in graph.items()
            if n["kind"] == "typeck_root" and n["key"] in ids(c[0]["stable"], client_fn)
        ]
        (target,) = [
            i
            for i, n in graph.items()
            if n["kind"] == "type_of" and n["key"] in ids(a[0]["stable"], bound)
        ]
        assert target in graph[typeck]["edges"]
        end = len(buf) - 13
        start, count, _, slots, *_ = struct.unpack_from("<QQ8sQQQ", buf, end - 48)
        roots = struct.unpack_from("<" + "I" * count, buf, start + 8 * slots)
        assert set(graph[i]["kind"] for i in roots) == {"typeck_root", "mir_borrowck"}
        assert sorted(
            n["kind"]
            for n in graph.values()
            if n["kind"] in ("resolver_for_lowering_raw", "analysis") and not n["edges"]
        ) == ["analysis", "resolver_for_lowering_raw"]
        if kind == "glob":
            second = next(k for k, v in a[1].items() if v[0] == "second")
            queue = list(roots)
            reached = set()
            while queue:
                i = queue.pop()
                if i not in reached:
                    reached.add(i)
                    queue.extend(graph[i]["edges"])
            assert not any(
                graph[i]["key"] in ids(a[0]["stable"], second) for i in reached
            )
        component = allbytes["original", "consumer"]
        prior = bytes.fromhex(a[0]["public"])
        new = bytes.fromhex(b[0]["public"])
        assert component.count(prior) == 1
        pos = component.index(prior)
        patched = component[:pos] + new + component[pos + 16 :]
        p = source_arrays(patched, "consumer", sy, tables)
        assert (
            p[1:4] == c[1:4]
            and p[0]["public"] == c[0]["public"]
            and p[0]["private"] == c[0]["private"]
        )
        assert [x for x in c[4] if c[4][x] != p[4][x]] == [
            x for x in c[4] if x.startswith("origin-")
        ]
        sub = json.loads(read("substitution.json"))
        assert (
            sub["offset"] == pos
            and sub["old"] == sha(component)
            and sub["new"] == sha(patched)
        )
        records = sub["results"]
        assert [
            records[n]["returncode"] for n in ("original", "untouched", "rebound")
        ] == [0, 1, 0] and records["untouched"]["codes"] == ["E0460"]
        for mode in ("original", "rebound"):
            assert (
                sha(read("direct-" + mode + "/reader.rmeta")) == records[mode]["rmeta"]
            )
        if args.sdk:
            sdk = args.sdk.resolve()
            manifest = json.loads(raw["factory-files.json"])
            (driver,) = (sdk / "lib").glob("librustc_driver-*.so")
            with driver.open("rb") as stream:
                assert (
                    hashlib.file_digest(stream, "sha256").hexdigest()
                    == "164ae65b41ff9db3b6853b4d66ed39c36a4f10d5082673b77487becfe8b20a58"
                )
            assert sha((sdk / "bin/rustc").read_bytes()) == manifest["bin/rustc"]
            with tempfile.TemporaryDirectory() as tmp:
                job = Path(tmp)
                (job / "toolchains").mkdir()
                (job / "toolchains/ohm").symlink_to(sdk, target_is_directory=True)
                test = job / "read.rs"
                test.write_text("pub fn check() -> u8 { consumer::result() }\n")
                env = {
                    "HOME": str(job),
                    "RUSTUP_HOME": str(job),
                    "RUSTUP_AUTO_INSTALL": "0",
                    "PATH": str(Path(shutil.which("rustup")).parent) + ":/usr/bin:/bin",
                    "LC_ALL": "C",
                }
                for mode in ("original", "untouched", "rebound"):
                    loc = job / mode
                    loc.mkdir()
                    for n in ("origin", "facade", "consumer"):
                        body = (
                            (patched if mode == "rebound" else component)
                            if n == "consumer"
                            else allbytes[
                                "original" if mode == "original" else "invalid", n
                            ]
                        )
                        (loc / ("lib" + n + ".rmeta")).write_bytes(body)
                    cmd = [
                        "rustc",
                        "+ohm",
                        str(test),
                        "--edition",
                        "2024",
                        "--crate-name",
                        "reader",
                        "--crate-type",
                        "lib",
                        "--emit",
                        "metadata",
                        "--error-format",
                        "json",
                        "--extern",
                        "consumer=" + str(loc / "libconsumer.rmeta"),
                        "-L",
                        "dependency=" + str(loc),
                        "-o",
                        str(loc / "reader.rmeta"),
                    ]
                    observed = subprocess.run(
                        cmd, env=env, capture_output=True, timeout=30
                    )
                    codes = [
                        e["code"]["code"]
                        for row in observed.stderr.splitlines()
                        if (e := json.loads(row)).get("code")
                    ]
                    assert (observed.returncode, codes) == (
                        records[mode]["returncode"],
                        records[mode]["codes"],
                    )
        print(
            kind,
            error,
            "independent fresh match;",
            len(graph),
            "nodes,",
            edges,
            "edges; actual typeck edge",
            typeck,
            target,
            "; false admission after substituting",
            pos,
        )


if __name__ == "__main__":
    main()
