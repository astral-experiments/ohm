"""Apply the preregistered balanced, paired twofold decision at the two primary endpoints."""
import itertools
import json
import math
from pathlib import Path
import statistics
import sys

from instructions import ALLOCS, order
from study import load, need, save


def evaluate(rows, endpoint):
    pairs = [(row["arms"]["P"]["Ir"][endpoint], row["arms"]["C"]["Ir"][endpoint]) for row in rows]
    ratios = sorted(p / c for p, c in pairs)
    # Under the sharp twofold null the adjusted observations are exchangeable across arm order.
    diffs = [math.log(p/c) - math.log(2) for p,c in pairs]
    temporal = [d if row["order"] == "PC" else -d for row,d in zip(rows,diffs)]
    obs = sum(diffs)
    greater_equal = sum(sum(v if j in a else -v for j,v in enumerate(temporal)) >= obs - 1e-12 for a in ALLOCS)
    return {"parent_median_Ir": statistics.median(p for p,c in pairs), "candidate_median_Ir": statistics.median(c for p,c in pairs),
            "median_paired_ratio": statistics.median(ratios), "min": ratios[0], "max": ratios[-1],
            "median_96_14pct_interval": [ratios[2],ratios[9]], "twofold_p": [greater_equal, len(ALLOCS)],
            "passes": ratios[2] > 2 and greater_equal / len(ALLOCS) <= .025, "individual": [p/c for p,c in pairs]}


def main():
    files = list(Path(sys.argv[1]).rglob("result-*.json"))
    rows = sorted((load(p) for p in files), key=lambda r:r["block"])
    need([r["block"] for r in rows] == list(range(12)), "incomplete or duplicate held-out block")
    need(all(r["order"] == order(r["block"]) and len(r["arms"]) == 2 for r in rows), "order changed")
    need(all(len({json.dumps(r[k]) for r in rows}) == 1 for k in ("qa","manifest","sources")), "unmatched subjects")
    primary = ["first-real-edit", "immediate-repeat"]
    scores = {e:evaluate(rows,e) for e in primary + ["edit-plus-repeat","settled"]}
    result = {"sources": rows[0]["sources"], "manifest": rows[0]["manifest"], "endpoints": scores,
              "eligible": any(scores[k]["passes"] for k in primary), "blocks": rows}
    save(Path(sys.argv[2]), result)
    print(json.dumps({e: {k:v for k,v in s.items() if k != "individual"} for e,s in scores.items()}, indent=2))


if __name__ == "__main__":
    main()
