"""Prospective arithmetic on independently admitted per-host rows. No result-file ingress."""

from fractions import Fraction


MIB = 1 << 20
PHASES = ("cold-A", "first-B", "return-A", "return-B", "unchanged-B", "invalid", "repair")
SAME = ("same-cold-A", "same-edit", "same-repeat", "same-first-B")
ARMS = ("Eoff", "Kon", "Eon")


def ratio(a, b):
    return {"numerator": a, "denominator": b, "decimal": a / b}


def evaluate(arms):
    """Calculate one host. The separate media reader owns provenance and correctness admission."""
    if set(arms) != set(ARMS):
        raise ValueError("three distinct role names required")
    keys = ("instructions", "running", "enabled", "allocated", "unmetered_allocated")
    for arm in ARMS:
        if set(arms[arm]) != set(PHASES + SAME):
            raise ValueError(f"incomplete {arm} history")
        for phase in PHASES + SAME:
            row = arms[arm][phase]
            if any(type(row.get(k)) is not int or row[k] <= 0 for k in keys):
                raise ValueError(f"missing original positive integer for {arm}/{phase}")
            if not Fraction(995, 1000) <= Fraction(row["running"], row["enabled"]) <= 1:
                raise ValueError(f"inadmissible scheduling in {arm}/{phase}")

    def sums(phases):
        return [sum(arms[a][p]["instructions"] for p in phases) for a in ARMS]

    spans = {p: (p,) for p in PHASES + SAME}
    spans.update(
        returns=PHASES[2:4],
        first_B_and_return_A=PHASES[1:3],
        from_empty_through_returns=PHASES[:4],
        all_seven=PHASES,
        same_cold_edit=SAME[:2],
        same_history=SAME,
    )
    counts = {}
    for name, phases in spans.items():
        off, old, new = sums(phases)
        counts[name] = {
            "absolute": dict(zip(ARMS, (off, old, new), strict=True)),
            "Eoff_over_Eon": ratio(off, new),
            "Kon_over_Eon": ratio(old, new),
        }

    gates = {}
    storage = {}
    for lane in ("allocated", "unmetered_allocated"):
        rows = {}
        for phase in PHASES + SAME:
            off, old, new = [arms[a][phase][lane] for a in ARMS]
            rows[phase] = {
                "absolute": dict(zip(ARMS, (off, old, new), strict=True)),
                "Kon_minus_Eon": old - new,
                "Eon_minus_Eoff": new - off,
                "Kon_minus_Eoff": old - off,
            }
        first = rows["first-B"]
        saved = first["Kon_minus_Eon"]
        excess = first["Kon_minus_Eoff"]
        gates[lane] = {
            "positive_Kon_first_excess": excess > 0,
            "at_least_250_MiB_first_saving": saved >= 250 * MIB,
            "at_least_75_percent_first_excess_removed": excess > 0 and 4 * saved >= 3 * excess,
            "first_residual_at_most_64_MiB": first["Eon_minus_Eoff"] <= 64 * MIB,
            "settled_no_more_than_8_MiB_extra": rows["unchanged-B"]["Kon_minus_Eon"] >= -8 * MIB,
            "repair_no_more_than_8_MiB_extra": rows["repair"]["Kon_minus_Eon"] >= -8 * MIB,
        }
        second = rows["same-first-B"]
        after_edit = second["Kon_minus_Eon"]
        after_excess = second["Kon_minus_Eoff"]
        gates[lane].update(
            {
                "after_edit_positive_Kon_excess": after_excess > 0,
                "after_edit_250_MiB_saving": after_edit >= 250 * MIB,
                "after_edit_75_percent_excess_removed": after_excess > 0
                and 4 * after_edit >= 3 * after_excess,
                "after_edit_residual_at_most_64_MiB": second["Eon_minus_Eoff"] <= 64 * MIB,
            }
        )
        storage[lane] = {
            "visits": rows,
            "largest_visit_end": {
                label: {a: max(arms[a][p][lane] for p in selected) for a in ARMS}
                for label, selected in (("main", PHASES), ("same", SAME))
            },
        }
    off, old, new = sums(PHASES[2:4])
    cold = sums(PHASES[:1])
    first = sums(PHASES[1:2])
    cycle = sums(PHASES[:4])
    gates["instructions"] = {
        **{
            f"overall_2x_{name}": stats["absolute"]["Eoff"] >= 2 * stats["absolute"]["Eon"]
            for name, stats in counts.items()
            if name in ("return-A", "return-B", "returns")
        },
        "returns_within_10_percent_of_Kon": 10 * new <= 11 * old,
        "at_least_90_percent_of_Kon_saving": off > old and 10 * (off - new) >= 9 * (off - old),
        "same_edit_within_10_percent_of_Kon": 10 * sums(("same-edit",))[2]
        <= 11 * sums(("same-edit",))[1],
        "same_cold_plus_edit_within_5_percent_of_Kon": 100 * sums(SAME[:2])[2]
        <= 105 * sums(SAME[:2])[1],
        "cold_within_5_percent_of_Kon": 100 * cold[2] <= 105 * cold[1],
        "first_within_15_percent_of_Kon": 100 * first[2] <= 115 * first[1],
        "whole_empty_through_returns_1_2x": 5 * cycle[0] >= 6 * cycle[2],
    }
    return {
        "instructions": counts,
        "storage": storage,
        "arithmetic_only": True,
        "gates": gates,
        "meets_numeric_margins": all(all(g.values()) for g in gates.values()),
    }
