"""Reconcile actual inode observations, provider reads, published sessions and materialized native products."""

import re
import stat
from pathlib import Path

from evidence import FILES, RAWS, need


def row_matches(row, identity):
    return (
        stat.S_ISREG(row[3])
        and (row[0], row[1], row[2], row[4] * 512, row[5])
        == tuple(identity[k] for k in ("dev", "ino", "links", "blocks", "bytes"))
        and re.fullmatch(r"[a-f0-9]{64}", identity["sha256"])
    )


def completed(ledger):
    return {
        s
        for s, r in ledger.items()
        if stat.S_ISDIR(r[3])
        and "incremental" in Path(s).parts
        and re.fullmatch(r"s-[a-z0-9]+-_[a-f0-9]{16}_[a-z0-9]+-[a-z0-9]+", Path(s).name)
        and not s.endswith("-working")
    }


def snapshot(q, ledger, work):
    captured = set()
    for owner, d in q["owners"].items():
        parent = Path(d)
        need(parent.name == owner and parent.is_relative_to(work), "unsafe selected session root")
        rel = parent.relative_to(work)
        scanned = {n for n in completed(ledger) if Path(n).parent == rel}
        expected = {str(rel / n) for n in q["sessions"][owner]}
        need(scanned == expected, ("missing finalized directory", owner))
        for n, tables in q["sessions"][owner].items():
            for name, rec in tables.items():
                path = str(rel / n / name)
                need(
                    name in (*FILES, *RAWS) and row_matches(ledger[path], rec), "different captured table inode"
                )
        captured |= expected
    return captured


def publication(prior, current, before, after, placements, link, whole, work):
    snapshot(before, prior, work)
    snapshot(after, current, work)
    expected = set()
    for owner, v in placements.items():
        owner_rel = Path(before["owners"][owner]).relative_to(work)
        d = owner_rel / v["final"]
        expected.add(str(d))
        fs = dict()
        for k, record in v["objects"].items():
            name = record["file"]
            p = str(d / name)
            need(
                row_matches(current[p], record["stat"]) and re.fullmatch(r"[0-9a-f]{64}", record["digest"]),
                "native object evidence",
            )
            if record["packed"]:
                need(
                    name == "ohm-packed-object-" + k + "-" + record["blake3"]
                    and re.fullmatch(r"blake3=[0-9a-f]{64}", record["blake3"])
                    and record["bytes"] >= 4097
                    and record["stat"]["bytes"] == record["stored"],
                    "packed object namespace",
                )
            else:
                need(
                    name == k
                    and record["stat"]["bytes"] == record["bytes"]
                    and record["stat"]["sha256"] == record["digest"],
                    "wrong raw native SHA",
                )
            fs[name] = record["stat"]["ino"]
        actual = {
            Path(k).name
            for k, vv in current.items()
            if Path(k).parent == d
            and (Path(k).name.endswith(".o") or Path(k).name.startswith("ohm-packed-object-"))
        }
        need(actual == set(fs), "missing object entries")
        for i, record in enumerate(v["tables"]):
            n = FILES[i] if v["packed_pair"] else RAWS[i]
            key = "packed" if v["packed_pair"] else "raw"
            need(
                row_matches(current[str(d / n)], record[key])
                and re.fullmatch(r"[a-f0-9]{64}", record["body_sha256"])
                and record[key] == after["sessions"][owner][v["final"]][n],
                "different physical published table",
            )
            if not v["packed_pair"]:
                need(
                    current[str(d / ("ohm-build-" + n))] == current[str(d / n)]
                    and record["body_sha256"] == record["raw"]["sha256"]
                    and record["body_bytes"] == record["raw"]["bytes"],
                    "lost alias/contents of raw stream",
                )
    need(completed(current) - completed(prior) == expected, "additional/missing finalized owner")
    a = Path(link["wild_output"]).relative_to(work)
    b = Path(link["cargo"]).relative_to(work)
    need(
        b == Path("target/debug/ruff")
        and a.parts[0] in ("target", "build")
        and current[str(a)] == current[str(b)]
        and row_matches(current[str(a)], link["file"])
        and link["file"] == link["returned"]
        and whole == link["file"]["sha256"],
        "Wild output does not own Cargo's complete ELF",
    )
