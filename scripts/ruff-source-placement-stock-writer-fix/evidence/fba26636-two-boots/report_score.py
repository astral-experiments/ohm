"""Print the six registered workloads separately for each real boot using only absolute cells."""

from fractions import Fraction
import json
from pathlib import Path
import sys


def results(projection):
    d = json.loads(projection.read_bytes())
    assert d["schema"] == "two-independent-selected-source-boot-comparisons"
    assert d["count"] == 36 and d["scored_with_prior_cohort"] == 0
    assert len({x["boot"] for x in d["slots"]}) == 2
    val = {(r["slot"], r["suite"], r["phase"]): r for r in d["measurements"]}
    assert len(val) == 12
    out = []
    for i in (1, 2):
        for suite in ("option", "e2e"):
            for ph in ("old", "new", "unchanged"):
                row = val[i, suite, ph]
                cells = row["cells"]
                cols = [cells[r] for r in ("P", "C3b", "Stock4")]
                assert len({p["raw"] for p in cols}) == 3
                for j, r in enumerate(("P", "C3b")):
                    before, after = cols[j]["instructions"], cols[2]["instructions"]
                    rel = row["Stock4_vs"][r]
                    assert rel["factor"] == float(Fraction(before, after))
                    assert rel["instruction_reduction_percent"] == float(100 * Fraction(before - after, before))
                    assert rel["allocated_change"] == cols[2]["allocated_bytes"] - cols[j]["allocated_bytes"]
                    assert rel["kernel_maxrss_kib_change"] == cols[2]["kernel_maxrss_kib"] - cols[j]["kernel_maxrss_kib"]
                out.append((i, suite, ph, cols))
    return out


def tables(projection):
    data = results(projection)
    print("Positive percentages in the last two columns are fewer instructions. Each row is one physical boot.")
    print("\n| Boot | Ruff workload | Phase | #337 instructions | C3b instructions | Corrected instructions | Reduction vs #337 | Reduction vs C3b |")
    print("|---:|---|---|---:|---:|---:|---:|---:|")
    for i, s, p, cols in data:
        n = [c["instructions"] for c in cols]
        pr = [float(100 * Fraction(x - n[2], x)) for x in n[:2]]
        print(f"| {i} | {s} | {p} | {n[0]:,} | {n[1]:,} | {n[2]:,} | {pr[0]:+.4f}% | {pr[1]:+.4f}% |")
    print("\nAllocated bytes cover the recorded target and shared build outputs after each visit. RSS is the largest single descendant's kernel peak (KiB).")
    print("\n| Boot | Ruff workload | Phase | #337 allocated | C3b allocated | Corrected allocated | #337 RSS | C3b RSS | Corrected RSS |")
    print("|---:|---|---|---:|---:|---:|---:|---:|---:|")
    for i, s, p, cols in data:
        figures = [c[k] for k in ("allocated_bytes", "kernel_maxrss_kib") for c in cols]
        print(f"| {i} | {s} | {p} | " + " | ".join(f"{v:,}" for v in figures) + " |")


if __name__ == "__main__":
    tables(Path(sys.argv[1]))
