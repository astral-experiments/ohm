"""Compute paired whole-command instruction reductions from the published CSV."""

import argparse
import collections
import csv
import itertools
import math
import random
import statistics


def gain(ratios):
    return -100 * math.expm1(-statistics.mean(ratios))


def analyze(pairs):
    log_ratios = [math.log(int(base["total"]) / int(candidate["total"])) for base, candidate in pairs]
    wild = [math.log(int(base["wild"]) / int(candidate["wild"])) for base, candidate in pairs]
    observed = abs(sum(log_ratios))
    tail = sum(abs(sum(sign * value for sign, value in zip(signs, log_ratios))) + 1e-14 >= observed
               for signs in itertools.product((-1, 1), repeat=len(pairs)))
    strata = [[i for i, (base, _) in enumerate(pairs) if base["edit"] == edit] for edit in ("original", "changed")]
    rng = random.Random(703031)
    bootstrap = sorted(gain([log_ratios[rng.choice(stratum)] for stratum in strata for _ in stratum])
                       for _ in range(40_000))
    half = len(pairs) // 2
    return (f'whole-command instruction reduction {gain(log_ratios):.3f}% '
            f'(95% CI {bootstrap[1000]:.3f} to {bootstrap[-1001]:.3f}, '
            f'exact two-sided p={tail / 2**len(pairs):.6f}, '
            f'{sum(v > 0 for v in log_ratios)}/{len(pairs)} pairs favorable)\n'
            f'  halves {gain(log_ratios[:half]):.3f}%, {gain(log_ratios[half:]):.3f}%, '
            f'Wild alone {gain(wild):.3f}%')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv")
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    args = parser.parse_args()
    data = collections.defaultdict(lambda: collections.defaultdict(dict))
    with open(args.csv, newline="") as source:
        for row in csv.DictReader(source):
            assert int(row["total"]) == sum(int(row[k]) for k in ("cargo", "rustc", "clang", "wild"))
            block = data[row["mode"]][int(row["block"])]
            assert row["arm"] not in block
            block[row["arm"]] = row
    for mode, blocks in sorted(data.items()):
        pairs = [(blocks[i][args.baseline], blocks[i][args.candidate]) for i in sorted(blocks)]
        assert len(pairs) == 12
        for base, candidate in pairs:
            for key in ("edit", "units", "executables", "source_sha256", "outputs_sha256"):
                assert base[key] == candidate[key], (mode, base["block"], key)
        assert sum(base["edit"] == "original" for base, _ in pairs) == 6
        print(mode, analyze(pairs), sep="\n")
