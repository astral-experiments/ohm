"""Read the actual Rust metadata returned by the ordinary check and compile a typed client against it."""

import gzip
import hashlib
import json
from pathlib import Path
import re
from protocol import need

PROVIDERS = ("ruff_python_ast", "ruff_python_parser", "ruff_linter", "ruff_source_file", "ruff_text_size")
H = lambda data: hashlib.sha256(data).hexdigest()


def listing(name, path, body, stdout, stderr, rc):
    # Checked against the physical GNU rustc -Zls=root header, including the Cargo file suffix.
    need(
        rc == 0 and stderr == b"" and len(body) > 1024 and body.startswith(b"rust"),
        "failed metadata read, warning or empty body",
    )
    lines = stdout.decode().splitlines()
    need(
        len(lines) > 12
        and lines[0] == "Crate info:"
        and lines.count("Crate info:") == 1
        and lines.count("=External Dependencies=") == 1
        and re.fullmatch(r"name " + re.escape(name) + r"-[0-9a-f]{16}", lines[1])
        and path.name == "lib" + lines[1].removeprefix("name ") + ".rmeta"
        and re.fullmatch(r"private hash [0-9a-f]{32} stable_crate_id StableCrateId\([0-9]+\)", lines[2])
        and re.fullmatch(r"public_hash [0-9a-f]{32}", lines[3])
        and lines[4:6] == ["proc_macro false", "triple x86_64-unknown-linux-gnu"],
        "wrong physical metadata identity",
    )
    return {"bytes": len(body), "sha256": H(body), "listing": H(stdout)}


APIS = {
    "ruff_python_ast": ("[(); 56]", "[(); 64]", "[(); std::mem::size_of::<ruff_python_ast::Expr>()]"),
    "ruff_python_parser": ("bool", "u8", 'ruff_python_parser::parse_module("x = 1").is_ok()'),
    "ruff_linter": ("&'static str", "u8", "ruff_linter::VERSION"),
    "ruff_source_file": (
        "ruff_source_file::LineIndex",
        "u8",
        'ruff_source_file::LineIndex::from_source_text("a")',
    ),
    "ruff_text_size": ("u32", "u8", "ruff_text_size::TextSize::new(17).to_u32()"),
}


def client_source(ty, expression):
    return f"pub fn api() -> {ty} {{\n    {expression}\n}}\n"


def target_provider(art, name):
    # With a native host the two compilations have the same triple. Cargo's check
    # row emits only metadata; the host-side proc macro dependency emits an rlib.
    roots = [r for r in art if r["target"]["name"] == "ruff" and r["target"]["kind"] == ["bin"]]
    need(len(roots) == 1, "no unique checked Ruff root")
    target = roots[0]["profile"]
    features = {
        "ruff_python_ast": ["cache", "get-size", "salsa", "serde"],
        "ruff_linter": ["clap", "default"],
        "ruff_python_parser": [],
        "ruff_source_file": ["get-size", "serde"],
        "ruff_text_size": ["get-size", "serde"],
    }
    rows = [r for r in art if r["target"]["name"] == name and r["target"]["kind"] == ["lib"]]
    selected = [
        r
        for r in rows
        if r["profile"] == target
        and r["features"] == features[name]
        and len(r["filenames"]) == 1
        and Path(r["filenames"][0]).suffix == ".rmeta"
        and r["executable"] is None
    ]
    need(len(selected) == 1, ("missing or ambiguous target metadata provider", name, rows))
    r = selected[0]
    if name in ("ruff_source_file", "ruff_text_size"):
        host = [
            x
            for x in rows
            if x is not r
            and not x["features"]
            and x["profile"] != target
            and any(n.endswith(".rlib") for n in x["filenames"])
        ]
        need(len(rows) == 2 and len(host) == 1, ("unexpected host/target pair", name))
    return Path(r["filenames"][0]), {
        "target_kind": r["target"]["kind"],
        "features": r["features"],
        "profile": target,
    }


def exercise_client(run, src, dst, name, allowed, ty, expression, extern, search, env, tree, where):
    tag = name + ("-accepted" if allowed else "-refused")
    source = client_source(ty, expression)
    src.write_text(source)
    (where / ("api-" + tag + ".rs")).write_text(source)
    p = run(
        [
            "rustc",
            "+ohm",
            "--crate-name",
            "checked_api",
            "--crate-type=lib",
            "--edition=2024",
            "--emit=metadata",
            "--error-format=json",
            src,
            *extern,
            *search,
            "-o",
            dst,
        ],
        env,
        tree,
        where / ("api-" + tag),
        int(not allowed),
    )
    errors = [json.loads(line) for line in p.stderr.splitlines()]
    coded = [d for d in errors if d.get("level") == "error" and d.get("code")]
    if allowed:
        need(
            dst.is_file() and dst.stat().st_size > 1024 and not errors,
            "genuine checked public API rejected: " + name,
        )
    else:
        need(
            not dst.exists()
            and len(coded) == 1
            and coded[0]["code"]["code"] == "E0308"
            and any(
                s["is_primary"] and Path(s["file_name"]) == src and s["line_start"] == 2
                for s in coded[0]["spans"]
            )
            and all(
                d.get("level") != "error"
                or d in coded
                or (not d["spans"] and d["message"].startswith("aborting due to 1 previous error"))
                for d in errors
            ),
            "wrong discriminating checked API diagnostic or source: " + name,
        )
    return p


def verdict(worker, messages, env, where):
    art = [m for m in messages if m["reason"] == "compiler-artifact"]
    need(
        len(art) == 375 and sum(m["reason"] == "build-script-executed" for m in messages) == 37,
        "incomplete target/host checked Cargo graph",
    )
    index = {}
    for m in art:
        key = worker.historical.commit(
            [m["package_id"], m["target"]["name"], m["target"]["kind"], m["features"], m["profile"]]
        )
        need(key not in index, "duplicate checked Cargo unit")
        index[key] = sorted(Path(f).name for f in m["filenames"])
    files = {}
    identities = {}
    for n in PROVIDERS:
        f, unit = target_provider(art, n)
        need(
            f.is_file()
            and f.resolve() == f
            and any(f.is_relative_to(worker.WORK / k) for k in ("target", "build")),
            ("foreign/symlinked returned metadata", f),
        )
        before = f.stat()
        body = f.read_bytes()
        result = worker.native.run(
            ["rustc", "+ohm", "-Zls=root", f], env, worker.kit.TREE, where / ("listing-" + n)
        )
        desc = listing(n, f, body, result.stdout, result.stderr, result.returncode)
        need(
            f.stat() == before
            or (f.stat().st_dev, f.stat().st_ino, f.stat().st_size, f.stat().st_ctime_ns)
            == (before.st_dev, before.st_ino, before.st_size, before.st_ctime_ns),
            "metadata changed during decoding",
        )
        stash = worker.OUT / "check-bodies"
        stash.mkdir(exist_ok=True)
        body_path = stash / (desc["sha256"] + ".gz")
        if not body_path.exists():
            body_path.write_bytes(gzip.compress(body, compresslevel=1, mtime=0))
        need(gzip.decompress(body_path.read_bytes()) == body, "retained metadata bytes differ")
        identities[n] = desc | {"unit": unit, "path": str(f.relative_to(worker.WORK))}
        files[n] = f
    need(set(files) == set(PROVIDERS), "incomplete physical providers")
    dependency_dirs = {
        Path(f).parent for m in art for f in m["filenames"] if f.endswith((".rmeta", ".rlib", ".so"))
    }
    extern = [v for n in PROVIDERS for v in ("--extern", n + "=" + str(files[n]))]
    search = [v for p in sorted(dependency_dirs) for v in ("-L", "dependency=" + str(p))]
    temp = worker.ROOT / "typed-check-reader"
    temp.mkdir(exist_ok=True)
    verdicts = {}
    for name, (good, bad, expression) in APIS.items():
        for allowed, ty in ((True, good), (False, bad)):
            tag = name + ("-accepted" if allowed else "-refused")
            src = temp / (name + ".rs")
            dst = temp / "client.rmeta"
            dst.unlink(missing_ok=True)
            p = exercise_client(
                worker.native.run,
                src,
                dst,
                name,
                allowed,
                ty,
                expression,
                extern,
                search,
                env,
                worker.kit.TREE,
                where,
            )
            verdicts[tag] = [p.returncode, H(p.stdout), H(p.stderr)]
    return {"providers": identities, "typed": verdicts, "graph": index}


def equivalent(current, empty):
    need(
        set(current["providers"]) == set(empty["providers"]) == set(PROVIDERS) and current == empty,
        "incremental checked metadata, physical listings, graph or typed verdict differ from independent empty",
    )


def cross(before, after):
    need(
        set(before["providers"]) == set(after["providers"]) == set(PROVIDERS)
        and before["typed"] == after["typed"]
        and len(after["typed"]) == 10,
        "changed semantic provider or missing positive/contradictory native client",
    )
    differences = {}
    for name in PROVIDERS:
        x, y = before["providers"][name], after["providers"][name]
        if (x["sha256"], x["listing"]) != (y["sha256"], y["listing"]):
            differences[name] = {
                "parent": x,
                "candidate": y,
                "actual_per_provider_typed_clients": {
                    k: v for k, v in after["typed"].items() if k.startswith(name + "-")
                },
            }
    return {
        "complete_byte_and_listing_equality": not differences,
        "differences": differences,
        "typed_clients": after["typed"],
    }
