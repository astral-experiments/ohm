"""Reopen the compressed raw streams, typed units, elapsed clocks and independent native reader subjects."""

import argparse
import gzip
import json
from pathlib import Path

from calibrate import fields
from cohort import summarize
from measure import typed
from study import ORDERS, digest, load, need, sha


def as_json(value):
    return json.loads(json.dumps(value))


def verify(root):
    n = 0
    for f in root.rglob("terminal.json"):
        terminal = load(f)
        if "phase_sha256" not in terminal:
            continue
        for phase, expected in terminal["phase_sha256"].items():
            d = f.parent / phase
            need(sha(d / "verified.json") == expected, "phase receipt changed")
            row = load(d / "verified.json")
            stats = row["cargo"]
            sums = stats["streams"]
            raw = gzip.decompress((d / "stdout.gz").read_bytes())
            need(
                digest(raw) == sums["stdout"]
                and digest(gzip.decompress((d / "stderr.gz").read_bytes())) == sums["stderr"],
                "Cargo streams changed",
            )
            arts, dirty, codes, roster = typed(raw, row["success"])
            need(
                as_json(dirty) == row["dirty"] and as_json(roster) == row["roster"] and codes == row["codes"],
                "typed projection changed",
            )
            need(
                digest(gzip.decompress((d / "zmij.dep.gz").read_bytes())) == row["marker"]["sha256"],
                "wrong compiler dep-info",
            )
            for holder in [d] + ([d / "reader/link"] if row["reader"] else []):
                checks = sums if holder == d else row["reader"]["streams"]
                for name, file in (
                    ("stdout", "stdout.gz"),
                    ("stderr", "stderr.gz"),
                    ("native_events", "exec.json.gz"),
                ):
                    if name in checks:
                        need(
                            digest(gzip.decompress((holder / file).read_bytes())) == checks[name],
                            "changed process evidence",
                        )
            if "ns" in stats:
                need(stats["ns"] == stats["stop_ns"] - stats["start_ns"] > 0, "wrong blocking elapsed")
                measured = fields((d / "time.txt").read_text())
                need(all(stats[k] == v for k, v in measured.items()), "Darwin counter differs")
            n += 1
    need(n, "no independently closed Cargo installations")
    for p in (root / "clean-readers").glob("*.macho.gz"):
        data = gzip.decompress(p.read_bytes())
        need(
            digest(data) == p.name.split(".")[0] and data[:8] == bytes.fromhex("cffaedfe0c000001"),
            "wrong cold reader",
        )
    for mode, order in ORDERS.items():
        d = root / mode
        if not (d / "result.json").is_file():
            continue
        pairs = []
        for i in range(1, len(order) + 1):
            pairs.append(
                {
                    r: {
                        phase: load(d / f"pair-{i:02}" / r / phase / "verified.json")
                        for phase in ("edit", "repeat-1", "repeat-2")
                    }
                    for r in "PC"
                }
            )
        result = load(d / "result.json")
        need(result["wall"] == summarize(pairs, order), "paired projection failed")
    print(f"Verified {n} closed phase receipts and each completed timing projection.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("receipts", type=Path)
    verify(p.parse_args().receipts)
