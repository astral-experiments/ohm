"""Survey fixed-size content in the two largest complete semantic incremental sessions."""

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

from kits import need, write
from state import payload

BLOCK = 64 * 1024
FILES = ("dep-graph.bin", "query-cache.bin")


def overlap(left, right):
    def index(file):
        return Counter((size, h) for size, h in file["chunks"])

    result = {}
    for name in FILES:
        a, b = left["files"][name], right["files"][name]
        aa, bb = index(a), index(b)
        common = aa.keys() & bb.keys()
        result[name] = {
            "left_logical": a["size"],
            "right_logical": b["size"],
            "left_allocated": a["allocated"],
            "right_allocated": b["allocated"],
            "same_inode": a["inode"] == b["inode"],
            "left_unique_content_bytes": sum(n for n, h in aa),
            "right_unique_content_bytes": sum(n for n, h in bb),
            "common_unique_complete_block_bytes": sum(n for n, h in common if n == BLOCK),
            "common_unique_partial_block_bytes": sum(n for n, h in common if n != BLOCK),
            "common_bytes_including_multiplicity": sum(n * min(aa[n, h], bb[n, h]) for n, h in common),
        }
    return result


def capture(root, label):
    dest = root / "receipts/semantic-chunks"
    dest.mkdir(exist_ok=True)
    candidates = {}
    for base in [root / "slot/target", root / "slot/shared"]:
        for dep in base.rglob("dep-graph.bin"):
            directory = dep.parent
            query = directory / "query-cache.bin"
            if not (
                directory.name.startswith("s-")
                and not directory.name.endswith("-working")
                and directory.parent.name.startswith("ty_python_semantic-")
                and query.is_file()
            ):
                continue
            paths = [dep, query]
            stats = [p.stat() for p in paths]
            key = tuple((st.st_dev, st.st_ino) for st in stats)
            candidates.setdefault(key, (sum(st.st_size for st in stats), directory))
    selected = []
    for total, directory in sorted(candidates.values(), key=lambda x: (-x[0], str(x[1])))[:2]:
        files = {}
        for name in FILES:
            p = directory / name
            before = p.stat()
            parts = []
            h = hashlib.sha256()
            with p.open("rb") as f:
                for data in iter(lambda: f.read(BLOCK), b""):
                    h.update(data)
                    parts.append([len(data), hashlib.sha256(data).hexdigest()])
            after = p.stat()
            need(
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
                "incremental session changed during separate physical read",
            )
            files[name] = {
                "sha256": h.hexdigest(),
                "size": before.st_size,
                "allocated": before.st_blocks * 512,
                "inode": [before.st_dev, before.st_ino],
                "chunks": parts,
            }
        selected.append({"path": str(directory.relative_to(root / "slot")), "logical": total, "files": files})
    raw = {
        "observation": "physical replay only",
        "block": BLOCK,
        "eligible_sessions": len(candidates),
        "selected": selected,
    }
    payload(dest / (label + ".json.gz"), json.dumps(raw, separators=(",", ":")).encode())
    return raw


def summarize(directory):
    samples = {
        p.name.replace(".json.gz", ""): json.loads(gzip.decompress(p.read_bytes()))
        for p in sorted(directory.glob("*.json.gz"))
    }
    result = {"intra": {}, "across": {}}
    for label, s in samples.items():
        need(
            s["block"] == BLOCK and len(s["selected"]) == min(2, s["eligible_sessions"]),
            "wrong session coverage",
        )
        for session in s["selected"]:
            for file in session["files"].values():
                chunks = file["chunks"]
                need(
                    all(n == BLOCK for n, h in chunks[:-1])
                    and (not chunks or 0 < chunks[-1][0] <= BLOCK)
                    and sum(n for n, h in chunks) == file["size"],
                    "invalid last block or length",
                )
        result["intra"][label] = {
            "eligible_sessions": s["eligible_sessions"],
            "selected": [x["path"] for x in s["selected"]],
            "distinct_sessions": overlap(*s["selected"]) if len(s["selected"]) == 2 else None,
        }
    pre = samples["pre-install"]["selected"]
    for label, s in samples.items():
        if label != "pre-install":
            result["across"][label] = [
                {"before": i, "after": j, "content": overlap(a, b)}
                for i, a in enumerate(pre)
                for j, b in enumerate(s["selected"])
            ]
    return result
