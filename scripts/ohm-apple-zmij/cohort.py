"""Fixed-order native qualification, a two-pair screen and an independently rooted twelve-pair confirmation."""

import argparse
import collections
import itertools
import math
import statistics
from pathlib import Path

from execs import ExecTrace
from dyld import check as check_dyld
from measure import installation, select
from native_inputs import run_archive_check
from objects import bag
from study import ARGS, CHILD, EDIT, EXPECTED, ORDERS, PARENT, RUFF, check_host, load, need, save, sha
from wrapper import WrapperTrace

ENDPOINTS = ("edit", "repeat-1", "repeat-2")


def verify_reader(a, b):
    need(a["value"] == b["value"] and bag(a) == bag(b), "wrong actual native caller or AST object")
    return {
        "raw_reader_equal": a["sha256"] == b["sha256"],
        "raw_rlib_equal": a["archive_sha256"] == b["archive_sha256"],
        "raw_metadata_equal": a["archive_metadata"] == b["archive_metadata"],
        "member_names_equal": a["archive_objects"] == b["archive_objects"],
    }


def acquire(root, roles, trace, out):
    baseline = {}
    refs = {}
    parity = {}
    for role in roles:
        check_dyld(root, role, select(root, role), out / role / "dyld")
        subjects = {}
        for state in ("old", "new"):
            row = installation(root, role, out / role / ("empty-" + state), trace=trace, clean_only=state)[
                "clean-" + state
            ]
            subjects[state] = row["reader"]
            need(row["reader"]["value"] == EXPECTED[state], "independent native caller")
        refs[role] = subjects
        normal = installation(root, role, out / role / "actual", trace=trace, invalid=True)
        if not isinstance(trace, ExecTrace):
            plain = installation(root, role, out / role / "unwrapped", invalid=True)
            for phase, r in normal.items():
                q = plain[phase]
                need(
                    r["dirty"] == q["dirty"] and r["roster"] == q["roster"] and r["codes"] == q["codes"],
                    "observer changed workload",
                )
                if r["reader"]:
                    verify_reader(r["reader"], q["reader"])
        for k, v in normal.items():
            if v["reader"]:
                parity[role + "/" + k] = verify_reader(v["reader"], subjects[v["state"]])
        run_archive_check(root, role, trace, label=out.parent.name + "-" + role)
        baseline[role] = normal
    for s in refs["P"]:
        parity["across/" + s] = verify_reader(refs["P"][s], refs["C"][s])
    for k in ENDPOINTS:
        p, c = (baseline[r][k]["native"] for r in "PC")
        need(p["full"].count("zmij") == 1 and c["full"].count("zmij") == 0, "source cause missing")
        need(not (collections.Counter(c["full"]) - collections.Counter(p["full"])), "extra full compiler")
        need(p["link_only"] == c["link_only"] == [], "unexpected resumed native compiler")
        if isinstance(trace, ExecTrace):
            need(p["linkers"] == c["linkers"] == [], "unexpected extra linker")
    save(
        out / "verified.json",
        {
            "observer": trace.kind,
            "native": {r: {k: d[k]["native"] for k in ENDPOINTS} for r, d in baseline.items()},
            "parity": parity,
        },
    )
    return baseline, refs


def summarize(pairs, orders, key="ns", endpoints=ENDPOINTS):
    answer = {}
    for phase in endpoints:
        raw = [[p[role][phase]["cargo"][key] for role in "PC"] for p in pairs]
        if key != "ns" and any(a <= 0 or b <= 0 for a, b in raw):
            answer[phase] = {"unavailable": "counter or timer resolution", "raw_PC": raw}
            continue
        ratios = [a / b for a, b in raw]
        entry = {
            "raw_PC": raw,
            "ratios_P_over_C": ratios,
            "median_ratio": statistics.median(ratios),
            "parent_median": statistics.median(a for a, b in raw),
            "child_median": statistics.median(b for a, b in raw),
            "geometric_ratio": math.exp(statistics.mean(math.log(x) for x in ratios)),
        }
        if len(raw) == 12:
            ranked = sorted(ratios)
            entry["median_CI_96.14pct"] = [ranked[2], ranked[-3]]
            # Under the sharp null time(P)=2*time(C), map observed elapsed to control-equivalent
            # log units. Sign is assigned to period1/2 under each of all 924 balanced allocations.
            logres = [
                math.log(a / b / 2.0) * (1 if order == "PC" else -1) for (a, b), order in zip(raw, orders)
            ]
            observed = statistics.mean(math.log(x / 2.0) for x in ratios)
            vals = []
            for first in itertools.combinations(range(12), 6):
                vals.append(sum(x if i in first else -x for i, x in enumerate(logres)) / 12)
            entry["one_sided_balanced_sharp_2x_p"] = sum(x >= observed - 1e-12 for x in vals) / len(vals)
            entry["assignments"] = len(vals)
        answer[phase] = entry
    return answer


def fingerprint_sources():
    here = Path(__file__).resolve().parent
    return {p.name: sha(p) for p in sorted(here.iterdir()) if p.is_file() and p.suffix in (".py", ".md")}


def execute(mode, root):
    check_host(root, 8)
    receipts = root / "receipts"
    kernel = (receipts / "observer.json").is_file()
    pkg = load(receipts / "pair.json")
    out = receipts / mode
    out.mkdir()
    run_plan = {
        "mode": mode,
        "order": ORDERS[mode],
        "endpoint": "first unchanged immediately after the historical edit",
        "actual_argv": ARGS,
        "source": [PARENT, CHILD],
        "ruff": [RUFF, EDIT],
        "harness": fingerprint_sources(),
        "difference": pkg["differ"],
        "calibration": sha(receipts / "calibration/result.json"),
    }
    if mode == "confirm":
        plan = load(receipts / "screen/result.json")
        need(
            plan["accept_screen"]
            and plan["harness"] == run_plan["harness"]
            and plan["source"] == [PARENT, CHILD],
            "prior registered screen absent, different or below gate",
        )
        run_plan["admission"] = sha(receipts / "screen/result.json")
    save(out / "registered.json", run_plan)
    tracer = ExecTrace() if kernel else WrapperTrace()
    try:
        tracer.ready()
        baseline, refs = acquire(root, "PC", tracer, out / "native-before")
    finally:
        tracer.close()
    pairs = []
    for n, order in enumerate(ORDERS[mode], 1):
        pair = {}
        for role in order:
            check_host(root, 8)
            visit = installation(root, role, out / f"pair-{n:02}" / role, timed=True)
            pair[role] = visit
            for k in ("cold", *ENDPOINTS):
                row = visit[k]
                ref = baseline[role][k]
                need(
                    row["dirty"] == ref["dirty"]
                    and row["roster"] == ref["roster"] == baseline["P"][k]["roster"],
                    "unwrapped typed census changed",
                )
                verify_reader(row["reader"], refs[role][row["state"]])
        pairs.append(pair)
    tracer = ExecTrace() if kernel else WrapperTrace()
    try:
        tracer.ready()
        for role in "CP":
            closed = installation(root, role, out / "native-after" / role, trace=tracer)
            for k in ENDPOINTS:
                left, right = closed[k], baseline[role][k]
                need(
                    left["dirty"] == right["dirty"]
                    and left["native"]["full"] == right["native"]["full"]
                    and left["native"]["link_only"] == right["native"]["link_only"]
                    and left["native"]["linkers"] == right["native"]["linkers"],
                    "native terminal flank changed",
                )
                verify_reader(left["reader"], refs[role][left["state"]])
    finally:
        tracer.close()
    cal = load(receipts / "calibration/result.json")
    wall = summarize(pairs, ORDERS[mode])
    result = {
        "source": [PARENT, CHILD],
        "harness": run_plan["harness"],
        "mode": mode,
        "wall": wall,
        "observer_scope": tracer.kind,
        "registration": sha(out / "registered.json"),
        "counter_scope": cal["retired_instruction_scope"],
    }
    if cal["tree_CPU_calibrated"]:
        for i in pairs:
            for arm in i.values():
                for k in ENDPOINTS:
                    m = arm[k]["cargo"]
                    m["cpu"] = m["user"] + m["system"]
        result["cpu_seconds"] = summarize(pairs, ORDERS[mode], "cpu")
    if cal["retired_instruction_scope"] == "whole-tree-calibrated":
        result["retired_instructions"] = summarize(pairs, ORDERS[mode], "instructions")
    if mode == "screen":
        result["accept_screen"] = kernel and all(r > 2.0 for r in wall["repeat-1"]["ratios_P_over_C"])
    else:
        primary = wall["repeat-1"]
        result["accept_confirm"] = (
            kernel
            and primary["median_CI_96.14pct"][0] > 2.0
            and primary["one_sided_balanced_sharp_2x_p"] <= 0.05
        )
    save(out / "result.json", result)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=ORDERS)
    p.add_argument("root", type=Path)
    a = p.parse_args()
    execute(a.mode, a.root.resolve())
