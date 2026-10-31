"""Prospective arithmetic on independently admitted per-host rows. No result-file ingress."""

from fractions import Fraction


MIB = 1 << 20
PHASES = ("cold-A", "first-B", "return-A", "return-B", "unchanged-B", "invalid", "repair")
SAME = ("same-cold-A", "same-edit", "same-repeat", "same-first-B")
ARMS = ("Eoff", "Kon", "Eon")
TABLE_ONLY = ("Foff", "Fon", "Ton")


def ratio(a, b):
    return {"numerator": a, "denominator": b, "decimal": a / b}


def evaluate(arms, roles=ARMS):
    """Calculate one host. The separate media reader owns provenance and correctness admission."""
    if roles not in (ARMS, TABLE_ONLY) or set(arms) != set(roles):
        raise ValueError("three distinct role names required")
    disabled, previous, candidate = roles
    saved_bytes = f"{previous}_minus_{candidate}"
    residual_bytes = f"{candidate}_minus_{disabled}"
    excess_bytes = f"{previous}_minus_{disabled}"
    keys = ("instructions", "running", "enabled", "allocated", "unmetered_allocated")
    for arm in roles:
        if set(arms[arm]) != set(PHASES + SAME):
            raise ValueError(f"incomplete {arm} history")
        for phase in PHASES + SAME:
            row = arms[arm][phase]
            if any(type(row.get(k)) is not int or row[k] <= 0 for k in keys):
                raise ValueError(f"missing original positive integer for {arm}/{phase}")
            if not Fraction(995, 1000) <= Fraction(row["running"], row["enabled"]) <= 1:
                raise ValueError(f"inadmissible scheduling in {arm}/{phase}")

    def sums(phases):
        return [sum(arms[a][p]["instructions"] for p in phases) for a in roles]

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
            "absolute": dict(zip(roles, (off, old, new), strict=True)),
            f"{disabled}_over_{candidate}": ratio(off, new),
            f"{previous}_over_{candidate}": ratio(old, new),
        }

    gates = {}
    storage = {}
    for lane in ("allocated", "unmetered_allocated"):
        rows = {}
        for phase in PHASES + SAME:
            off, old, new = [arms[a][phase][lane] for a in roles]
            rows[phase] = {
                "absolute": dict(zip(roles, (off, old, new), strict=True)),
                saved_bytes: old - new,
                residual_bytes: new - off,
                excess_bytes: old - off,
            }
        first = rows["first-B"]
        saved = first[saved_bytes]
        excess = first[excess_bytes]
        gates[lane] = {
            f"positive_{previous}_first_excess": excess > 0,
            "at_least_250_MiB_first_saving": saved >= 250 * MIB,
            "at_least_75_percent_first_excess_removed": excess > 0 and 4 * saved >= 3 * excess,
            "first_residual_at_most_64_MiB": first[residual_bytes] <= 64 * MIB,
            "settled_no_more_than_8_MiB_extra": rows["unchanged-B"][saved_bytes] >= -8 * MIB,
            "repair_no_more_than_8_MiB_extra": rows["repair"][saved_bytes] >= -8 * MIB,
        }
        second = rows["same-first-B"]
        after_edit = second[saved_bytes]
        after_excess = second[excess_bytes]
        gates[lane].update(
            {
                f"after_edit_positive_{previous}_excess": after_excess > 0,
                "after_edit_250_MiB_saving": after_edit >= 250 * MIB,
                "after_edit_75_percent_excess_removed": after_excess > 0
                and 4 * after_edit >= 3 * after_excess,
                "after_edit_residual_at_most_64_MiB": second[residual_bytes] <= 64 * MIB,
            }
        )
        storage[lane] = {
            "visits": rows,
            "largest_visit_end": {
                label: {a: max(arms[a][p][lane] for p in selected) for a in roles}
                for label, selected in (("main", PHASES), ("same", SAME))
            },
        }
    off, old, new = sums(PHASES[2:4])
    cold = sums(PHASES[:1])
    first = sums(PHASES[1:2])
    cycle = sums(PHASES[:4])
    gates["instructions"] = {
        **{
            f"overall_2x_{name}": stats["absolute"][disabled] >= 2 * stats["absolute"][candidate]
            for name, stats in counts.items()
            if name in ("return-A", "return-B", "returns")
        },
        f"returns_within_10_percent_of_{previous}": 10 * new <= 11 * old,
        f"at_least_90_percent_of_{previous}_saving": off > old
        and 10 * (off - new) >= 9 * (off - old),
        f"same_edit_within_10_percent_of_{previous}": 10 * sums(("same-edit",))[2]
        <= 11 * sums(("same-edit",))[1],
        f"same_cold_plus_edit_within_5_percent_of_{previous}": 100 * sums(SAME[:2])[2]
        <= 105 * sums(SAME[:2])[1],
        f"cold_within_5_percent_of_{previous}": 100 * cold[2] <= 105 * cold[1],
        f"first_within_15_percent_of_{previous}": 100 * first[2] <= 115 * first[1],
        "whole_empty_through_returns_1_2x": 5 * cycle[0] >= 6 * cycle[2],
    }
    result = {
        "instructions": counts,
        "storage": storage,
        "arithmetic_only": True,
        "gates": gates,
        "meets_numeric_margins": all(all(g.values()) for g in gates.values()),
    }

    if roles == TABLE_ONLY:
        narrow = all(gates["instructions"].values())
        for value in counts.values():
            baseline = value["absolute"][previous]
            value["instructions_over_Fon"] = {
                role: ratio(n, baseline) for role, n in value["absolute"].items()
            }
        for lane in ("allocated", "unmetered_allocated"):
            for values in storage[lane]["visits"].values():
                values["bytes_above_Foff"] = {
                    role: n - values["absolute"][disabled]
                    for role, n in values["absolute"].items()
                }
            narrow &= all(
                gates[lane][g]
                for g in (
                    "at_least_250_MiB_first_saving",
                    "after_edit_250_MiB_saving",
                    "settled_no_more_than_8_MiB_extra",
                    "repair_no_more_than_8_MiB_extra",
                )
            )
        result["incremental_table_storage_and_instructions_only"] = narrow
    return result
