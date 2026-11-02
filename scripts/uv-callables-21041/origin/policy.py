"""The preregistered marginal test uses exact integer per-rustc counts."""
from fractions import Fraction
from math import comb
from statistics import median

CRATES = ("uv_cache", "uv_client", "uv_configuration", "uv_distribution_types",
          "uv_install_wheel", "uv_metadata", "uv_pypi_types", "uv_torch")

def endpoint(values, threshold):
    if len(values) != 8 or any(len(v) != 2 or any(type(n) is not int or n <= 0 for n in v) for v in values):
        raise ValueError("expected eight positive parent/candidate hardware count pairs")
    ratios = [Fraction(c, p) for p, c in values]
    halves = [median(ratios[:4]), median(ratios[4:])]
    wins = sum(r < threshold for r in ratios)
    p = Fraction(sum(comb(8, k) for k in range(wins, 9)), 256)
    return {
        "raw_parent_candidate": values, "strict_threshold": str(threshold),
        "candidate_over_parent": list(map(str, ratios)), "hold_medians": list(map(str, halves)),
        "strict_wins": wins, "strict_half_wins": [r < threshold for r in halves],
        "at_threshold": sum(r == threshold for r in ratios),
        "at_or_below": sum(r <= threshold for r in ratios),
        "half_medians_at_or_below": [r <= threshold for r in halves],
        "one_sided_exact_sign_p_ties_against": str(p),
        "all_strict": wins == 8 and all(r < threshold for r in halves),
    }

def assess(metrics):
    if set(metrics) != {*CRATES, "sum_of_eight"}:
        raise ValueError("wrong enrolled rustc population")
    rows = {name: metrics[name]["raw_control_candidate"] for name in metrics}
    for name in CRATES:
        endpoint(rows[name], Fraction(1))
    sums = [[sum(rows[name][pair][arm] for name in CRATES) for arm in (0, 1)] for pair in range(8)]
    if sums != rows["sum_of_eight"]:
        raise ValueError("aggregate differs from individually observed rustc counters")
    primary = endpoint(sums, Fraction(996, 1000))
    named = endpoint(rows["uv_metadata"], Fraction(4, 5))
    return {"primary": "sum_of_eight", "qualified": primary["all_strict"], "eight_rustcs": primary,
            "named_secondary": "uv_metadata", "uv_metadata": named,
            "wall_separate": "Separate ordinary, unwrapped, blocking Cargo observation. No wall value enters either hardware endpoint."}
