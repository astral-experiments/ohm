"""Preserve the five previously regenerated native objects and their real upstream metadata."""

import gzip
import hashlib
import json
from pathlib import Path
import stat

from contract import require
from inputs import load, save


SUBJECT = {
    "ty_python_core": (169, {"805iflb9n0q9vsr9561jcffuz.o", "dq8k7f7y82bb6drjtju51q4u0.o"}),
    "ty_python_semantic": (
        256,
        {
            "a10661ylyumg6xywz4uq3obqi.o",
            "b2mii351fcyt5n2vbh189aiul.o",
            "ev229d563129e3p76rvyj1a1r.o",
        },
    ),
}
STATES = {
    "S1/prior-repeat": "original",
    "S1/edited": "reversed",
    "S1/restored": "original",
    "T/prior-repeat": "original",
    "T/edited": "reversed",
    "T/restored": "original",
    "clean/reversed": "reversed",
    "clean/original": "original",
}
MAGIC = b"rust\0\0\0\n"
ISSUER = b"rustc 1.99.0-dev (c79998a5c 2026-10-30) (ohm-1.99.0-21) (Ohm metadata 1)"


def original(path, slot, cas, keep=False):
    rel = path.relative_to(slot)
    require(
        path.resolve() == slot.resolve() / rel and ".." not in rel.parts,
        ("noncanonical compiler output", path),
    )
    before = path.stat()
    limit = (128 if keep else 1024) * 2**20
    require(stat.S_ISREG(before.st_mode) and 0 < before.st_size < limit, str(path))
    with path.open("rb") as f:
        if keep:
            data = f.read()
            key = hashlib.sha256(data).hexdigest()
            blob = cas / (key + ".gz")
            if not blob.exists():
                with blob.open("xb") as dest:
                    dest.write(gzip.compress(data, compresslevel=2, mtime=0))
        else:
            key = hashlib.file_digest(f, "sha256").hexdigest()
    finish = path.stat()
    ident = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    require(ident(before) == ident(finish), ("compiler output changed during capture", path))
    return [key, before.st_size, before.st_dev, before.st_ino, before.st_mtime_ns, str(rel)]


def capture(root, folder, products, cas):
    cas.mkdir(exist_ok=True)
    slot = root / "slot"
    files = {}
    for crate in ("ruff_notebook", *SUBJECT):
        meta = Path(products[crate])
        files[crate] = {"rmeta": original(meta, slot, cas, True)}
        if crate == "ruff_notebook":
            files[crate]["rlib"] = original(meta.with_suffix(".rlib"), slot, cas, True)
            continue
        expected, selected = SUBJECT[crate]
        inc = slot / "target/debug/incremental"
        sessions = [p for p in inc.glob(f"*/{crate}-*/s-*") if p.is_dir()]
        require(
            len(sessions) == 1 and not sessions[0].name.endswith("-working"),
            ("ambiguous session", crate),
        )
        caches = {}
        for name in ("dep-graph.bin", "query-cache.bin"):
            path = sessions[0] / name
            require(
                path.samefile(sessions[0] / ("ohm-build-" + name)),
                ("different cached build artifact", path),
            )
            caches[name] = original(path, slot, cas)
        files[crate]["caches"] = caches
        objects = {p.name: original(p, slot, cas, p.name in selected) for p in sessions[0].glob("*.o")}
        require(
            len(objects) == expected and selected <= set(objects), ("wrong actual codegen units", crate)
        )
        files[crate]["objects"] = objects
    save(folder / "heavy-products.json.gz", files)


def reopen(out):
    seen = set()
    states = {}
    slot = Path(load(out / "environment.json")["cwd"]).parent / "slot"
    for label in STATES:
        folder = out / label
        rows = load(folder / "heavy-products.json.gz")
        clean = label.startswith("clean/")
        stdout = folder / ("stdout.jsonl.gz" if clean else "stdout.gz")
        cargo = [json.loads(line) for line in gzip.decompress(stdout.read_bytes()).splitlines()]
        headers = load(folder / "workspace-headers.json.gz") if label.startswith("T/") else {}
        roots = load(folder / "workspace-rmeta.json") if clean else {}
        require(set(rows) == set(SUBJECT) | {"ruff_notebook"}, "unexpected heavy crate roster")
        for crate, files in rows.items():
            returned = [
                r for r in cargo if r["reason"] == "compiler-artifact" and r["target"]["name"] == crate
            ]
            require(len(returned) == 1, ("ambiguous Cargo owner", crate))
            artifact = returned[0]
            source = f"crates/{crate}/src/lib.rs"
            require(
                artifact["target"]["kind"] == ["lib"]
                and not artifact["profile"]["test"]
                and Path(artifact["target"]["src_path"]) == slot.parent / "ruff" / source,
                ("wrong Cargo source", crate),
            )
            returned_paths = {str(Path(f).relative_to(slot)) for f in artifact["filenames"]}
            rmeta = files["rmeta"]
            require(rmeta[-1] in returned_paths, "a compiler output was not returned by Cargo")
            if headers:
                h = headers[rmeta[-1]]
                require(
                    [h["sha256"], h["size"], h["dev"], h["ino"]] == rmeta[:4]
                    and (h["source"], h["target"]) == (source, crate),
                    "independent metadata/header mismatch",
                )
            if roots:
                key = json.dumps([source, ["lib"], False, Path(rmeta[-1]).name], separators=(",", ":"))
                require(
                    [roots[key]["sha256"], roots[key]["size"]] == rmeta[:2], "different clean metadata"
                )
            expected = {"rmeta", "rlib"} if crate == "ruff_notebook" else {"rmeta", "objects", "caches"}
            require(set(files) == expected, ("missing native or metadata output", crate))

            def check(row, kind):
                key, size, dev, ino, mtime, raw = row
                path = Path(raw)
                require(
                    len(key) == 64
                    and all(c in "abcdef0123456789" for c in key)
                    and not path.is_absolute()
                    and ".." not in path.parts
                    and size > 0
                    and dev >= 0
                    and ino > 0
                    and mtime > 0,
                    "invalid compiler file record",
                )
                if not kind:
                    return
                seen.add(key)
                data = gzip.decompress((out / "heavy-cas" / (key + ".gz")).read_bytes())
                require(
                    len(data) == size and hashlib.sha256(data).hexdigest() == key,
                    "invalid native CAS payload",
                )
                if kind == "rmeta":
                    require(
                        path.name.startswith("lib" + crate + "-")
                        and path.suffix == ".rmeta"
                        and data.startswith(MAGIC)
                        and 16 < int.from_bytes(data[8:16], "little") < size
                        and ISSUER in data[16:160],
                        ("wrong signed metadata", path),
                    )
                elif kind == "rlib":
                    require(
                        path.name.startswith("lib" + crate + "-")
                        and path.suffix == ".rlib"
                        and data.startswith(b"!<arch>\n"),
                        ("wrong native Rust archive", path),
                    )
                else:
                    require(
                        path.name == kind
                        and data.startswith(b"\x7fELF\x02\x01\x01")
                        and data[16:20] == b"\x01\x00\x3e\x00",
                        ("wrong x86-64 relocatable object", path),
                    )

            check(files["rmeta"], "rmeta")
            if crate == "ruff_notebook":
                require(
                    files["rlib"][-1] in returned_paths,
                    "edited notebook rlib was not returned by Cargo",
                )
                check(files["rlib"], "rlib")
            else:
                require(
                    set(files["caches"]) == {"dep-graph.bin", "query-cache.bin"},
                    "missing original cache witnesses",
                )
                for name, row in files["caches"].items():
                    require(Path(row[-1]).name == name, "wrong cache witness filename")
                    check(row, None)
                total, selected = SUBJECT[crate]
                objects = files["objects"]
                require(
                    len(objects) == total
                    and selected <= objects.keys()
                    and len({(v[2], v[3]) for v in objects.values()}) == total,
                    ("wrong object identities", crate),
                )
                for name, row in objects.items():
                    require(Path(row[-1]).name == name, "mismatched native filename")
                    check(row, name if name in selected else None)
        states[label] = rows
    require(
        {p.name for p in (out / "heavy-cas").iterdir()} == {k + ".gz" for k in seen},
        "unknown native CAS member",
    )
    transitions = {}
    pairs = [
        (lane + "/" + left, lane + "/" + right)
        for lane in ("S1", "T")
        for left, right in (("prior-repeat", "edited"), ("edited", "restored"))
    ]
    for left, right in pairs:
        result = {}
        for crate, (_, selected) in SUBJECT.items():
            a, b = (states[k][crate]["objects"] for k in (left, right))
            require(a.keys() == b.keys(), ("different CGU roster", crate))
            replaced = {n for n in a if a[n][1:5] != b[n][1:5]}
            changed = {n for n in a if a[n][0] != b[n][0]}
            require(
                replaced == selected and changed <= selected,
                ("unexpected dirty objects", crate, replaced, changed),
            )
            result[crate] = {"replaced": sorted(replaced), "different_contents": sorted(changed)}
        transitions[right] = result
    clean = {}
    for label, state in STATES.items():
        if label.startswith("clean/"):
            continue
        ref = states["clean/" + state]
        clean[label] = {
            crate: {
                "rmeta": rows["rmeta"][:2] == ref[crate]["rmeta"][:2],
                "native": (
                    rows["rlib"][:2] == ref[crate]["rlib"][:2]
                    if crate == "ruff_notebook"
                    else all(v[:2] == ref[crate]["objects"][n][:2] for n, v in rows["objects"].items())
                ),
            }
            for crate, rows in states[label].items()
        }
    return {"distinct_originals": len(seen), "transitions": transitions, "empty_comparisons": clean}
