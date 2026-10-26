"""Compute effects and randomization probabilities for the balanced three-arm experiment."""

import argparse
import collections
import csv
import itertools
import json
import math
from pathlib import Path
import random
import statistics


def reduction(log_ratios):
    return -100 * math.expm1(-statistics.mean(log_ratios))


def compare(blocks, baseline, candidate, metric="total"):
    ratios = []
    linker_ratios = []
    source = collections.defaultdict(list)
    by_third_position = collections.defaultdict(list)
    counts_by_arm = collections.defaultdict(list)
    for block in blocks:
        assert len(block) == 3 and set(block) == {"control", "middle", "candidate"}
        a, b = block[baseline], block[candidate]
        (third,) = [
            row for arm, row in block.items() if arm not in {baseline, candidate}
        ]
        for key in ["edit", "units", "executables", "source_sha256", "outputs_sha256"]:
            assert a[key] == b[key] == third[key]
        log_ratio = math.log(int(a[metric]) / int(b[metric]))
        ratios.append(log_ratio)
        source[a["edit"]].append(log_ratio)
        if metric == "total":
            linker_ratios.append(math.log(int(a["wild"]) / int(b["wild"])))
        sign = 1 if int(a["position"]) < int(b["position"]) else -1
        by_third_position[int(third["position"])].append((sign, sign * log_ratio))
        for arm, row in block.items():
            counts_by_arm[arm].append(int(row[metric]))

    # Conditioning on the third arm's position leaves four blocks in each stratum.
    # Each contains exactly two baseline-first and two candidate-first assignments.
    sums = []
    for group in by_third_position.values():
        assert len(group) == 4 and sum(sign for sign, _ in group) == 0
        values = [x for _, x in group]
        sums.append(
            [
                2 * sum(values[i] for i in earlier) - sum(values)
                for earlier in itertools.combinations(range(4), 2)
            ]
        )
    assert (
        len(sums) == 3
        and set(source) == {"original", "changed"}
        and all(len(xs) == 6 for xs in source.values())
    )
    observed = abs(sum(ratios))
    permuted = [abs(sum(x)) for x in itertools.product(*sums)]
    tail = sum(x + 1e-14 >= observed for x in permuted)
    rng = random.Random(703031)
    bootstrap = sorted(
        reduction([rng.choice(group) for group in source.values() for _ in group])
        for _ in range(40000)
    )
    return {
        "baseline": baseline,
        "candidate": candidate,
        "n": len(blocks),
        "reduction_percent": reduction(ratios),
        "bootstrap95": [bootstrap[1000], bootstrap[-1001]],
        "favorable": sum(x > 0 for x in ratios),
        "conditional_randomization": {
            "two_sided_p": tail / len(permuted),
            "tail": tail,
            "assignments": len(permuted),
        },
        **(
            {"linker_reduction_percent": reduction(linker_ratios)}
            if linker_ratios
            else {}
        ),
        "half_reductions_percent": [reduction(ratios[:6]), reduction(ratios[6:])],
        "source_direction_percent": {s: reduction(xs) for s, xs in source.items()},
        ("median_instructions" if metric == "total" else "median_elapsed_ns"): {
            arm: statistics.median(xs) for arm, xs in counts_by_arm.items()
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--elapsed", action="store_true")
    args = parser.parse_args()
    blocks = collections.defaultdict(dict)
    with args.csv.open() as f:
        for row in csv.DictReader(f):
            if args.elapsed:
                assert int(row["elapsed_ns"]) > 0
            else:
                assert int(row["total"]) == sum(
                    int(row[role]) for role in ["cargo", "rustc", "clang", "wild"]
                )
            block = blocks[int(row["block"])]
            assert row["arm"] not in block
            block[row["arm"]] = row
    assert set(blocks) == set(range(12))
    ordered = [blocks[i] for i in range(12)]
    print(
        json.dumps(
            [
                compare(
                    ordered,
                    base,
                    "candidate",
                    "elapsed_ns" if args.elapsed else "total",
                )
                for base in ["middle", "control"]
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
