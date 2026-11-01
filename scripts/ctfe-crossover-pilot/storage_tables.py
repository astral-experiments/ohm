"""Count complete raw/packed tables in the quiescent physical two-root inode ledger."""

from collections import defaultdict
from pathlib import PurePosixPath
import stat

KINDS = ("dep-graph.bin", "query-cache.bin")


def scan(ledger):
    paths = defaultdict(list)
    tables = {}
    sessions = {}
    seen = {}

    def need(x, why):
        if not x:
            raise ValueError(why)

    for name, row in ledger.items():
        p = PurePosixPath(name)
        dev, ino, links, mode, count, length = row
        key = (dev, ino)
        need(
            seen.setdefault(key, tuple(row)) == tuple(row) and p.parts[0] in ("target", "build"),
            "racing or foreign physical path",
        )
        if "incremental" not in p.parts:
            continue
        if stat.S_ISDIR(mode) and p.name.startswith("s-"):
            sessions[p.as_posix()] = {
                "id": [dev, ino],
                "working": p.name.endswith("-working"),
                "owner": p.parent.name,
            }
            continue
        kind = p.name.removeprefix("ohm-packed-").removeprefix("ohm-build-")
        if kind not in KINDS or not p.parent.name.startswith("s-"):
            continue
        need(stat.S_ISREG(mode), "nonregular original incremental table")
        data = [kind, p.name.startswith("ohm-packed-"), length, 512 * count]
        need(tables.setdefault(key, data) == data, "different table kinds share an inode")
        paths[key].append(p.as_posix())
    need(
        all(
            PurePosixPath(n).parent.as_posix() in sessions
            for group in paths.values()
            for n in group
        ),
        "table lacks an actual directory in the same ledger",
    )
    summary = {}
    for key, (kind, packed, size, allocation) in tables.items():
        names = {PurePosixPath(n).name for n in paths[key]}
        spelling = (
            "packed"
            if packed
            else (
                "raw+build-alias"
                if kind in names and "ohm-build-" + kind in names
                else "build-only" if "ohm-build-" + kind in names else "raw"
            )
        )
        label = spelling + "/" + kind
        v = summary.setdefault(label, dict(files=0, names=0, length=0, allocated=0))
        v["files"] += 1
        v["names"] += len(paths[key])
        v["length"] += size
        v["allocated"] += allocation
    return dict(
        total=sum(v[4] * 512 for v in seen.values()),
        inodes=len(seen),
        tables=summary,
        sessions=sessions,
        observed_table_names=sum(map(len, paths.values())),
        unique_physical_tables=len(tables),
    )
