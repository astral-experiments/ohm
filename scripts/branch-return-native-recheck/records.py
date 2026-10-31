"""Read strict Cargo 761ea115's exact versioned dep-info, preserving original evidence."""

import collections
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess

MARK = "/dev/null/ohm-recheck-dependent-links"


def need(ok, why):
    if not ok:
        raise ValueError(str(why))


def save(path, obj):
    with path.open("x") as stream:
        json.dump(obj, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")


def file_id(path):
    s = path.stat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def b3(raw):
    out = subprocess.check_output(["b3sum", "--no-names"], input=raw)
    return bytes.fromhex(out.decode().strip())


def translated(raw, digest=b3):
    off = 0

    def take(n):
        nonlocal off
        need(0 <= n <= len(raw) - off, "truncated dep-info")
        off += n
        return raw[off - n : off]

    def uint():
        return int.from_bytes(take(4), "little")

    def string():
        return os.fsdecode(take(uint()))

    need(take(5) == b"\x01\0\0\0\xff", "dep-info magic")
    version = take(1)[0]
    need(version in (2, 4), ("dep-info version", version))
    files = []
    for _ in range(uint()):
        kind, path, checked = take(1)[0], string(), take(1)[0]
        need(kind in (0, 1) and checked in (0, 1), "file record")
        if checked:
            take(8)
            string()
        files.append((kind, path, checked))
    for _ in range(uint()):
        string()
        present = take(1)[0]
        need(present in (0, 1), "env record")
        if present:
            string()
    link = None
    if raw[off : off + 4] == b"LNK1":
        take(4)
        link = uint()
        need(link < len(files) and files[link] == (1, MARK, 0), "LNK1 index/path")
        signed = raw[:off]
        need(take(32) == digest(signed), "LNK1 BLAKE3")
    if off == len(raw) and version == 2:
        need(not any(checked for _, _, checked in files), "legacy checksum has no observer trailer")
    if off < len(raw):
        need(take(4) == b"OBS1", "unidentified trailer")
        item = uint()
        tag = take(1)[0]
        need(
            item < len(files)
            and tag in (0, 1)
            and Path(files[item][1]).name == "ohm-foreign-span-bytes"
            and not files[item][2],
            "OBS1 record",
        )
        signed = raw[:off]
        need(take(32) == digest(signed), "OBS1 BLAKE3")
    need(off == len(raw), "unparsed trailer")
    return {"version": version, "files": len(files), "link_index": link}


def paths_from_root(native):
    items = {}
    for row in native["rustcs"]:
        argv = row["argv"]
        if "--out-dir" not in argv or "--crate-type" not in argv or row["mode"] != "full":
            continue
        output = argv[argv.index("--out-dir") + 1]
        item = row["crate"], argv[argv.index("--crate-type") + 1]
        deps = {
            str(Path(arg.split("=", 1)[1]).parent)
            for prev, arg in zip(argv, argv[1:])
            if prev == "--extern" and "=" in arg
        }
        if output in items:
            need(items[output] == (item, deps), ("ambiguous native out-dir", output))
        items[output] = item, deps
    roots = [k for k, (item, _) in items.items() if item == ("ruff", "bin")]
    need(len(roots) == 1, ("full Ruff root", roots))
    q = collections.deque([(roots[0], [])])
    paths = {}
    while q:
        key, prior = q.popleft()
        if key in paths:
            continue
        name, deps = items[key]
        paths[key] = prior + [dict(unit=key, name=name[0], kind=name[1])]
        q.extend((d, paths[key]) for d in sorted(deps & items.keys()))
    return paths


def collect(roots, native, out):
    # Read each real encoded record and its upstream raw .d, before the first repeat.
    paths = paths_from_root(native)
    out.mkdir()
    store = out / "objects"
    store.mkdir()

    def retain(data):
        h = hashlib.sha256(data).hexdigest()
        p = store / (h + ".gz")
        if not p.exists():
            with p.open("xb") as f:
                f.write(gzip.compress(data, compresslevel=5, mtime=0))
        return h

    found = {}
    census = {}
    originals = {}
    for root in roots:
        for p in sorted(root.rglob("dep-*")):
            if p.parent.name != "fingerprint" or not p.is_file():
                continue
            need(not p.is_symlink() and p.resolve() == p, ("unexpected translated path alias", p))
            data = p.read_bytes()
            info = translated(data)
            census[str(p)] = dict(**info, identity=file_id(p), sha256=retain(data))
            unit = p.parent.parent / "out"
            raw = []
            for d in sorted(unit.glob("*.d")):
                need(not d.is_symlink() and d.resolve() == d, ("unexpected raw path alias", d))
                b = d.read_bytes()
                originals[str(d)] = dict(identity=file_id(d), sha256=retain(b))
                if info["link_index"] is None or MARK.encode() not in b:
                    continue
                rules = [s.split(": ", 1) for s in b.decode().splitlines() if ": " in s]
                own = [rhs for lhs, rhs in rules if lhs == str(d) or Path(lhs).name == d.name]
                marked = [rhs for _, rhs in rules if rhs.endswith(" " + MARK)]
                need(
                    len(own) == 1
                    and marked
                    and all(rhs == own[0] + " " + MARK for rhs in marked)
                    and MARK not in own[0].split(" "),
                    ("raw rustc marker", d),
                )
                need(MARK + ":" in b.decode().splitlines(), ("raw rustc target", d))
                raw.append(dict(path=str(d), **originals[str(d)]))
            if info["link_index"] is None:
                continue
            need(raw, ("translated LNK1 without matching rustc rules", p))
            found[str(p)] = dict(raw=raw, chain=paths.get(str(unit)), **census[str(p)])
    need(
        found and any(v["chain"] for v in found.values()),
        "no genuine native extern path to a marked producer",
    )
    save(out / "census.json", census)
    save(out / "rustc-dep-info.json", originals)
    save(out / "origins.json", found)
    return found


def unchanged(origins):
    # A fresh producer should not be rewritten by Cargo's final executable recheck.
    result = {}
    for name, value in origins.items():
        records = [dict(path=name, **value), *value["raw"]]
        for row in records:
            p = Path(row["path"])
            same_bytes = hashlib.sha256(p.read_bytes()).hexdigest() == row["sha256"]
            same_identity = file_id(p) == row["identity"]
            result[str(p)] = {"same_bytes": same_bytes, "same_identity": same_identity}
            need(
                same_bytes and (same_identity or p.name.startswith("dep-bin-")),
                ("marked producer changed on final native recheck", p, same_bytes, same_identity),
            )
    return result
