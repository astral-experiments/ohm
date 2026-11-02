"""Recompute the whole-Cargo comparison from its 72 original retired-instruction records."""
from fractions import Fraction
from itertools import combinations
from math import exp, fsum, log, prod
import argparse
import hashlib
import json
from pathlib import Path
from statistics import median
import zipfile


RUN = 41442005889
HEAD = "a43236131847bb5906247e46656d702e543d3c50"
ORDERS = ("CP", "CP", "PC", "CP", "PC", "PC")
SUITES = ("e2e", "option")
PHASES = ("old", "new", "unchanged", "edit_plus_next")
STUDIES = {
    "option": ("3c77dcc2a5c04fc0c54ce95cd51068734015f3e0", "088b7b5f77fcb05994fd2a17cbc940cd9edb341a"),
    "e2e": ("ec92fb2b9c451acb04b43dbbf173b6a236eee67e", "f9115b8deefa56b18b79449f8acafe25475c54d3"),
}
ROSTERS = {
    "option": {
        "new": {"rustc": [["full", "ruff_workspace", 1]], "linkers": []},
        "unchanged": {"rustc": [], "linkers": []},
    },
    "e2e": {
        "new": {"rustc": [["full", "e2e", 1], ["full", "ty_server", 1]], "linkers": [["signed-Wild", "e2e", 1]]},
        "unchanged": {"rustc": [["link-only", "e2e", 1]], "linkers": [["signed-Wild", "e2e", 1]]},
    },
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def statistic(pairs, orders):
    assert len(pairs) == len(orders) == 6 and orders.count("PC") == 3
    chronological = [(p, c) if order == "PC" else (c, p) for (p, c), order in zip(pairs, orders, strict=True)]
    ratios = [Fraction(p, c) for p, c in pairs]
    threshold = prod(ratios)
    alternatives = []
    for positions in combinations(range(6), 3):
        value = prod(Fraction(a, b) if i in positions else Fraction(b, a)
                     for i, (a, b) in enumerate(chronological))
        alternatives.append(value)
    assert len(alternatives) == 20 and threshold in alternatives
    return {
        "pairs": pairs,
        "ratios": list(map(float, ratios)),
        "geometric_mean": exp(fsum(log(float(x)) for x in ratios) / len(ratios)),
        "median": float(median(ratios)),
        "min": float(min(ratios)),
        "max": float(max(ratios)),
        "favorable": sum(x > 1 for x in ratios),
        "ties": sum(x == 1 for x in ratios),
        "tail_over_20": sum(x >= threshold for x in alternatives),
    }


def verify_behavior(behavior, suite):
    assert behavior["invalid"]["error"] == "E0308"
    new = behavior["new"]
    assert len(new["elf"]) == 64 and behavior["old"]["elf"] != new["elf"]
    for phase in ("clean-new", "unchanged", "repair"):
        assert (behavior[phase]["elf"], behavior[phase]["verdict"]) == (new["elf"], new["verdict"])
    for phase in ("new", "unchanged"):
        assert behavior[phase]["raw_roster"] == ROSTERS[suite][phase]
    if suite == "option":
        assert behavior["old"]["verdict"] == "e65047ba02433d991a48910c34462adfba4886f8c9e4eb3c2b48460b10cbde9e"
        assert new["verdict"] == "ccae78bb0fc82d54b4d0f1024bbb6ad9c811bc034f233ae58b9c4072742113bd"
    else:
        assert behavior["old"]["verdict"]["count"] == 151 and not behavior["old"]["verdict"]["added"]
        assert new["verdict"]["count"] == 152 and new["verdict"]["added"] and new["verdict"]["negative_left"] is None
        assert behavior["negative"]["verdict"]["negative_left"] == "0:0..0:7[ERROR]: Name `missing` used when not defined"
        assert behavior["negative"]["elf"] != new["elf"] == behavior["restored-new"]["elf"]


def analyze(directory):
    reports = []
    hardware = json.loads((directory / "reopened-per-boot.json").read_bytes())
    accepted = json.loads((directory / "local-complete.json").read_bytes())
    assert accepted["run"] == RUN and accepted["qa"] == HEAD and accepted["native"] == 41436324816
    assert accepted["original_events"] == 72 and set(hardware) == {str(i) for i in range(1, 7)}
    assert sha(directory / "reopened-per-boot.json") == accepted["physical_counter_readback_sha256"]
    assert sha(directory / "original-hosted-summary.json") == accepted["summary_sha256"]
    native_output = {}
    for slot, order in enumerate(ORDERS, start=1):
        path = directory / f"independent-original-result-{slot}.zip"
        with zipfile.ZipFile(path) as z:
            assert z.namelist() == ["reopened.json"] and z.testzip() is None
            native = json.loads(z.read("reopened.json"))
        assert native["run"] == RUN and native["stage"] == "score" and native["slot"] == slot
        assert native["qa"] == HEAD and native["assignment"]["compilers"] == list(order)
        assert native["coverage"]["ordinary"] == 28 and native["coverage"]["probes"] == 24
        assert native["inputs"] == {k: list(v) for k, v in STUDIES.items()}
        raw = hardware[str(slot)]
        assert raw["original_archive"] == native["original_archive"] and len(raw["events"]) == 12
        block = {"slot": slot, "order": order, "boot": native["boot"], "values": {},
                 "original": native["original_archive"], "native_sha256": sha(path),
                 "coverage": native["coverage"], "roles": native["roles"]}
        for suite in SUITES:
            events = native["events"][suite]
            block["values"][suite] = {}
            for role in "PC":
                outcome = native["behavior"][suite][role]
                verify_behavior(outcome, suite)
                summaries = {k: [v.get("elf"), v.get("verdict"), v.get("error")] for k, v in outcome.items()}
                native_output.setdefault(suite, []).append(summaries)
                counts = block["values"][suite][role] = {}
                for phase in PHASES[:3]:
                    key = f"physical/{suite}/{role}-edit/{phase}/pmu.json"
                    original = raw["events"][key]
                    observed = original["hardware"]
                    assert observed["status"] == 0 and observed["enabled"] == observed["running"] > 0
                    assert type(observed["instructions"]) is int and observed["instructions"] > 0
                    assert events[role][phase]["raw_sha256"] == original["sha256"]
                    assert all(events[role][phase][k] == v for k, v in observed.items())
                    counts[phase] = observed["instructions"]
                counts["edit_plus_next"] = counts["new"] + counts["unchanged"]
        reports.append(block)
    assert len({b["boot"] for b in reports}) == 6
    assert all(r["roles"] == reports[0]["roles"] for r in reports)
    statistics = {}
    for suite in SUITES:
        for phase in PHASES:
            pairs = [(r["values"][suite]["P"][phase], r["values"][suite]["C"][phase]) for r in reports]
            result = statistic(pairs, ORDERS)
            registered = accepted["analysis"]["results"][f"{suite}/{phase}"]
            assert result["ratios"] == registered["p_over_c"] and result["median"] == registered["median"]
            assert abs(result["geometric_mean"] - registered["geomean"]) < 1e-12
            assert [result["min"], result["max"]] == registered["range"]
            if (suite, phase) != ("option", "new"):
                del result["tail_over_20"]
            statistics[f"{suite}/{phase}"] = result
    primary = statistics["option/new"]
    assert [primary["tail_over_20"], 20] == accepted["analysis"]["restricted_one_sided_assignment_p"]
    assert (primary["favorable"] == 6) == accepted["analysis"]["primary_all_above_one"]
    return {
        "statistics": statistics,
        "source_roles": reports[0]["roles"],
        "blocks": reports,
        "native_outputs_across_all_twelve_role_installs": {
            suite: {k: len({json.dumps(v[k], sort_keys=True) for v in group}) for k in group[0]}
            for suite, group in native_output.items()
        },
    }


def self_test():
    assert statistic([(7, 7)] * 6, ORDERS)["tail_over_20"] == 20
    assert statistic([(7, 3)] * 6, ORDERS)["tail_over_20"] == 1
    assert statistic([(3, 7)] * 6, ORDERS)["tail_over_20"] == 20
    one_tie = statistic([(7, 3)] * 5 + [(3, 3)], ORDERS)
    assert (one_tie["favorable"], one_tie["ties"], one_tie["min"]) == (5, 1, 1)
    intermediate = statistic([(7, 3), (6, 10), (3, 3), (20, 11), (4, 9), (11, 7)], ORDERS)
    assert 1 < intermediate["tail_over_20"] < 20


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("Five synthetic randomization, tie and sign controls passed.")
    if args.directory:
        result = analyze(args.directory)
        print(json.dumps(result, sort_keys=True, indent=2))
    elif not args.self_test:
        parser.error("supply a complete independent readback directory")
