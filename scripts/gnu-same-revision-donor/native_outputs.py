"""Reopen qualified GNU ELF members of actual rustc rlibs and execute the same Rust client."""

import gzip
import hashlib
import json
import os
import re
import struct
import subprocess
from pathlib import Path
from binding import digest, need, sha


def write(path, data):
    if not isinstance(data, bytes):
        data = (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with path.open("xb") as dest:
        dest.write(gzip.compress(data, compresslevel=1, mtime=0) if path.suffix == ".gz" else data)


def read(path):
    raw = path.read_bytes()
    return gzip.decompress(raw) if path.suffix == ".gz" else raw


def run(argv, env, cwd, out, tag, code=0):
    cmd = list(map(str, argv))
    c = subprocess.run(
        cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=900
    )
    write(out / (tag + ".stdout.gz"), c.stdout)
    write(out / (tag + ".stderr.gz"), c.stderr)
    write(
        out / (tag + ".json"),
        dict(
            argv=cmd,
            cwd=str(cwd),
            code=c.returncode,
            stdout=digest(c.stdout),
            stderr=digest(c.stderr),
        ),
    )
    need(c.returncode == code, (tag, c.returncode, c.stderr[-1500:]))
    return c


def store(cas, data):
    key = digest(data)
    dst = cas / (key + ".gz")
    if dst.exists():
        need(read(dst) == data, "CAS collision")
    else:
        write(dst, data)
    return [len(data), key]


def objects(cas, file, owner):
    data = file.read_bytes()
    return archive(data, owner, lambda b: store(cas, b), store(cas, data))


def archive(data, owner, record, whole):
    need(data[:8] == b"!<arch>\n", "foreign rlib")
    pos = 8
    table = None
    rows = {}
    other = {}
    while pos < len(data):
        header = data[pos : pos + 60]
        need(len(header) == 60 and header[58:] == b"`\n", "invalid ar header")
        field = header[:16].rstrip().decode()
        size = int(header[48:58])
        start = pos + 60
        body = data[start : start + size]
        need(len(body) == size, "short archive member")
        pos = start + size + size % 2
        if field == "//":
            table = body
            name = field
        elif field.startswith("/") and field[1:].isdigit():
            n = int(field[1:])
            need(table is not None and 0 <= n < len(table), "invalid GNU name offset")
            name = table[n : table.index(b"/\n", n)].decode()
        else:
            name = field.removesuffix("/") if field not in ("/", "/SYM64/") else field
        if name.endswith(".o"):
            hit = re.fullmatch(
                "(" + re.escape(owner) + r"-[a-f0-9]+\.[0-9a-z]+)(?:\.([a-z0-9]{7}))?\.rcgu\.o",
                name,
            )
            need(
                hit
                and body[:6] == b"\x7fELF\x02\x01"
                and struct.unpack_from("<HH", body, 16) == (1, 62)
                and hit[1] not in rows,
                "wrong or duplicate native CGU",
            )
            rows[hit[1]] = record(body)
        else:
            need(name not in other, "duplicate archive name")
            other[name] = [size, digest(body)]
    need(pos == len(data) and rows and "lib.rmeta" in other, "incomplete native archive")
    return {"cgus": rows, "non_native": other, "rlib": whole}


def negative(stderr, path):
    ds = [json.loads(l) for l in stderr.splitlines()]
    errors = [r for r in ds if r.get("level") == "error" and r["code"]]
    return (
        len(errors) == 1
        and errors[0]["code"]["code"] == "E0308"
        and [s["file_name"] for s in errors[0]["spans"] if s["is_primary"]] == [str(path)]
        and b"internal compiler error" not in stderr
    )


def client(env, tree, work, out, cas, typed, width, flavor, client_source):
    if len(typed) != 37:
        raise ValueError("not the preregistered 37 returned artifacts")
    libs = {}
    search = set()
    products = {}
    role_ids = []
    for row in typed:
        paths = [Path(p) for p in row["filenames"]]
        need(
            paths
            and all(
                p.is_file()
                and not p.is_symlink()
                and p.resolve() == p
                and any(p.is_relative_to(work / i) for i in ("target", "build"))
                for p in paths
            ),
            "unowned actual artifact",
        )
        search.update(p.parent for p in paths if p.suffix in (".rlib", ".rmeta", ".so"))
        owner = row["target"]["name"]
        role_ids.append(
            [
                row["package_id"].replace(str(tree), "/__ENROLLED_RUFF__"),
                owner,
                row["target"]["kind"],
                row["target"]["crate_types"],
                row["features"],
                row["profile"],
            ]
        )
        if owner not in ("ruff_python_ast", "ruff_python_edits", "ruff_text_size"):
            continue
        (lib,) = [p for p in paths if p.suffix == ".rlib"]
        need(owner not in libs, "multiple provider variants")
        libs[owner] = lib
        if owner == "ruff_text_size":
            continue
        products[owner] = objects(cas, lib, owner)
        listing = run(["rustc", "+ohm", "-Zls=root", lib], env, tree, out, "listing-" + owner)
        public = re.findall(rb"^public_hash ([0-9a-f]{32})$", listing.stdout, re.M)
        need(len(public) == 1 and not listing.stderr, "foreign metadata listing")
        products[owner]["public"] = public[0].decode()
    need(
        len(libs) == 3
        and len(products["ruff_python_edits"]["cgus"]) == 3
        and (width != 56 or len(products["ruff_python_ast"]["cgus"]) == 94),
        "missing provider or native members",
    )
    exe = work / "returned-native-client"
    src = work / "returned-native-client.rs"
    wrongout = work / "returned-wrong.rmeta"
    args = ["rustc", "+ohm", "--edition=2024", "--crate-name", "ast_consumer_verify"]
    for n, p in sorted(libs.items()):
        args += ["--extern", n + "=" + str(p)]
    for p in sorted(search):
        args += ["-L", "dependency=" + str(p)]
    body = client_source.read_bytes()
    src.write_bytes(body)
    write(out / "client-input.rs", body)
    exe.unlink(missing_ok=True)
    actual = run(args + ["-o", exe, src], env, tree, out, "client")
    need(not actual.stderr, "unexpected external Rust diagnostic")
    runtime = {}
    for ext, val in (("pyi", flavor), ("py", "Python")):
        x = run([exe, ext], env, tree, out, "run-" + ext)
        need(
            x.stdout == f"{width} x {val}\n".encode() and not x.stderr, "wrong actual Ruff behavior"
        )
        runtime[ext] = x.stdout.decode()
    elf = store(cas, exe.read_bytes())
    wrongout.unlink(missing_ok=True)
    src.write_bytes(
        body + f"\nconst _: [(); {120-width}] = [(); std::mem::size_of::<Expr>()];\n".encode()
    )
    write(out / "wrong-input.rs", src.read_bytes())
    err = run(
        args + ["--emit=metadata", "--error-format=json", "-o", wrongout, src],
        env,
        tree,
        out,
        "wrong",
        1,
    )
    need(
        not wrongout.exists() and negative(err.stderr, src),
        "incorrect contradictory external client",
    )
    return dict(
        products=products,
        provider_paths={k: str(v) for k, v in libs.items()},
        native=runtime,
        elf=elf,
        graph=sorted(role_ids, key=lambda x: json.dumps(x, sort_keys=True)),
    )
