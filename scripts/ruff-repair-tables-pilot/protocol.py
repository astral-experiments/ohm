"""Registered single-host contrasts. All decisions use raw integer instruction and block counts."""

from pathlib import Path
import json

BASE = ("cold-A", "first-B", "return-A", "return-B", "unchanged-B", "invalid", "invalid-repeat", "repair")
RETURNS = ("return-A", "return-B", "post-repair-A", "post-repair-B")
CORE = BASE + ("post-repair-A", "post-repair-B")
ADJACENT = (
    "adjacent-invalid",
    "adjacent-invalid-repeat",
    "adjacent-repair",
    "adjacent-unchanged-B",
    "private-UP035-B",
    "private-repeat-B",
    "private-restore-B",
)
MAIN = CORE + ADJACENT
PEAK = BASE[:-1] + (
    "repair",
    "private-UP035-B",
    "private-repeat-B",
    "private-restore-B",
    "stage-invalid",
    "stage-invalid-repeat",
    "stage-repair",
    "stage-check",
    "stage-build",
    "donor-A",
    "donor-B",
    "verify-invalid",
    "verify-invalid-repeat",
    "verify-repair",
    "post-repair-A",
    "post-repair-B",
    "verify-private-B",
)
ORDINARY = ("single-source-B", "single-restore-B", "single-private-B", "single-repeat-B")
ROLES = ("Eon", "Ron", "Roff")
PEAK_ROLES = ("Ron", "Eon")
COMMAND = [
    "cargo",
    "+ohm",
    "build",
    "-p",
    "ruff",
    "--bin",
    "ruff",
    "--locked",
    "--offline",
    "-j4",
    "--message-format=json",
]
CHECK = [*COMMAND[:2], "check", *COMMAND[3:]]
EXPECT = {
    "cold-A": 375,
    "first-B": 20,
    "donor-A": 20,
    "donor-B": 20,
    "return-A": 20,
    "return-B": 20,
    "unchanged-B": 1,
    "repair": 16,
    "post-repair-A": 20,
    "post-repair-B": 20,
    "adjacent-repair": 16,
    "adjacent-unchanged-B": 1,
    "private-UP035-B": 7,
    "private-repeat-B": 1,
    "private-restore-B": 7,
    "stage-repair": 16,
    "verify-repair": 16,
    "verify-private-B": 7,
    "single-source-B": 375,
    "single-restore-B": 7,
    "single-private-B": 7,
    "single-repeat-B": 1,
}
M = 1 << 20


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def valid_count(value):
    return type(value) is int and value > 0


def objective(parent, candidate, parts, percentage):
    need(
        all(valid_count(x.get(p)) for x in (parent, candidate) for p in parts),
        "incomplete matched observations",
    )
    p, c = (sum(x[s] for s in parts) for x in (parent, candidate))
    return {
        "phases": parts,
        "old": p,
        "candidate": c,
        "max_percent": percentage,
        "passed": 100 * c <= percentage * p,
    }


def early(rows):
    p, c = rows["Eon"], rows["Ron"]
    return {
        "repair": objective(p, c, ["repair"], 110),
        "repair-next": objective(p, c, ["repair", "post-repair-A"], 105),
        "repair-both-returns": objective(p, c, ["repair", "post-repair-A", "post-repair-B"], 105),
        "adjacent-repair": objective(p, c, ["adjacent-repair"], 110),
        "adjacent-repair-next": objective(p, c, ["adjacent-repair", "adjacent-unchanged-B"], 105),
        "adjacent-repair-private": objective(
            p, c, ["adjacent-repair", "adjacent-unchanged-B", "private-UP035-B"], 105
        ),
        "ordinary-private-sequence": objective(
            p, c, ["private-UP035-B", "private-repeat-B", "private-restore-B"], 105
        ),
        **{
            pname: objective(p, c, [pname], 102)
            for pname in (
                "cold-A",
                "first-B",
                "return-A",
                "return-B",
                "invalid",
                "invalid-repeat",
                "unchanged-B",
                "adjacent-invalid",
                "adjacent-invalid-repeat",
                "adjacent-unchanged-B",
                "single-source-B",
                "single-restore-B",
                "single-private-B",
                "single-repeat-B",
            )
        },
    }


def final(rows, allocated, peaks):
    need(
        set(rows) == set(ROLES) and set(allocated) == set(ROLES) and set(peaks) == set(PEAK_ROLES),
        "missing or extra compiler role",
    )
    o, c = rows["Roff"], rows["Ron"]
    checks = early(rows)
    for k, parts in (
        ("pre-A", ["return-A"]),
        ("pre-B", ["return-B"]),
        ("pre-AB", ["return-A", "return-B"]),
        ("post-A", ["post-repair-A"]),
        ("post-B", ["post-repair-B"]),
        ("post-AB", ["post-repair-A", "post-repair-B"]),
    ):
        need(all(valid_count(r.get(n)) for n in parts for r in (o, c)), k)
        off, on = (sum(r[n] for n in parts) for r in (o, c))
        checks[k] = {"off": off, "on": on, "passed": off > 2 * on}
    for name, (p, c, bound) in {
        "first-B-over-off": (allocated["Roff"]["first-B"], allocated["Ron"]["first-B"], 64 * M),
        "repair-over-off": (allocated["Roff"]["repair"], allocated["Ron"]["repair"], 32 * M),
        "repair-versus-E": (allocated["Eon"]["repair"], allocated["Ron"]["repair"], -240 * M),
    }.items():
        need(valid_count(p) and valid_count(c), name)
        checks[name] = {"reference": p, "candidate": c, "max_delta": bound, "passed": c - p <= bound}
    for phase in ("repair", "private-UP035-B"):
        p, c = peaks["Eon"][phase], peaks["Ron"][phase]
        if p is None or c is None:
            checks[phase + "-sampled-resources"] = {
                "coverage": "unavailable host PID namespace",
                "passed": False,
            }
            continue
        if phase == "repair":
            checks["repair-private-writer-overlap"] = {
                "observed": c["max_working_table_pairs_observed"],
                "passed": c["max_working_table_pairs_observed"] > 0,
            }
        for field in ("allocated_including_deleted_peak", "pss_peak", "rss_peak"):
            need(valid_count(p[field]) and valid_count(c[field]), "missing high-water " + field)
            delta = c[field] - p[field]
            # RSS is additive across process mappings. PSS separately charges shared resident bytes fractionally.
            allowed = 160 * M if field.startswith("allocated") else max(64 * M, p[field] // 20)
            covered = not field.startswith("allocated") or all(
                v.get("all_deleted_mappings_accounted") is True for v in (p, c)
            )
            checks[phase + "-" + field] = {
                "old": p[field],
                "candidate": c[field],
                "max_delta": allowed,
                "interpretation": "sampled observed maxima only",
                "coverage": (
                    "complete at sampled boundaries"
                    if covered
                    else "inconclusive; unresolved deleted mapping"
                ),
                "passed": covered and delta <= allowed,
            }
    return {
        "conditions": checks,
        "passed": all(x["passed"] for x in checks.values()),
        "inference": "one host; no confidence or publication claim",
    }


def branch(phase):
    return "A" if phase in ("cold-A", "return-A", "post-repair-A", "clean-A", "donor-A") else "B"


def state(phase):
    if "invalid" in phase:
        return "invalid"
    if phase in (
        "private-UP035-B",
        "private-repeat-B",
        "clean-private-B",
        "verify-private-B",
        "single-source-B",
        "single-private-B",
        "single-repeat-B",
    ):
        return "private"
    return "clean"
