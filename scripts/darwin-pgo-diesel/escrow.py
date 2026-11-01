"""Keep the original workspace, including hardlink relationships, before any replay."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tarfile

from identity import need, sha, write

GIB = 1 << 30
FLOOR = 4 * GIB
CAP = 2 * GIB


def free_guard(where, additional=0):
    need(shutil.disk_usage(where).free > FLOOR + additional, "bounded receipt space unavailable")


def facts(root, ceiling=CAP):
    """Walk without following symlinks and hash each distinct file inode once."""
    entries = {}
    content = {}
    size = 0
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            p = Path(base) / name
            s = p.lstat()
            m = stat.S_IMODE(s.st_mode)
            row = {
                "mode": m,
                "dev": s.st_dev,
                "ino": s.st_ino,
                "nlink": s.st_nlink,
                "mtime_ns": s.st_mtime_ns,
                "ctime_ns": s.st_ctime_ns,
            }
            if stat.S_ISREG(s.st_mode):
                key = (s.st_dev, s.st_ino)
                if key not in content:
                    size += s.st_size
                    need(size <= ceiling, "complete workspace exceeds its capture budget")
                    content[key] = sha(p)
                row.update(type="file", size=s.st_size, sha256=content[key])
            elif stat.S_ISDIR(s.st_mode):
                row.update(type="dir")
            elif stat.S_ISLNK(s.st_mode):
                row.update(type="symlink", target=os.readlink(p))
            else:
                raise ValueError(f"unsupported special file in collector workspace: {p}")
            after = p.lstat()
            need(
                (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                "file changed while hashing",
            )
            entries[str(p.relative_to(root))] = row
    return entries, size


def pack(root, dest, cap=CAP):
    original, size = facts(root, cap)
    free_guard(dest.parent, size + (16 << 20))
    write(dest.with_suffix(".inventory.json"), {"root": str(root), "unique_bytes": size, "entries": original})
    with tarfile.open(dest, "x:gz", compresslevel=1, dereference=False) as t:
        for path in sorted(original):
            t.add(root / path, arcname=path, recursive=False)
    with tarfile.open(dest, "r:gz") as t:
        seen = set()
        for m in t:
            need(m.name in original and m.name not in seen, "unknown/duplicate archive path")
            seen.add(m.name)
            v = original[m.name]
            if v["type"] == "file":
                need(m.isreg() or m.islnk(), "wrong saved file type")
                if m.islnk():
                    target = original[m.linkname]
                    need((v["dev"], v["ino"]) == (target["dev"], target["ino"]), "false hardlink in archive")
                else:
                    with t.extractfile(m) as stream:
                        need(
                            m.size == v["size"]
                            and hashlib.file_digest(stream, "sha256").hexdigest() == v["sha256"],
                            "saved member bytes differ",
                        )
            elif v["type"] == "symlink":
                need(m.issym() and m.linkname == v["target"], "symlink changed")
            else:
                need(m.isdir(), "lost directory")
            need(m.mode == v["mode"], "lost file permissions")
        need(seen == set(original), "incomplete workspace archive")
    now, _ = facts(root, cap)
    need(original == now, "source changed before completed archive comparison")
    return {"size": dest.stat().st_size, "sha256": sha(dest), "raw_unique_bytes": size, "paths": len(original)}


def keep_graphs(cwd, dest):
    root = cwd / "incremental-state"
    paths = sorted(
        p
        for p in root.glob("diesel-*/s-*/*")
        if p.name in ("dep-graph.bin", "dep-graph.part.bin", "ohm-packed-dep-graph.bin", "query-cache.bin")
    )
    dest.mkdir()
    rows = []
    for p in paths:
        s = p.lstat()
        need(stat.S_ISREG(s.st_mode) and s.st_size <= 512 << 20, "invalid graph or query-cache file")
        h = sha(p)
        copy = p.name != "query-cache.bin"
        if copy:
            q = dest / h
            if not q.exists():
                free_guard(dest, s.st_size)
                shutil.copyfile(p, q)
            need(sha(q) == h, "graph escrow differs")
        with p.open("rb") as fp:
            header = fp.read(64).hex()
        s2 = p.lstat()
        need(
            (s.st_dev, s.st_ino, s.st_mtime_ns, s.st_ctime_ns, s.st_size)
            == (s2.st_dev, s2.st_ino, s2.st_mtime_ns, s2.st_ctime_ns, s2.st_size),
            "graph changed",
        )
        rows.append(
            {
                "path": str(p.relative_to(cwd)),
                "bytes": s.st_size,
                "dev": s.st_dev,
                "ino": s.st_ino,
                "nlink": s.st_nlink,
                "mtime_ns": s.st_mtime_ns,
                "ctime_ns": s.st_ctime_ns,
                "mode": s.st_mode,
                "sha256": h,
                "prefix": header,
                "raw_separate": copy,
            }
        )
    write(dest / "physical.json", rows)
    return rows


def safe_for_clone(root):
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            p = Path(base) / name
            if p.is_symlink():
                need(
                    not os.path.isabs(os.readlink(p)) and p.resolve().is_relative_to(root.resolve()),
                    "replay would follow an external link",
                )
