"""Compile, run, and retain the actual typed consumer of the Cargo-selected library."""

import json
from pathlib import Path
import subprocess

import study as p
import physical


def read_command(folder, name, cmd, root, env, expected):
    run = subprocess.run(cmd, cwd=root, env=env, capture_output=True, stdin=subprocess.DEVNULL, timeout=180)
    for suffix, body in (("stdout", run.stdout), ("stderr", run.stderr)):
        (folder / (name + "." + suffix)).write_bytes(body)
    p.save(folder / (name + ".json"), {"argv": list(map(str, cmd)), "exit": run.returncode})
    p.need(run.returncode == expected, (name, run.returncode, run.stderr[-1200:]))
    return run


def client(where, rows, products, root, work, env, gold, bodies):
    path = where / "client"
    path.mkdir()
    src, invalid, binary = root / "option-client.rs", root / "bad-option-client.rs", root / "option-client"
    binary.unlink(missing_ok=True)
    libs = {owner: p.artifact(products, owner) for owner in (p.OWNER, "ruff_options_metadata")}
    depdirs = sorted(
        {Path(f).parent for r in products for f in r["filenames"] if f.endswith((".rlib", ".rmeta", ".so"))}
        | {q for q in (work / "target/debug/deps", work / "build/debug/deps") if q.is_dir()}
    )
    flags = ["--edition=2024", "--crate-name", "ohm_option_client", "--error-format=json"]
    for name, lib in libs.items():
        flags += ["--extern", f"{name}={lib}"]
    for directory in depdirs:
        flags += ["-L", "dependency=" + str(directory)]
    search = []
    for r in rows:
        if r["reason"] == "build-script-executed":
            for entry in r["linked_paths"]:
                if entry not in search:
                    search.append(entry)
    for entry in search:
        flags += ["-L", entry]
    read_command(path, "compile", ["rustc", "+ohm", src, *flags, "-o", binary], root, env, 0)
    native = physical.keep(binary, bodies, b"\x7fELF\x02\x01")
    for name, key, code in (("field", p.KEY, 0), ("sibling", p.SIBLING, 0), ("missing", p.MISSING, 2)):
        r = read_command(path, name, [binary, key], root, env, code)
        p.need(r.stdout == gold.get(key, b"") and not r.stderr, ("wrong actual option value", key))
    rejected = read_command(
        path,
        "invalid",
        ["rustc", "+ohm", invalid, *flags, "--emit=metadata", "-o", root / "bad-option.rmeta"],
        root,
        env,
        1,
    )
    typed = [json.loads(line) for line in rejected.stderr.splitlines()]
    errors = [
        (d.get("code") or {}).get("code") for d in typed if d.get("level") == "error" and d.get("code")
    ]
    p.need(errors == ["E0308"] and not (root / "bad-option.rmeta").exists(), "wrong downstream rejection")
    p.save(
        path / "native.json",
        {"elf": native, "libs": {k: str(v) for k, v in libs.items()}, "native_search": search},
    )
    return native
