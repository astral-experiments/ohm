"""Join actual process identities, Cargo products, cached recipes and the separate fingerprint trace."""
from __future__ import annotations

import collections
import gzip
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from linux_common import SUBJECTS, digest, event, need

RON = "registry|ron@0.12.0|lib"
DIAG = "diagnostic-unchanged"
LOG = "cargo::compiler=info,cargo::compiler::fingerprint=info"
LOG_PREFIX = "cargo::compiler::fingerprint: "

def entries(products, returned):
    matches = [a for a in products if a["target"]["name"] == "ron" and a["target"]["kind"] == ["lib"]
               and a["package_id"].endswith("#ron@0.12.0")]
    need(len(matches) == 1, "ambiguous ordinary Ron producer")
    return {**{k: returned[k] for k in SUBJECTS}, RON: matches[0]}

def literal_output(a, ron=False):
    if ron:
        files = [p for p in a["filenames"] if p.endswith(".rlib")]
        need(len(files) == 1, "ambiguous regular Ron rlib")
        return Path(files[0])
    p = Path(a["executable"])
    need(p.is_absolute() and p.parent.name == "out", "noncanonical test product " + str(p))
    return p

def resolver(argv):
    if "--out-dir" not in argv or "--crate-name" not in argv:
        return None
    opts = [v for k, v in zip(argv, argv[1:]) if k == "-C"] + [v[2:] for v in argv if v.startswith("-C") and len(v) > 2]
    ext = [v.partition("=")[2] for v in opts if v.startswith("extra-filename=")]
    if len(ext) != 1 or not re.fullmatch("-[0-9a-f]{12,16}", ext[0]):
        return None
    directory = Path(argv[argv.index("--out-dir")+1])
    crate = argv[argv.index("--crate-name")+1]
    if crate == "ron" and "--test" not in argv:
        return directory / ("libron" + ext[0] + ".rlib")
    # Four original harness=false integration tests use a normal binary entry point.
    return directory / (crate + ext[0])

def group_by_product(products, returned, rows, actual, wild, cwd, exits):
    return join(entries(products, returned), rows, actual, wild, cwd, exits)

def join(items, rows, actual, wild, cwd, exits):
    outputs = {literal_output(a, k == RON): k for k, a in items.items()}
    need(len(outputs) == len(items), "ambiguous observed artifact paths")
    by_pid = {r["pid"]: r for r in actual["compilers"]}
    need(len(by_pid) == len(actual["compilers"]), "duplicate physical compiler PID")
    compilers = collections.defaultdict(list)
    for pid, line in rows:
        c = by_pid.get(pid)
        if not c or c["argv_sha256"] != digest(line.encode()):
            continue
        _, argv = event(line.encode())
        out = resolver(argv)
        if out not in outputs:
            continue
        key = outputs[out]
        a = items[key]
        if c["mode"] == "link-only":
            need(key != RON and [v for v in argv if v.endswith(".rlink")] == [str(out.with_suffix(".rlink"))],
                 "link-only PID did not consume its own recipe")
        else:
            src = Path(a["target"]["src_path"])
            need(any(v.endswith(".rs") and (Path(cwd) / v) == src for v in argv), "full PID did not read its Cargo source")
        opts = [v for k, v in zip(argv, argv[1:]) if k == "-Z"] + [v[2:] for v in argv if v.startswith("-Z") and v != "-Z"]
        compilers[key].append(c | {"exit": exits[pid], "out_dir": str(out.parent), "extra_filename": "-" + out.stem.rsplit("-", 1)[-1],
                                  "test_harness": "--test" in argv, "emit": [v for v in argv if v.startswith("--emit=")],
                                  "incremental": [v for v in argv if v.startswith("incremental=") or v.startswith("-Cincremental=")],
                                  "z_relink": [v for v in opts if "rlink" in v or "relink" in v or v == "link-only"]})
    result = {}
    for key, a in items.items():
        cs = compilers[key]
        links = [r for r in wild if r["unit"] == key]
        succeeded = [c["mode"] for c in cs if c["exit"] == "0"]
        need(not cs or succeeded, "returned product lacks a successful compiler after a failed attempt")
        need(key == RON or bool(links) == bool(succeeded), "compiler/Wild owner mismatch for " + key)
        need(not a["fresh"] or not cs, "fresh Cargo product unexpectedly had a compiler")
        status = ("+".join(sorted(set(succeeded))) if cs else
                  "fresh" if a["fresh"] else "dirty-without-rustc")
        result[key] = {"cargo_fresh": a["fresh"], "mode": status, "rustc": cs, "wild": links,
                       "product": str(literal_output(a, key == RON))}
    return result

def log_reasons(stderr, items):
    lines = [l.split(LOG_PREFIX, 1)[1] for l in stderr.decode().splitlines() if LOG_PREFIX in l]
    by_key = collections.defaultdict(list)
    for i, raw in enumerate(lines):
        if not raw.startswith(("fingerprint dirty for ", "fingerprint error for ")):
            continue
        label = "err: " if raw.startswith("fingerprint error") else "dirty: "
        need(i + 1 < len(lines) and lines[i+1].strip().startswith(label), "unmatched fingerprint message")
        # Native Cargo's target Debug rendering includes the full source, mode and package name.
        head = re.match(r"^fingerprint (?:dirty|error) for (\S+) v.+?/(Build|RunCustomBuild|Test|Check|Doc|Doctest)/TargetInner ", raw)
        mode_src = re.findall(r'"([^"]+\.rs)"', raw)
        if not head or len(mode_src) != 1:
            continue
        by_key[(head[1], head[2], mode_src[0])].append([raw, lines[i+1].strip()])
    result = {}
    for key, a in items.items():
        package = "ron" if key == RON else key.split("|")[0].split("/")[-1]
        observed = by_key[(package, "Build" if key == RON else "Test", a["target"]["src_path"])]
        if not a["fresh"]:
            need(observed, "dirty tracked product lacks immediate Cargo fingerprint reason: " + key)
        result[key] = observed
    return result

def blob(root, path):
    """Keep literal .rlink and manifest bytes once per content identity."""
    if not path.exists():
        return None
    need(path.is_file() and not path.is_symlink() and path.stat().st_size <= (16<<20), "invalid sidecar " + str(path))
    raw = path.read_bytes()
    key = digest(raw)
    dest = root / (key + ".gz")
    if not dest.exists():
        with dest.open("xb") as f:
            f.write(gzip.compress(raw, compresslevel=1, mtime=0))
    s = path.stat()
    return {"path": str(path), "sha256": key, "size": s.st_size, "dev": s.st_dev, "ino": s.st_ino, "mtime_ns": s.st_mtime_ns}

def facts(folder, tracked):
    """Snapshot the saved products without changing their contents or timestamps used by Cargo."""
    storage = folder.parents[1] / "recipe-blobs"
    storage.mkdir(exist_ok=True)
    result = {}
    for key, value in tracked.items():
        out = Path(value["product"])
        unit = out.parent.parent
        need(out.parent.name == "out" and re.fullmatch("[0-9a-f]{12,16}", unit.name), "unexpected Cargo unit layout")
        fpdir = unit / "fingerprint"
        names = sorted(fpdir.iterdir()) if fpdir.exists() else []
        need(all(not p.is_symlink() for p in names), "symlinked Cargo fingerprint member")
        dep = out.with_suffix(".d")
        if key == RON:
            dep = dep.with_name(dep.name.removeprefix("lib"))
        inputs = {"fingerprint_dir": str(fpdir), "fingerprints": {p.name: blob(storage,p) for p in names if p.is_file()},
                  "nested_fingerprint_dirs": [p.name for p in names if p.is_dir()],
                  "rustc_depinfo": blob(storage,dep)}
        if key == RON:
            result[key] = inputs
            continue
        recipe = out.with_suffix(".rlink")
        manifest = out.with_suffix(".rlink-cache.json")
        obj_dir = out.with_suffix(".rlink-objects")
        r, m = blob(storage, recipe), blob(storage, manifest)
        real = out.stat()
        row = {"rlink": r, "manifest": m, "executable_stat": [real.st_dev, real.st_ino, real.st_size, real.st_mtime_ns],
               "object_dir": str(obj_dir), "object_files": {}, "rlink_blake3": None}
        paths = []
        if r:
            paths.append(recipe)
        if obj_dir.exists():
            need(obj_dir.is_dir() and not obj_dir.is_symlink(), "unsafe object directory")
            paths.extend(sorted(p for p in obj_dir.iterdir() if p.suffix in (".o", ".obj")))
        need(all(p.is_file() and not p.is_symlink() for p in paths), "unsafe retained object")
        if paths:
            output = subprocess.check_output(["b3sum", "--", *paths], text=True).splitlines()
            need(len(output) == len(paths), "incomplete physical BLAKE3 census")
            for file, line in zip(paths, output):
                h, sep, label = line.partition("  ")
                need(sep and label == str(file) and re.fullmatch("[a-f0-9]{64}", h), "invalid BLAKE3 output")
                if file == recipe:
                    row["rlink_blake3"] = h
                else:
                    st = file.stat()
                    row["object_files"][str(file)] = [st.st_size, st.st_dev, st.st_ino, h]
        result[key] = row | inputs
    need(sum(p.stat().st_size for p in storage.iterdir()) <= 512 << 20, "portable recipe/fingerprint escrow exceeds 512 MiB")
    return result

def recipe_matches(product, row, load):
    """Report the observable validation predicates. The Cargo-specific internal proof checksum is opaque here."""
    exe = Path(product)
    bodies = []
    for name, suffix in (("rlink", ".rlink"), ("manifest", ".rlink-cache.json")):
        entry = row[name]
        if entry is None:
            bodies.append(None)
            continue
        raw = load(entry["sha256"])
        need(digest(raw) == entry["sha256"] and len(raw) == entry["size"] and
             entry["path"] == str(exe.with_suffix(suffix)), "wrong recorded sidecar bytes or output path")
        bodies.append(raw)
    if bodies[0] is None or bodies[1] is None:
        return "missing"
    known = subprocess.check_output(["b3sum"], input=bodies[0]).split()[0].decode()
    need(known == row["rlink_blake3"], "retained recipe checksum differs from physical capture")
    m = json.loads(bodies[1])
    data = m["executable"]
    valid = (bodies[0].startswith(b"rustlink") and m["version"] == 5 and
             m["rlink"] == {"path": str(exe.with_suffix(".rlink")), "blake3": row["rlink_blake3"]} and
             data["path"] == product and [data["len"], data["modified_nanos"]] == row["executable_stat"][2:] and
             row["object_dir"] == str(exe.with_suffix(".rlink-objects")) and bool(m["objects"]))
    expected = {i["path"]: i["blake3"] for i in m["objects"]}
    need(len(expected) == len(m["objects"]), "duplicate manifest object")
    current = {p: v[3] for p, v in row["object_files"].items()}
    valid = valid and all(current.get(path) == wanted for path, wanted in expected.items())
    return "matches-recorded-files" if valid else "differs-from-recorded-files"
