"""Classify every debug RELA of ELF objects that released Wild selected on a real Ruff link."""

import argparse, collections, hashlib, json, mmap, struct
from pathlib import Path


def selected(data):
    i = 0

    def n():
        nonlocal i
        val = shift = 0
        while True:
            u = data[i]
            i += 1
            val += (u & 127) << shift
            if u < 128:
                return val
            shift += 7
            assert shift < 70

    def buf():
        nonlocal i
        length = n()
        v = data[i : i + length]
        i += length
        return bytes(v)

    for _ in range(n()):
        name = Path(buf().decode())
        s = e = None
        member = None
        if n():
            s = n()
            e = n()
            member = buf().decode(errors="replace")
        kept = 0
        for _ in range(n()):
            if n():
                start = n()
                end = n()
                assert end >= start
                kept += 1
        temp = n()
        assert temp in [0, 1]
        yield name, s, e, member, kept
    assert n() == 0 and i == len(data), (i, len(data))


def objects(files):
    for name, entries in files.items():
        with (
            name.open("rb") as f,
            mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as file,
        ):
            for s, e, _m, k in entries:
                raw = file[s:e] if s is not None else file[:]
                if (
                    raw[:6] != b"\x7fELF\x02\x01"
                    or struct.unpack_from("<H", raw, 16)[0] != 1
                ):
                    continue
                yield raw, s is not None, k


def category(name):
    if name.startswith(".text"):
        return "code"
    if name.startswith((".data", ".bss", ".rodata", ".tdata")):
        return "other-alloc"
    if name.startswith(".debug"):
        return name
    return "other"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("layout", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    files = collections.defaultdict(list)
    for name, s, e, m, k in selected(a.layout.read_bytes()):
        files[name].append((s, e, m, k))
    totals = collections.defaultdict(collections.Counter)
    by_output = collections.Counter()
    groups = collections.Counter()
    archive_digests = {}
    for name, entries in files.items():
        if any(s is not None for s, e, m, k in entries):
            with name.open("rb") as stream:
                archive_digests[str(name)] = hashlib.file_digest(
                    stream, "sha256"
                ).hexdigest()
    for raw, archive, kept in objects(files):
        which = "archive" if archive else "loose"
        t = totals[which]
        t["objects"] += 1
        t["with_alloc_sections"] += bool(kept)
        t["object_bytes"] += len(raw)
        (off,) = struct.unpack_from("<Q", raw, 40)
        sz, n, ss = struct.unpack_from("<HHH", raw, 58)
        assert sz == 64 and n > 0
        h = [struct.unpack_from("<IIQQQQIIQQ", raw, off + i * sz) for i in range(n)]
        str_off = h[ss][4]
        names = [
            raw[str_off + r[0] : raw.index(b"\0", str_off + r[0])].decode(
                errors="replace"
            )
            for r in h
        ]
        targets = [category(z) for z in names]
        syms = {}
        allkeys = collections.defaultdict(set)
        local_symbols = {}
        for r in h:
            if r[1] != 4:
                continue
            source = names[r[7]]
            cnt = r[5] // 24
            t["all_rela"] += cnt
            if not source.startswith(".debug"):
                continue
            t["debug_rela"] += cnt
            by_output[source] += cnt
            if r[6] not in syms:
                st = h[r[6]]
                entries = list(
                    struct.iter_unpack("<IBBHQQ", raw[st[4] : st[4] + st[5]])
                )
                syms[r[6]] = [q[3] for q in entries]
                local_symbols[r[6]] = [
                    q[1] == 3 and q[4] == 0 and 0 < q[3] < len(h) for q in entries
                ]
            target_symbols = syms[r[6]]
            keys = set()
            prev = prevsym = None
            previous = None
            for off, ri, add in struct.iter_unpack("<QQq", raw[r[4] : r[4] + r[5]]):
                if (
                    source in (".debug_ranges", ".debug_loc")
                    and ri & 0xFFFFFFFF == 1
                    and local_symbols[r[6]][ri >> 32]
                ):
                    if previous and previous[0] + 8 == off and previous[1] == ri:
                        t["eligible paired entries " + source] += 2
                        previous = None
                    else:
                        previous = (off, ri)
                else:
                    previous = None
                sym = ri >> 32
                sec = target_symbols[sym]
                cat = targets[sec] if 0 < sec < len(h) else "non-section"
                groups[cat] += 1
                key = (ri, add)
                t["same_preceding_symbol"] += sym == prevsym
                t["same_preceding_key"] += key == prev
                keys.add(key)
                prev = key
                prevsym = sym
                if cat == ".debug_str":
                    t["debug_str_rela"] += 1
                if targets[r[7]] == ".debug_info" and cat == ".debug_str":
                    t["info_to_str"] += 1
                if cat == ".debug_str":
                    allkeys["debug_str"].add(key)
                allkeys["any"].add(key)
            t["unique_keys_per_section"] += len(keys)
        t["unique_keys_per_object"] += len(allkeys["any"])
        t["unique_str_keys_per_object"] += len(allkeys["debug_str"])
    result = {
        "layout_sha256": hashlib.sha256(a.layout.read_bytes()).hexdigest(),
        "selected_archive_sha256": archive_digests,
        "by_input": totals,
        "by_output_section": by_output,
        "by_target_class": groups,
    }
    a.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    result.pop("selected_archive_sha256")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
