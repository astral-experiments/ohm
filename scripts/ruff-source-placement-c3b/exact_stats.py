"""Enumerate the actual randomized assignments of a balanced three-treatment block experiment."""

from fractions import Fraction
from itertools import combinations, permutations
import json
from math import prod
from pathlib import Path
from statistics import median

ROLES = ("P", "C2", "C3b")
PERMS = tuple(permutations(ROLES))
ALL = tuple(permutations(PERMS))
CONTRASTS = (("P", "C2"), ("P", "C3b"), ("C2", "C3b"))


def registered(d):
    q = d["assignment"]

    def draw(name, n, index):
        x = int(q[name], 16)
        assert len(q[name]) == 64 and x < (1 << 256) - ((1 << 256) % n) and x % n == q[index]
        return x % n

    schedules = ALL[draw("role_permutation_draw", 720, "scope_assignment_index")]
    option_first = list(combinations(range(1, 7), 3))[
        draw("suite_draw", 20, "suite_assignment_index")
    ]
    assert d["blocks"] == [
        {
            "slot": i,
            "roles": list(o),
            "suites": ["option", "e2e"] if i in option_first else ["e2e", "option"],
        }
        for i, o in enumerate(schedules, 1)
    ]
    return schedules


def rand_test(cells, schedule, baseline=None, treatment=None):
    if baseline is None:
        allowed = ALL

        def stat(s):
            p = prod(cells[i][x.index("P")] for i, x in enumerate(s))
            return Fraction(
                p * p, prod(cells[i][x.index(r)] for i, x in enumerate(s) for r in ("C2", "C3b"))
            )

    else:
        (remaining,) = set(ROLES) - {baseline, treatment}
        allowed = [
            s
            for s in ALL
            if all(
                x.index(remaining) == o.index(remaining) for x, o in zip(s, schedule, strict=True)
            )
        ]
        assert len(allowed) == 8

        def stat(s):
            return Fraction(
                prod(cells[i][x.index(baseline)] for i, x in enumerate(s)),
                prod(cells[i][x.index(treatment)] for i, x in enumerate(s)),
            )

    observed = stat(schedule)
    return [sum(stat(s) >= observed for s in allowed), len(allowed)]


def endpoint(rows, schedule):
    assert len(rows) == 6 and all(
        set(row) == set(ROLES) and all(type(v) is int and v > 0 for v in row.values())
        for row in rows
    )
    cells = [[row[r] for r in order] for order, row in zip(schedule, rows, strict=True)]
    contrasts = {}
    for b, c in CONTRASTS:
        effects = [Fraction(row[b] - row[c], row[b]) for row in rows]
        contrasts[b + "_" + c] = {
            "per_boot_savings": list(map(float, effects)),
            "median_savings": float(median(effects)),
            "individual_median_interval": [float(min(effects)), float(max(effects))],
            "positive": sum(x > 0 for x in effects),
            "ties": sum(x == 0 for x in effects),
            "all_over_10_percent": all(x > Fraction(1, 10) for x in effects),
            "all_over_2x": all(row[b] > 2 * row[c] for row in rows),
            "conditional_right_tail": rand_test(cells, schedule, b, c),
        }
    return {
        "counts_in_chronological_order": cells,
        "contrasts": contrasts,
        "joint_right_tail": rand_test(cells, schedule),
    }


def test():
    d = json.loads((Path(__file__).resolve().parent / "three-arm-protocol.json").read_bytes())
    order = registered(d)
    flat = endpoint([{r: 100 for r in ROLES} for _ in order], order)
    assert flat["joint_right_tail"] == [720, 720] and all(
        v["conditional_right_tail"] == [8, 8] and v["ties"] == 6 for v in flat["contrasts"].values()
    )
    separated = [dict(P=400 + i, C2=300 + i, C3b=100 + i) for i in range(6)]
    got = endpoint(separated, order)
    assert got["joint_right_tail"] == [8, 720] and all(
        v["conditional_right_tail"] == [1, 8] for v in got["contrasts"].values()
    )
    assert not got["contrasts"]["P_C2"]["all_over_2x"] and got["contrasts"]["P_C3b"]["all_over_2x"]
    # A single exactly-threshold, harmful or missing observation cannot pass.
    for last in (360, 400, 444):
        bad = separated[:-1] + [dict(P=400, C2=last, C3b=55)]
        assert not endpoint(bad, order)["contrasts"]["P_C2"]["all_over_10_percent"]
    malformed = set()
    for name in ("P", "C2", "C3b"):
        try:
            endpoint([{k: v for k, v in row.items() if k != name} for row in separated], order)
        except AssertionError:
            malformed.add(name)
    assert sorted(malformed) == sorted(ROLES)
    print(
        "Frozen role and suite orders, 720 schedules, 8 conditional schedules, ties, strict thresholds and missing-arm veto all passed."
    )


if __name__ == "__main__":
    test()
