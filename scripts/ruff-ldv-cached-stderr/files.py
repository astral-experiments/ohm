"""Reversibly switch only genuine Cargo message cache files observed on this private study."""
from collections import Counter
import hashlib
import os
from pathlib import Path
import re
import stat


def need(ok, why):
    if not ok:
        raise ValueError(str(why))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def signature(path):
    s = path.lstat()
    need(stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and s.st_uid == os.getuid(),
         ("private regular message file required", str(path), s.st_nlink))
    return [s.st_dev, s.st_ino, s.st_mtime_ns, s.st_atime_ns, s.st_mode, s.st_size, s.st_nlink]


def files_read(path, work):
    result = Counter()
    for line in path.read_text().splitlines():
        got = re.search(r"= [0-9]+<(/[^>]+)>$", line)
        if not got or "O_RDONLY" not in line:
            continue
        file = Path(got[1])
        if not file.name.startswith("output-") or not file.is_relative_to(work):
            continue
        rel = file.relative_to(work)
        need(rel.parts[0] in ("target", "build") and file.resolve(strict=True) == file,
             ("escaped message file", str(file)))
        result[str(rel)] += 1
    need(result, "no successful reads of Cargo output-* files")
    return result


def capture(trace, work, destination, stderr, role):
    destination.mkdir()
    observed = {}
    n_markers = Counter()
    for name, opens in sorted(files_read(trace, work).items()):
        path = work / name
        sig = signature(path)
        data = path.read_bytes()
        if b"OHM_LDV_" not in data:
            continue
        need(len(data) < 2**20 and opens == 1, ("unbounded or multiply read cache entry", name, opens))
        # Permit ordinary compiler JSON only when the other independently trained
        # history retains those lines exactly. We never manufacture or edit any line.
        nonprobe = bytearray()
        for line in data.splitlines(keepends=True):
            tokens = re.sub(rb"OHM_LDV_GUARD|OHM_LDV_REASONS|original|guard|[0-9]+|[ \t\r\n]", b"", line)
            if tokens:
                need(b"OHM_LDV_" not in line, ("mixed diagnostic and other compiler bytes", name, line[:80]))
                nonprobe.extend(line)
        need(data.count(b"OHM_LDV_GUARD") > 0 and
             (b"OHM_LDV_GUARD original" not in data if role == "guard" else
              b"OHM_LDV_GUARD guard" not in data and b"OHM_LDV_REASONS" not in data),
             ("wrong independently trained message set", name))
        for marker in (b"OHM_LDV_GUARD", b"OHM_LDV_REASONS"):
            n_markers[marker] += data.count(marker)
        key = digest(data)
        output = destination / key
        if not output.exists():
            output.write_bytes(data)
        need(output.read_bytes() == data, "changed authentic diagnostic bytes")
        observed[name] = {"sha": key, "bytes": len(data), "stat": sig, "opens": opens, "nonprobe": digest(nonprobe)}
    need(observed and all(n_markers[k] == stderr.count(k) for k in (b"OHM_LDV_GUARD", b"OHM_LDV_REASONS")),
         ("not all actually replayed compiler text is accounted", n_markers))
    return observed


def switch(work, spec, bodies, stable, expected):
    need(set(spec) == set(stable) == set(expected), "different file set")
    for name, row in sorted(spec.items()):
        f = work / name
        now = signature(f)
        baseline = stable[name]["stat"]
        need(now[:3] == baseline[:3] and now[4] == baseline[4] and f.resolve(strict=True) == f
             and digest(f.read_bytes()) == expected[name]["sha"], ("changed active private file", name))
        incoming = (bodies / row["sha"]).read_bytes()
        need(len(incoming) == row["bytes"] and digest(incoming) == row["sha"], "different stored source")
        fd = os.open(f, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "r+b", buffering=0) as dst:
            tmp = os.fstat(dst.fileno())
            need((tmp.st_dev, tmp.st_ino, tmp.st_nlink) == (now[0], now[1], 1), "message object was replaced")
            dst.seek(0)
            dst.write(incoming)
            dst.truncate()
            os.fsync(dst.fileno())
            os.utime(dst.fileno(), ns=(baseline[3], baseline[2]))
        need(signature(f)[:3] == baseline[:3] and digest(f.read_bytes()) == row["sha"], "failed switch readback")
