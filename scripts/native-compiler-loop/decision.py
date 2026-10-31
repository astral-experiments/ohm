"""Calculate preregistered within-profile comparisons from existing raw counter and allocation data."""

import json
from pathlib import Path


def read(path):
    return json.loads(path.read_bytes())


def paid(path, kind):
    counter = read(path / "whole.json")
    assert (
        counter["code"] == 0
        and counter["event_errno"] == 0
        and counter["enabled"] == counter["running"]
        and counter["running"] > 0
        and counter["instructions"] > 0
    )
    visit = read(path / ("visit.json" if kind == "check" else "build.json"))
    assert visit["instructions"] == counter["instructions"]
    return [counter["instructions"], visit["storage"]["allocated_B"]]


def compare(packet):
    sample = {}
    for kind in ("check", "build"):
        edit = "historical-edit" if kind == "check" else "historical-hunk"
        sample[kind] = {}
        for level in "012":
            arms = {}
            for role in "PC":
                paths = (
                    packet / ("opt" + role + level)
                    if kind == "check"
                    else packet / ("linked-opt" + level) / ("opt" + str("PC".index(role)))
                )
                arms[role] = {
                    k: paid(paths / k, kind)
                    for k in ("cold", "neutral-unchanged", edit, "first-unchanged")
                }
                arms[role]["edit_plus_repeat"] = [
                    sum(arms[role][k][0] for k in (edit, "first-unchanged")),
                    arms[role]["first-unchanged"][1],
                ]
            rows = {}
            for endpoint in arms["P"]:
                parent, candidate = arms["P"][endpoint], arms["C"][endpoint]
                rows[endpoint] = {
                    "parent": parent,
                    "candidate": candidate,
                    "same_profile_P_over_C": parent[0] / candidate[0],
                    "candidate_minus_parent_allocated_B": candidate[1] - parent[1],
                }
            sample[kind][level] = rows
    opportunities = {
        (kind + "/" + n): data["1"][n]["same_profile_P_over_C"]
        for kind, data in sample.items()
        for n in ("first-unchanged", "edit_plus_repeat")
    }
    return {
        "same_profile": sample,
        "named_intrinsic_O1": opportunities,
        "at_least_1.8_on_this_worker": sorted(k for k, v in opportunities.items() if v >= 1.8),
        "at_least_2_on_this_worker": sorted(k for k, v in opportunities.items() if v >= 2.0),
    }


def cohort(left, right):
    assert left["named_intrinsic_O1"].keys() == right["named_intrinsic_O1"].keys()
    both = lambda threshold: sorted(
        k
        for k, v in left["named_intrinsic_O1"].items()
        if v >= threshold and right["named_intrinsic_O1"][k] >= threshold
    )
    return {
        "advance_same_endpoint_both_workers": both(1.8),
        "at_least_two_both_workers": both(2.0),
        "no_go": not both(1.8),
    }
