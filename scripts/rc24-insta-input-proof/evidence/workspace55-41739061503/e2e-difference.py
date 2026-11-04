"""Independently compare genuine stock-Wild e2e warm and empty binary generations."""

import argparse, hashlib, json, mmap, shutil, struct, subprocess, tempfile, zipfile
from pathlib import Path


def digest(x):
    return hashlib.sha256(x).hexdigest()


def image(mm):
    e = struct.unpack_from("<16sHHIQQQIHHHHHH", mm)
    assert e[0][:6] == b"\x7fELF\x02\x01" and e[2] == 62 and e[11] == 64 and e[9] == 56
    sh = [struct.unpack_from("<IIQQQQIIQQ", mm, e[6] + 64 * i) for i in range(e[12])]
    by = mm[sh[e[13]][4] : sh[e[13]][4] + sh[e[13]][5]]
    sections = {
        by[s[0] :].split(b"\0", 1)[0].decode(): (i, s) for i, s in enumerate(sh)
    }
    assert len(sections) == len(sh)
    _, note = sections[".note.gnu.build-id"]
    off = note[4]
    assert (
        struct.unpack_from("<III", mm, off) == (4, 32, 3)
        and mm[off + 12 : off + 16] == b"GNU\0"
        and note[5] == 48
    )
    ix, ro = sections[".rodata"]
    segments = []
    for i in range(e[10]):
        ph = struct.unpack_from("<IIQQQQQQ", mm, e[5] + 56 * i)
        if ph[0] == 1:
            segments.append((ph[2], ph[5]))
    return {
        "sections": sections,
        "rodata_field": e[6] + ix * 64 + 56,
        "rodata_entsize": ro[9],
        "note": (off, 48),
        "buildid": (off + 16, 32),
        "buildid_hex": mm[off + 16 : off + 48].hex(),
        "segments": segments,
    }


def normalized(mm, span, clear):
    begin, size = span
    end = begin + size
    lo, n = clear
    hi = lo + n
    h = hashlib.sha256()
    for i in range(begin, end, 1024 * 1024):
        nxt = min(i + 1024 * 1024, end)
        b = mm[i:nxt]
        if max(i, lo) < min(nxt, hi):
            c = bytearray(b)
            start = max(i, lo) - i
            stop = min(nxt, hi) - i
            c[start:stop] = bytes(stop - start)
            b = c
        h.update(b)
    return h.hexdigest()


def compare(old, new):
    with (
        old.open("rb") as x,
        new.open("rb") as y,
        mmap.mmap(x.fileno(), 0, access=mmap.ACCESS_READ) as a,
        mmap.mmap(y.fileno(), 0, access=mmap.ACCESS_READ) as b,
    ):
        ah, bh = image(a), image(b)
        assert len(a) == len(b)
        changed = 0
        classes = {}
        first = []
        for i in range(0, len(a), 65536):
            av, bv = a[i : i + 65536], b[i : i + 65536]
            if av == bv:
                continue
            for j, (v, w) in enumerate(zip(av, bv, strict=True)):
                if v == w:
                    continue
                at = i + j
                changed += 1
                off, n = ah["buildid"]
                if off <= at < off + n:
                    cls = "GNU build ID"
                elif ah["rodata_field"] <= at < ah["rodata_field"] + 8:
                    cls = ".rodata section header sh_entsize"
                else:
                    cls = "other"
                classes[cls] = classes.get(cls, 0) + 1
                if len(first) < 100:
                    first.append([at, v, w, cls])
        same_segments = ah["segments"] == bh["segments"]
        loaded = (
            [
                {
                    "offset": u,
                    "size": n,
                    "first": normalized(a, (u, n), ah["buildid"]),
                    "second": normalized(b, (u, n), bh["buildid"]),
                }
                for u, n in ah["segments"]
            ]
            if same_segments
            else []
        )
        assert changed > 0
        return {
            "old": digest(a),
            "new": digest(b),
            "size": len(a),
            "changed_bytes": changed,
            "classes": classes,
            "differences_first100": first,
            "rodata_sh_entsize": [ah["rodata_entsize"], bh["rodata_entsize"]],
            "rodata_field": [ah["rodata_field"], bh["rodata_field"]],
            "gnu_buildid": [ah["buildid_hex"], bh["buildid_hex"]],
            "buildid_range": [ah["buildid"], bh["buildid"]],
            "loadable": loaded,
            "all_loadable_equal_after_only_buildid": same_segments
            and all(x["first"] == x["second"] for x in loaded),
            "all_other_file_bytes_match": not classes.get("other")
            and sum(classes.values()) == changed,
        }


def run(path, raw_hash):
    with path.open("rb") as f:
        assert hashlib.file_digest(f, "sha256").hexdigest() == raw_hash
    with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory(dir=path.parent) as td:
        td = Path(td)
        proj = {}
        r = json.loads(z.read("result.json"))
        for role, res in sorted(r.items()):
            phases = res["natives"]
            base = phases["independent-empty"]
            wants = set(v for k, v in phases.items() if k != "old" and v != base)
            diff = {}
            for h in sorted(wants | {base}):
                f = td / h
                if f.exists():
                    continue
                with z.open(role + "/" + h + ".elf.zst") as c, f.open("wb") as out:
                    p = subprocess.Popen(
                        ["zstd", "-q", "-dc"], stdin=subprocess.PIPE, stdout=out
                    )
                    with p.stdin:
                        shutil.copyfileobj(c, p.stdin, 1024 * 1024)
                    assert p.wait() == 0
                with f.open("rb") as handle:
                    assert hashlib.file_digest(handle, "sha256").hexdigest() == h
            for h in sorted(wants):
                diff[h] = compare(td / h, td / base)
            proj[role] = {
                "original_qualified": res["e2e_exact"],
                "native_phase_sha256": phases,
                "vs_empty": diff,
                "true_full": res["full"],
                "link_only": res["link_only"],
                "stock_wild": res["wild"],
                "census_refusal": res["census_refusal"],
                "actual_product_counts": res["products"],
                "actual_unit_counts": res["units"],
            }
        return {"original_zip_sha256": raw_hash, "roles": proj}


if __name__ == "__main__":
    pa = argparse.ArgumentParser()
    pa.add_argument("zip", type=Path)
    pa.add_argument("sha")
    a = pa.parse_args()
    print(json.dumps(run(a.zip, a.sha), indent=2, sort_keys=True))
