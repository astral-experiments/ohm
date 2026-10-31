"""Hash actual table bodies off-clock, resolving logical sessions and physical allocation separately."""

from collections import Counter, defaultdict
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import zlib

HERE = Path(__file__).resolve().parent
LIMIT, MIN = 512 << 20, 64 << 10
BLOCK = 256 << 10
KINDS = {"G": "dep-graph", "Q": "query-cache"}
TAG = re.compile(r"s-[a-z0-9]+-_([0-9a-f]{16})_[a-z0-9]+-[a-z0-9]+")
PLAIN = re.compile(r"s-[a-z0-9]+-[a-z0-9]+-[a-z0-9]+")
ROSTER = json.loads((HERE / "inputs/cold-units.json").read_bytes())


def need(b, message):
    if not b:
        raise ValueError(message)


def geometry(s):
    return [s.st_dev, s.st_ino, s.st_nlink, s.st_mode, s.st_blocks, s.st_size]


def read_ledger(folder):
    with gzip.open(folder / "path-inodes.json.gz", "rt") as f:
        return json.load(f)


def units(ledger):
    rows = defaultdict(list)
    for name in ledger:
        p = PurePosixPath(name)
        if p.name == "work-products.bin" and "incremental" in p.parts:
            need(
                TAG.fullmatch(p.parent.name) or PLAIN.fullmatch(p.parent.name),
                ("invalid completed session name", name),
            )
            rows[str(p.parent.parent)].append(str(p.parent))
    expected = Counter(PurePosixPath(n).name.rsplit("-", 1)[0] for n in rows)
    need(
        expected == ROSTER["cold_roster"] and all(1 <= len(v) <= 2 for v in rows.values()),
        ("incomplete or ambiguous 38-unit work-product inventory", expected),
    )
    return dict(rows)


def mount(fd):
    vals = [
        ln.split()[1]
        for ln in Path(f"/proc/self/fdinfo/{fd}").read_text().splitlines()
        if ln.startswith("mnt_id:")
    ]
    need(len(vals) == 1 and vals[0].isdigit(), "missing actual file mount id")
    return int(vals[0])


def digest_body(stream, kind, producer, packed):
    stored = hashlib.sha256()
    body = hashlib.sha256()
    magic = bytearray()
    head = bytearray()
    need_head = 11 + len(producer) + 1
    dec = zlib.decompressobj() if packed else None
    size = total = disk_bytes = 0
    alias_mask = None

    def consume(data):
        nonlocal size, total, alias_mask
        if packed and len(head) < need_head:
            n = min(need_head - len(head), len(data))
            head.extend(data[:n])
            data = data[n:]
            if len(head) == need_head:
                size = int.from_bytes(head[3:11], "little")
                alias_mask = head[2]
                need(
                    head[:2] == bytes((1, ord(kind)))
                    and alias_mask in (1, 3, 5, 7)
                    and head[11:] == producer.encode() + b"\0"
                    and MIN <= size <= LIMIT,
                    "bad native table prefix",
                )
        if data:
            total += len(data)
            need(total <= (size if packed else LIMIT), "overlong decoded table")
            magic.extend(data[: 4 - len(magic)])
            body.update(data)

    while data := stream.read(BLOCK):
        stored.update(data)
        disk_bytes += len(data)
        need(disk_bytes <= LIMIT, "overlong stored table")
        if dec is None:
            consume(data)
        else:
            while data:
                out = dec.decompress(data, BLOCK)
                consume(out)
                need(not dec.unused_data, "trailing compressed member")
                data = dec.unconsumed_tail
    if packed:
        consume(dec.flush())
        need(
            dec.eof and not dec.unused_data and not dec.unconsumed_tail and size == total,
            "incomplete stream",
        )
    need(magic == b"RSIC", "not a rustc incremental table")
    return {
        "raw_bytes": total,
        "raw_sha256": body.hexdigest(),
        "stored_bytes": disk_bytes,
        "stored_sha256": stored.hexdigest(),
        "alias_mask": alias_mask,
    }


def scan(root, folder, *, cold=False, arm):
    ledger = read_ledger(folder)
    current = units(ledger)
    all_aliases = defaultdict(set)
    for name, row in ledger.items():
        if stat.S_ISREG(row[3]):
            all_aliases[tuple(row[:2])].add(name)
    by_unit = {}
    for unit, sessions in sorted(current.items()):
        need(not cold or len(sessions) == 1, "cold root retained an alternate")
        for session in sessions:
            p = PurePosixPath(session)
            tag = TAG.fullmatch(p.name)
            need(bool(tag) == arm.endswith("on"), ("wrong actual session header", arm, session))
            producer = p.name.rsplit("-", 1)[0]
            streams = {}
            for k, basename in KINDS.items():
                aliases = [
                    str(p / (prefix + basename + ".bin"))
                    for prefix in ("", "ohm-build-", "ohm-check-")
                ]
                compact = str(p / ("ohm-packed-" + basename + ".bin"))
                packed = compact in ledger
                name = compact if packed else aliases[0]
                need(
                    name in ledger and (not packed or not set(aliases).intersection(ledger)),
                    ("missing/hybrid table", unit, session, k),
                )
                shape = ledger[name]
                need(
                    stat.S_ISREG(shape[3]) and not (root / name).is_symlink() and shape[5] > 0,
                    ("nonregular table", name),
                )
                fd = os.open(root / name, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, "rb") as f:
                    need(
                        geometry(os.fstat(fd)) == shape
                        and geometry((root / name).lstat()) == shape,
                        "table moved before read",
                    )
                    s = digest_body(f, k, producer, packed)
                    s["mount_id"] = mount(fd)
                    need(
                        s["stored_bytes"] == shape[5]
                        and geometry(os.fstat(fd)) == shape
                        and geometry((root / name).lstat()) == shape,
                        ("table changed under observer", name),
                    )
                actual = all_aliases[tuple(shape[:2])]
                need(
                    len(actual) <= shape[2] and name in actual, ("missing observed hardlink", name)
                )
                local_mask = sum(1 << i for i, a in enumerate(aliases) if a in actual)
                if packed:
                    need(
                        shape[2] == 1 and actual == {name},
                        ("published packed table is externally aliased", name),
                    )
                else:
                    need(local_mask in (1, 3, 5, 7), ("raw base missing", name))
                    s["alias_mask"] = local_mask
                streams[k] = {
                    **s,
                    "path": name,
                    "stat": shape,
                    "all_visible_aliases": sorted(actual),
                    "unlisted_links": shape[2] - len(actual),
                    "unowned_links": shape[2] - (1 if packed else local_mask.bit_count()),
                    "mode": "packed" if packed else "raw",
                    "allocated": shape[4] * 512,
                }
            need(
                streams["G"]["mode"] == streams["Q"]["mode"],
                ("mixed packed/raw table pair", session),
            )
            if cold and arm != "Eon":
                need(
                    streams["G"]["mode"] == "raw",
                    "unexpected first-checkout packing in original/off role",
                )
            classifier = (
                "native-packed"
                if streams["G"]["mode"] == "packed"
                else (
                    "outside-codec-size"
                    if any(not MIN <= s["raw_bytes"] <= LIMIT for s in streams.values())
                    else (
                        "additional-hardlink"
                        if any(s["unowned_links"] for s in streams.values())
                        else "raw-in-size-range"
                    )
                )
            )
            by_unit.setdefault(unit, {})[session] = {
                "tag": tag[1] if tag else None,
                "classification": classifier,
                "streams": streams,
            }
    out = {"unit_count": len(by_unit), "sessions": by_unit, "cold": cold, "arm": arm}
    with gzip.GzipFile(
        filename=str(folder / "table-bodies.json.gz"), mode="xb", compresslevel=3, mtime=0
    ) as f:
        f.write((json.dumps(out, sort_keys=True, separators=(",", ":")) + "\n").encode())
    return out


def relate(previous, now, phase):
    before, after = previous["sessions"], now["sessions"]
    need(set(before) == set(after), "logical unit changed across history")
    rows = {}
    for unit in before:
        retained = set(before[unit]) & set(after[unit])
        for s in retained:
            a, b = before[unit][s], after[unit][s]
            need(a["tag"] == b["tag"], ("relabelled finalized session", s))
            for k in KINDS:
                left, right = a["streams"][k], b["streams"][k]
                need(
                    all(
                        left[x] == right[x]
                        for x in (
                            "mode",
                            "path",
                            "stored_sha256",
                            "raw_sha256",
                            "allocated",
                            "mount_id",
                        )
                    )
                    and left["stat"][:2] == right["stat"][:2],
                    ("finalized table moved or changed", s, k),
                )
        rows[unit] = {
            "retained": sorted(retained),
            "replaced": sorted(set(before[unit]) - retained),
            "new": sorted(set(after[unit]) - retained),
        }
    if phase == "first-B" and now["arm"].endswith("on"):
        switched = [u for u, r in rows.items() if r["new"]]
        need(
            Counter(PurePosixPath(u).name.rsplit("-", 1)[0] for u in switched)
            == ROSTER["original_displaced"]
            and all(len(rows[u]["retained"]) == 1 and len(rows[u]["new"]) == 1 for u in switched),
            "not the 20 genuine original checkout switches",
        )
    if phase == "same-repeat":
        need(
            all(not r["new"] and not r["replaced"] for r in rows.values()),
            "repeat rewrote incremental sessions",
        )
    if phase == "same-edit" and now["arm"].endswith("on"):
        changed = [u for u, r in rows.items() if r["new"]]
        need(
            any(PurePosixPath(u).name.startswith("ruff_python_parser-") for u in changed),
            "parser did not publish new code on its own branch",
        )
        for u in changed:
            old_tags = {b["tag"] for b in before[u].values()}
            for session in rows[u]["new"]:
                new = after[u][session]
                need(
                    new["tag"] in old_tags and new["streams"]["G"]["mode"] == "raw",
                    ("same-branch edit took a different checkout or packed a new session", u),
                )
    return rows
