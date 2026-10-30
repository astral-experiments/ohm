"""Capture physical reasons for the remaining ordinary Rust compilations on GNU AArch64."""
from pathlib import Path
import gzip
import json
import os
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compare
from compare import q, rt
from study import MISSING, RECHECK, change_source, digest, load, need, save, sha, source_values

NAMES = ("compact_str", "ruff_python_ast", "zmij")
FOCUS = ("compact_str", "ruff_python_ast")
FLAGS = "cargo::compiler::fingerprint=trace,cargo::core::compiler::fingerprint=trace"


def unit_files(rows, folder):
    seen = {}
    physical = {}
    interest = {}
    fragment = {s.replace("_", "-") for s in NAMES} | set(NAMES)
    for name in NAMES:
        row = rows[name]
        args = row["argv"]
        out = Path(args[args.index("--out-dir") + 1])
        suffix, = [v.partition("=")[2] for v in args if v.startswith("extra-filename=")]
        dep = out / (name + suffix + ".d")
        need(dep.is_file(), f"missing actual compiler dependency information: {dep}")
        b = dep.read_bytes()
        (folder / (name + ".d")).write_bytes(b)
        extern = {}
        for i, token in enumerate(args[:-1]):
            if token == "--extern" and "=" in args[i + 1]:
                crate, raw = args[i + 1].split("=", 1)
                p = Path(raw)
                st = p.stat()
                extern[crate] = [str(p), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, sha(p)]
        files = {}
        for p in sorted(out.iterdir()):
            if p.is_file() and (p.suffix in {".d", ".rlib", ".rmeta", ".so"} or "hash" in p.name):
                st = p.stat()
                files[p.name] = [st.st_dev, st.st_ino, st.st_nlink, st.st_size, st.st_mtime_ns, sha(p)]
        interest[name] = {"path": str(dep), "dep": digest(b), "hard": MISSING in b, "recheck": RECHECK in b,
                          "other_markers": sorted({v.decode(errors="backslashreplace") for v in re.findall(rb"/dev/null/[^\s]+", b)}),
                          "argv": args, "extern": extern, "outputs": files}
    for root in (rt.WORK / "target", rt.WORK / "shared"):
        for base, dirs, names in os.walk(root):
            here = Path(base)
            if not {".fingerprint", "fingerprint"}.intersection(here.parts):
                continue
            if not any(s in str(here) or any(s in n for n in names) for s in fragment):
                continue
            for n in sorted(names):
                p = here / n
                s = p.stat()
                if not p.is_file() or s.st_size > 256 * 1024:
                    continue
                raw = p.read_bytes()
                key = digest(raw)
                if key not in seen:
                    (folder / (key + ".fingerprint")).write_bytes(raw)
                    seen[key] = len(raw)
                physical[str(p)] = [key, s.st_dev, s.st_ino, s.st_nlink, s.st_mtime_ns, s.st_size]
    save(folder / "unit-evidence.json", {"units": interest, "fingerprint_files": physical})
    return interest


def diagnostic(name, row, env):
    folder = rt.LOG / "lowering" / name
    out = rt.ROOT / "separate-compiler-output" / name
    out.mkdir(parents=True)
    args = row["argv"][1:].copy()
    args[args.index("--out-dir") + 1] = str(out)
    emits, = [i for i, v in enumerate(args) if v.startswith("--emit=")]
    args[emits] = "--emit=link,dep-info,llvm-ir,asm,mir"
    redirected = []
    i = 0
    keys = ("incremental=", "temps-dir=", "public-api-hash-file=")
    while i < len(args):
        if args[i] in ("-Z", "-C") and i + 1 < len(args) and args[i + 1].startswith(keys):
            i += 2
        elif args[i].startswith(tuple(a + k for a in ("-Z", "-C") for k in keys)):
            i += 1
        else:
            redirected.append(args[i])
            i += 1
    need(any("ohm-check-relink-inputs" in a for a in redirected), "lost input classification")
    p = rt.record(["rustc", "+ohm", *redirected, "-Zprint-mono-items=yes"], folder / "compiler", rt.RUFF, env)
    mono = [line.decode(errors="backslashreplace") for line in p.stdout.splitlines() if line.startswith(b"MONO_ITEM ")]
    need(mono, "empty real monomorphization roster")
    dep, = out.glob("*.d")
    body = dep.read_bytes()
    (folder / "source-dependencies.d").write_bytes(body)
    sites = {}
    files = {}
    for ext in ("ll", "mir", "s"):
        counts = 0
        found = sorted(out.glob("*." + ext))
        need(found, "compiler did not emit requested lowering: " + ext)
        for f in found:
            owner = ""
            rows = []
            last_name = ""
            with f.open(errors="backslashreplace") as source:
                for line_no, line in enumerate(source, 1):
                    if ext == "ll" and line.startswith("; "):
                        last_name = line.strip()[2:]
                    if ext == "mir" and line.startswith("fn ") or ext == "ll" and line.startswith("define "):
                        owner = (last_name, line.strip().split(" {")[0])
                    if (ext == "mir" and "asm!(" in line or
                        ext == "ll" and ("module asm " in line or re.search(r"\b(?:call|invoke)\b.*\basm\b", line)) or
                        ext == "s" and any(t in line for t in ("//APP", "//NO_APP", ".incbin", "/*"))):
                        rows.append([line_no, owner, line.strip()])
            if rows:
                sites[f.name] = rows
            counts += len(rows)
            files[f.name] = [f.stat().st_size, sha(f)]
            with f.open("rb") as src, gzip.open(folder / (f.name + ".gz"), "wb", compresslevel=1) as dst:
                shutil.copyfileobj(src, dst, 2**20)
        print(name, ext, len(found), counts, flush=True)
    rec = {"unit": name, "mono_items": mono, "files": files, "sites": sites, "dep": digest(body),
           "hard": MISSING in body, "recheck": RECHECK in body, "actual_cargo_rustc": row["argv"],
           "diagnostic_rustc": redirected + ["-Zprint-mono-items=yes"]}
    save(folder / "observed.json", rec)
    return {k: v for k, v in rec.items() if k in ("dep", "hard", "recheck")}


def main():
    archive, archive_sha, native = sys.argv[1:]
    select, roles, restored = compare.installable(Path(archive), archive_sha, Path(native))
    different = select("C")
    need(len(different) == 1 and different[0].startswith("lib/librustc_driver-"), "non-matched kit")
    save(rt.LOG / "subject.json", {"source": roles["C"]["source"], "roles": {k: v["files"][different[0]][0] for k, v in roles.items()},
                                 "archive": archive_sha, "cargo": rt.TOOLS["bin/cargo"], "disk": rt.room()})
    q.prepare_graph()
    base = rt.LOG / "actual"
    base.mkdir()
    q.acquire(base, rt.ROOT / "seed")
    env = rt.environment()
    values = source_values(rt.RUFF)
    change_source(rt.RUFF, values, "old")
    searches = []
    rows = {}
    raw = {}
    seen = {}
    for stage, state, logging in (("old-empty", "old", False), ("edit", "new", False), ("settled-before", "new", False),
                                 ("fingerprint", "new", True), ("settled-after", "new", False)):
        if stage == "edit":
            change_source(rt.RUFF, values, state)
        source_env = env | ({"CARGO_LOG": FLAGS} if logging else {})
        rec = q.visit(base, stage, state, source_env, searches)
        inventory = digest(json.dumps(rec["typed"], sort_keys=True, separators=(",", ":")).encode())
        need(len(rec["typed"]) == 39 and inventory == "fe68c95a764685c7677db770a5e302996d8a18b95ed8ccf7d054a320c979b6ac", "typed inventory differs from original recorded native graph")
        native_reader = ("1a8df04825085b4b606db458fecf9ec24f2b651414eea444670226a5dfbf72f9" if state == "old" else
                         "7d4d2fd48f2ef717f19b11cf5e4f21bcea69d16d55e631301b8266d74cf8abd8")
        need(rec["reader"] == native_reader, "full reader differs from previously authenticated source+target")
        actual = load(base / stage / "native.json")["rustcs"]
        rows.update({r["crate"]: r for r in actual if r["crate"] in NAMES})
        need(set(rows) == set(NAMES), "incomplete original target compiler argv")
        raw[stage] = unit_files(rows, base / stage)
        seen[stage] = {"crates": rec["crates"], "dirty": rec["dirty"], "reader": rec["reader"],
                       "fingerprints": sha(base / stage / "unit-evidence.json"),
                       "markers": {k: [v["hard"], v["recheck"]] for k, v in raw[stage].items()}}
    need(all(sorted(seen[n]["crates"]) == sorted(FOCUS) for n in ("edit", "settled-before", "fingerprint", "settled-after")),
         "different true remaining compiler roster")
    need(len({seen[n]["reader"] for n in ("edit", "settled-before", "fingerprint", "settled-after")}) == 1
         and seen["old-empty"]["reader"] != seen["edit"]["reader"], "changed authentic external output")
    logs = gzip.decompress((base / "fingerprint/cargo/stderr.gz").read_bytes()).decode(errors="backslashreplace")
    (base / "fingerprint/dirty-lines.txt").write_text("\n".join(l for l in logs.splitlines() if any(t in l.lower() for t in
        ("stale", "is dirty", "filesystem status", "missingfile", "changedfile", "dirty reason", "dirty:", "fingerprint error"))) + "\n")
    save(rt.LOG / "ordinary-complete.json", {"phases": seen, "log_lines": len(logs.splitlines())})
    # Direct supplementary lowering always has its own directory and never updates Cargo's prior artifacts.
    results = {name: diagnostic(name, rows[name], env) for name in FOCUS if raw["settled-after"][name]["hard"]}
    save(rt.LOG / "terminal.json", {"ordinary": sha(rt.LOG / "ordinary-complete.json"), "diagnostic": results,
                                   "native_ledger": {s: sha(base / s / "native.json") for s in seen}})


if __name__ == "__main__":
    main()
