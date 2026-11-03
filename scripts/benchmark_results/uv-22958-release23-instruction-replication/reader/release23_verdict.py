"""Apply the pre-registered thresholds to the paired, independently verified measurements."""

from fractions import Fraction
from statistics import median


def paired_counts(metric):
    rows = metric["control_and_treatment"]
    if len(rows) != 8 or any(
        len(row) != 2 or any(type(value) is not int or value <= 0 for value in row)
        for row in rows
    ):
        raise ValueError("Expected eight positive integer pairs")
    return rows


def verdict(metrics):
    compilers = ("uv_configuration", "uv_client")
    counts = {name: paired_counts(metrics[name]) for name in (*compilers, "sum_two")}
    for configuration, client, total in zip(counts["uv_configuration"], counts["uv_client"], counts["sum_two"], strict=True):
        if [a + b for a, b in zip(configuration, client, strict=True)] != list(total):
            raise ValueError("The scoped total does not match the two rustc measurements")

    declarations = {}
    for name, rows in counts.items():
        ratios = [Fraction(candidate, control) for control, candidate in rows]
        holds = [median(ratios[:4]), median(ratios[4:])]
        gate = Fraction(4, 5)
        declarations[name] = {
            "median_cut_percent": float(100 * (1 - median(ratios))),
            "hold_cut_percent": [float(100 * (1 - hold)) for hold in holds],
            "pairs_at_least_20_percent": sum(ratio <= gate for ratio in ratios),
            "qualifies_20_percent": all(ratio <= gate for ratio in ratios + holds),
        }

    speedups = [Fraction(a, b) for a, b in paired_counts(metrics["wall"])]
    halves = [median(speedups[:4]), median(speedups[4:])]
    above = sum(value > 2 for value in speedups)
    return {
        "instruction_declarations": declarations,
        "median_wall_speedup": float(median(speedups)),
        "hold_wall_speedups": list(map(float, halves)),
        "pairs_strictly_above_2x": above,
        "qualifies_2x_on_this_host": above == 8 and all(value > 2 for value in halves),
    }
