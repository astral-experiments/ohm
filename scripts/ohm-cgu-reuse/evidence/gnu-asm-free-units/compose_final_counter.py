"""Check the registered assignments and compute paired results from independently reopened Callgrind files."""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
from statistics import median

QA = "1f5a25f23bdfabafc1fb2a0b06d33e7095b14115"
RUST = "f69f7b7cf6de57972b310900decfac2d3a0c6fd6"
SEED = b"ohm:independent-cgus:f69f7b7c:ef23c9c3:whole-cargo-ir-v3"
ASSIGNMENTS = list(itertools.combinations(range(12), 6))
PARENT_FIRST = ASSIGNMENTS[int.from_bytes(hashlib.sha256(SEED).digest(), "big") % len(ASSIGNMENTS)]
PRIMARY = ("first-real-edit", "immediate-repeat")
ENDPOINTS = (*PRIMARY, "edit-plus-repeat", "settled")


def observations(directory, qa):
    blocks = []
    ids = set()
    for number in range(12):
        record = json.loads((directory / f"confirmed-{number}.json").read_text())
        assert record["qa"] == qa and record["source"] == RUST and record["artifact"] not in ids
        ids.add(record["artifact"])
        assert list(record["blocks"]) == [str(number)] and record["archive_bytes"] > 0
        row = record["blocks"][str(number)]
        assert row["order"] == ("PC" if number in PARENT_FIRST else "CP")
        for arm in row["matched"].values():
            for timing in arm["observed"].values():
                assert set(timing["processes"]) == {"cargo", "ruff_python_ast", "compact_str", "zmij"}
                assert timing["Ir"] == sum(timing["processes"].values())
        blocks.append(row)
    return blocks


def count(row, arm, endpoint):
    counts = row["matched"][arm]["observed"]
    if endpoint == "edit-plus-repeat":
        return sum(counts[k]["Ir"] for k in PRIMARY)
    return counts[endpoint]["Ir"]


def evaluate(rows, endpoint):
    parent = [count(r, "P", endpoint) for r in rows]
    child = [count(r, "C", endpoint) for r in rows]
    ratios = [p / c for p, c in zip(parent, child)]
    assert ratios == [row["ratios"][endpoint] for row in rows]
    # The signed order effect changes sign under each other balanced assignment.
    deltas = [math.log(ratio) - math.log(2) for ratio in ratios]
    period = [d if row["order"] == "PC" else -d for row, d in zip(rows, deltas)]
    test_stat = sum(deltas)
    accepted = 0
    for group in ASSIGNMENTS:
        statistic = sum(v if i in group else -v for i, v in enumerate(period))
        accepted += statistic >= test_stat - 1e-12
    ordered = sorted(ratios)
    return {
        "parent_median_Ir": median(parent), "candidate_median_Ir": median(child),
        "median_paired_ratio": median(ratios), "min": ordered[0], "max": ordered[-1],
        "median_96_14pct_interval": [ordered[2], ordered[9]],
        "twofold_p": [accepted, len(ASSIGNMENTS)],
        "passes": ordered[2] > 2 and accepted / len(ASSIGNMENTS) <= .025,
        "individual": ratios,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("hosted_decision", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--qa", default=QA)
    args = parser.parse_args()
    rows = observations(args.directory, args.qa)
    result = {endpoint: evaluate(rows, endpoint) for endpoint in ENDPOINTS}
    hosted = json.loads(args.hosted_decision.read_text())
    assert hosted["sources"] == ["82911b516fb35608fd70ada4deb6f8429277f410", RUST]
    assert hosted["endpoints"] == result and hosted["eligible"] == any(result[e]["passes"] for e in PRIMARY)
    disk = {arm: [r["matched"][arm]["allocated_bytes"] for r in rows] for arm in ("P","C")}
    details = {"qa": args.qa, "rust": RUST, "registered_parent_first": list(PARENT_FIRST),
               "endpoints": result, "median_allocated_bytes": {k: median(v) for k,v in disk.items()},
               "allocated_bytes": disk, "reopened_blocks": rows}
    with args.output.open('x') as f:
        json.dump(details, f, indent=2)
        f.write('\n')
    for label, score in result.items():
        print(label, score["median_paired_ratio"], score["median_96_14pct_interval"], score["twofold_p"])
    print("Median allocated bytes", details["median_allocated_bytes"])


if __name__ == "__main__":
    main()
