"""Exact arithmetic for a completely authenticated set of twelve independent full-Ruff workers."""

from fractions import Fraction
from itertools import permutations
from math import comb
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "branch-first-session-e-screen"))
import metrics

ROLES = ("Foff", "Fon", "Eon")
POSITIONS = tuple(f"{n:02}" for n in range(1, 13))
FIRST = ("first-B", "same-first-B")
LANES = ("allocated", "unmetered_allocated")
THRESHOLDS = {
    "max_extra_bytes": 64 << 20,
    "min_saved_bytes": 250 << 20,
    "return_A": 2,
    "return_B": 2,
    "return_sum": 2,
}
MARGINAL = 1 - Fraction(2 * sum(comb(12, k) for k in (0, 1)), 2**12)
SIMULTANEOUS = 1 - len(THRESHOLDS) * (1 - MARGINAL)


def need(value, reason):
    if not value:
        raise ValueError(reason)


def form(fraction):
    q = Fraction(fraction)
    return [q.numerator, q.denominator]


def orders(registration):
    need(set(registration) == set(POSITIONS), "all twelve numbered orders required")
    six = set(permutations(ROLES))
    for block in (POSITIONS[:6], POSITIONS[6:]):
        need({tuple(registration[p]) for p in block} == six, "all six orders once per block")
    return registration


def median(values):
    s = sorted(values)
    need(len(s) == 12, "12 within-host values required")
    return (Fraction(s[5]) + s[6]) / 2


def passes(name, value):
    limit = THRESHOLDS[name]
    if name == "max_extra_bytes":
        return value <= limit
    if name == "min_saved_bytes":
        return value >= limit
    return value > limit


def endpoints(numbers):
    costs = metrics.evaluate(numbers, metrics.CONFIRMED)
    d = costs["storage"]
    residual = {}
    saving = {}
    for lane in LANES:
        for ph in FIRST:
            row = d[lane]["visits"][ph]["absolute"]
            residual[(ph, lane)] = row["Eon"] - row["Foff"]
            saving[(ph, lane)] = row["Fon"] - row["Eon"]
    pairs = {
        "max_extra_bytes": Fraction(max(residual.values())),
        "min_saved_bytes": Fraction(min(saving.values())),
    }
    for key, phase in (
        ("return_A", "return-A"),
        ("return_B", "return-B"),
        ("return_sum", "returns"),
    ):
        v = costs["instructions"][phase]["absolute"]
        pairs[key] = Fraction(v["Foff"], v["Eon"])
    cells = {
        f"{p}/{lane}": {"extra_bytes": residual[p, lane], "saved_bytes": saving[p, lane]}
        for p, lane in residual
    }
    for phase in costs["instructions"].values():
        counts = phase["absolute"]
        phase["Eon_over_Fon"] = form(Fraction(counts["Eon"], counts["Fon"]))
    return pairs, cells, costs


def describe(values):
    points = sorted(values)
    return {"range": [form(points[0]), form(points[-1])], "median": form(median(points))}


def secondary(positions):
    """Describe every paired visit and cost, including failures, without another confidence claim."""
    rows = [p["instructions_and_allocations"] for p in positions.values()]
    counts = {}
    for phase in rows[0]["instructions"]:
        values = [row["instructions"][phase]["absolute"] for row in rows]
        counts[phase] = {
            "instructions": {role: describe(v[role] for v in values) for role in ROLES},
            "Foff_over_Eon": describe(Fraction(v["Foff"], v["Eon"]) for v in values),
            "Eon_over_Fon": describe(Fraction(v["Eon"], v["Fon"]) for v in values),
        }
    storage = {}
    for lane in LANES:
        visits = rows[0]["storage"][lane]["visits"]
        phases = {}
        for phase in visits:
            values = [row["storage"][lane]["visits"][phase]["absolute"] for row in rows]
            phases[phase] = {
                "allocated_bytes": {role: describe(v[role] for v in values) for role in ROLES},
                "Eon_minus_Foff_bytes": describe(v["Eon"] - v["Foff"] for v in values),
                "Fon_minus_Eon_bytes": describe(v["Fon"] - v["Eon"] for v in values),
            }
        maximum = {
            history: {
                role: describe(r["storage"][lane]["largest_visit_end"][history][role] for r in rows)
                for role in ROLES
            }
            for history in ("main", "same")
        }
        storage[lane] = {"visits": phases, "largest_visit_end": maximum}
    return {"instructions": counts, "storage": storage}


def cohort(hosts, schedule, excluded):
    """Call after the original-media reader has verified every unmetered and empty reference."""
    orders(schedule)
    need(set(hosts) == set(POSITIONS), "one complete position for each of twelve workers")
    boots = {h["boot"] for h in hosts.values()}
    need(len(boots) == 12 and not boots.intersection(excluded), "duplicate or historical boot")
    values = {name: [] for name in THRESHOLDS}
    positions = {}
    for p in POSITIONS:
        host = hosts[p]
        need(host["order"] == schedule[p], "position differs from the registered six orders")
        raw, cells, costs = endpoints(host["numbers"])
        for name, x in raw.items():
            values[name].append(x)
        positions[p] = {
            "boot": host["boot"],
            "order": host["order"],
            "primary": {k: form(v) for k, v in raw.items()},
            "all_paired_first_switch_differences": cells,
            "instructions_and_allocations": costs,
            "whole_ordinary_inputs": host["numbers"],
            "each_primary_pass": {k: passes(k, v) for k, v in raw.items()},
        }
    stats = {}
    for k, items in values.items():
        xs = sorted(items)
        lo, hi = xs[1], xs[10]
        stats[k] = {
            "median": form(median(xs)),
            "ranks_2_11": [form(lo), form(hi)],
            "min_max": [form(xs[0]), form(xs[-1])],
            "threshold": THRESHOLDS[k],
            "all_12": all(passes(k, x) for x in xs),
            "interval_clears_threshold": passes(k, hi if k == "max_extra_bytes" else lo),
        }
    return {
        "positions": positions,
        "five_planned_endpoints": stats,
        "descriptive_warm_cold_edits_repair_and_maxima": secondary(positions),
        "interval_ranks": [2, 11],
        "each_coverage": form(MARGINAL),
        "family_coverage_at_least": form(SIMULTANEOUS),
        "all_five_and_all_boots_pass": all(
            q["all_12"] and q["interval_clears_threshold"] for q in stats.values()
        ),
        "included_pilot_observations": 0,
        "included_boots": len(boots),
    }
