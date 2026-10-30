"""Identify every active Rust/LLVM inline-assembly site in the locked Ruff dependency."""
import gzip
import hashlib
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ohm-aarch64-linux"))
import qualify as q
import runtime as rt
from study import MISSING, RECHECK, ZMIJ_LIB, digest, load, need, save, sha

VECTOR = b'asm!("/*{:v}*/", inout(vreg) extended);'
GENERAL = rb'asm!\("/\*\{0\}\*/", inout\(reg\) (c|hundred_million|digit)\);'


def trace_assembly(root, row, env):
    original = row["argv"][1:]
    files = [p for p in map(Path, original) if p.name == "lib.rs" and "zmij-1.0.10" in p.parts]
    need(len(files) == 1 and sha(files[0]) == ZMIJ_LIB, "missing literal Cargo src/lib.rs")
    src = files[0]
    text = src.read_bytes()
    need(text.count(VECTOR) == 1 and set(re.findall(GENERAL, text)) == {b"c", b"hundred_million", b"digit"}
         and len(re.findall(rb"\basm!\(", text)) == 4, "locked crate has different assembly")
    need(any("ohm-check-relink-inputs" in arg for arg in original), "real checked-input compiler flag absent")
    body = {}
    for name, disable_vec, disable_reg in (("original", False, False), ("without-vector", True, False),
                                           ("without-general", False, True), ("without-both", True, True)):
        folder = rt.ROOT / "diagnostic" / name
        out = folder / "out"
        out.mkdir(parents=True)
        # The real source and Cargo products remain intact. Only the audit copies contain the negative probes.
        if disable_vec or disable_reg:
            shutil.copytree(src.parent, folder / "src")
            source = folder / "src/lib.rs"
            contents = text.replace(VECTOR, b"") if disable_vec else text
            if disable_reg:
                contents, count = re.subn(GENERAL, b"", contents)
                need(count == 3, "wrong scalar diagnostic edits")
            source.write_bytes(contents)
        else:
            source = src
        argv = list(original)
        argv[argv.index(str(src))] = str(source)
        argv[argv.index("--out-dir") + 1] = str(out)
        emits = [i for i, token in enumerate(argv) if token.startswith("--emit=")]
        need(len(emits) == 1, "ambiguous Cargo emission operand")
        argv[emits[0]] = "--emit=link,dep-info,llvm-ir,asm,mir"
        # Probes must not write to any ordinary Cargo auxiliary output.
        skip = ("incremental=", "temps-dir=", "public-api-hash-file=")
        cleaned = []
        i = 0
        while i < len(argv):
            val = argv[i]
            if val in ("-C", "-Z") and i + 1 < len(argv) and argv[i + 1].startswith(skip):
                i += 2
                continue
            if val.startswith(tuple(prefix + key for prefix in ("-C", "-Z") for key in skip)):
                i += 1
                continue
            cleaned.append(val)
            i += 1
        run = rt.record(["rustc", "+ohm", *cleaned, "-Zprint-mono-items=yes"],
                        root / name / "compile", rt.RUFF, env)
        items = sorted(x.decode(errors="backslashreplace") for x in run.stdout.splitlines() if x.startswith(b"MONO_ITEM "))
        need(items, "rustc emitted no monomorphization inventory")
        deps, = out.glob("*.d")
        obs = {}
        for suffix in ("mir", "ll", "s"):
            observations = []
            hashes = {}
            for path in sorted(out.glob("*." + suffix)):
                data = path.read_bytes()
                hashes[path.name] = digest(data)
                owner = ""
                for n, line in enumerate(data.decode(errors="replace").splitlines(), 1):
                    if suffix == "mir" and line.startswith("fn ") or suffix == "ll" and line.startswith("define "):
                        owner = line.split(" {")[0]
                    if (suffix == "mir" and 'asm!(' in line or suffix == "ll" and re.search(r"\b(?:asm|module asm)\b", line)
                            or suffix == "s" and any(v in line for v in ("//APP", "//NO_APP", "/*", ".incbin"))):
                        observations.append([path.name, n, owner, line.strip()])
                artifact = root / name / (path.name + ".gz")
                artifact.write_bytes(gzip.compress(data, compresslevel=2, mtime=0))
                need(digest(gzip.decompress(artifact.read_bytes())) == digest(data), "corrupt compiler stream")
            need(hashes, "missing generated ." + suffix)
            obs[suffix] = {"files": hashes, "sites": observations}
        roster = [x for x in obs["ll"]["sites"] if re.search(r"\b(?:call|invoke)\b.*\basm\b", x[3])]
        hard = MISSING in deps.read_bytes()
        fresh = RECHECK in deps.read_bytes()
        body[name] = {"src": sha(source), "mono_items": items, "llvm_inline": roster, "diagnostics": obs,
                      "dep_info": sha(deps), "hard": hard, "recheck": fresh}
        (root / name / "depinfo").write_bytes(deps.read_bytes())
        save(root / name / "observed.json", body[name])
    need(all(body[n]["hard"] and not body[n]["recheck"] for n in ("original", "without-vector", "without-general")),
         "not independently attributable to both classes")
    need(not body["without-both"]["hard"] and not body["without-both"]["recheck"], "unexplained blocker after both removals")
    save(root / "complete.json", {n: {k: v[k] for k in ("src", "hard", "recheck", "dep_info")} | {
        "mono_items": len(v["mono_items"]), "llvm_inline": len(v["llvm_inline"])} for n, v in body.items()})


def graph():
    rt.room()
    q.prepare_graph()
    root = rt.LOG / "genuine-ruff"
    q.acquire(root, rt.ROOT / "seed")
    env = rt.environment()
    searches = []
    seed = q.visit(root, "cold", "old", env, searches)
    unchanged = q.visit(root, "unchanged", "old", env, searches)
    need(seed["marker"]["hard"] and unchanged["marker"]["hard"], "unreproduced original blocker")
    original = load(root / "cold/native.json")["rustcs"]
    zmij, = [r for r in original if r["crate"] == "zmij"]
    need(zmij["terminal"] == [0] and not zmij["link_only"], "no genuine cold zmij")
    trace_assembly(rt.LOG / "all-mono", zmij, env)


if __name__ == "__main__":
    graph()
