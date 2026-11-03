"""Offline raw-backed second opinion for the six complete three-role measurement projections."""

from fractions import Fraction
from itertools import permutations
import hashlib
import io
import json
from math import prod
from pathlib import Path
from statistics import median
import sys
import zipfile

here = Path(__file__).resolve().parent
roles = ("P", "C2", "C3b")
pairs = (("P", "C2"), ("P", "C3b"), ("C2", "C3b"))
originals = {
    "P": "531eb1980c08c75ccbf3f6b77adbee53cd9b8bd5",
    "C2": "4e546b27c311f29d99f9528e64420887f57c7538",
    "C3b": "ed0262f9bdc384576925229764971f23a141c95f",
}
drivers = {
    "P": "cb6bd1e8074cfb4c092b270fa1450fcbf59941315615a5af48d537edeaf1933b",
    "C2": "dd34aec89ef43e54b3ba6bd82003701ef7f5fb89b723625742a307d2a6601fc6",
    "C3b": "e005172b9c7602695b50b697b7b7cf5b028a97d3de597f2c4a32745d47950674",
}


def open_original(row):
    b = (here / row["file"]).read_bytes()
    assert (
        len(b) == row["size_in_bytes"]
        and "sha256:" + hashlib.sha256(b).hexdigest() == row["digest"]
    )
    with zipfile.ZipFile(io.BytesIO(b)) as f:
        assert (
            f.namelist() == [row["member"]]
            and f.getinfo(row["member"]).file_size < 6 << 20
            and f.testzip() is None
        )
        return json.loads(f.read(row["member"]))


def tail(data, orders, reference):
    # Reconstruct costs at chronological positions, then enumerate the allocations
    # from numeric indices. Never use floating point for a tie; compare products.
    costs = [[block[role] for role in order] for block, order in zip(data, orders, strict=True)]
    allowed = list(permutations(range(6)))

    def score(table):
        if reference is None:
            numerator = prod(costs[i][row.index("P")] ** 2 for i, row in enumerate(table))
            denominator = prod(
                costs[i][row.index("C2")] * costs[i][row.index("C3b")]
                for i, row in enumerate(table)
            )
        else:
            a, b = reference
            numerator = prod(costs[i][row.index(a)] for i, row in enumerate(table))
            denominator = prod(costs[i][row.index(b)] for i, row in enumerate(table))
        return numerator, denominator

    nominal = score(orders)
    ge = 0
    size = 0
    for allocation in allowed:
        current = [orders[j] for j in allocation]
        if reference is not None:
            (third,) = set(roles) - set(reference)
            if any(
                obs.index(third) != test.index(third)
                for obs, test in zip(orders, current, strict=True)
            ):
                continue
        num, den = score(current)
        size += 1
        ge += num * nominal[1] >= nominal[0] * den
    assert size == (720 if reference is None else 8)
    return [ge, size]


def verify(native, reports, final, schedule, run):
    assert len(native) == 2 and len(reports) == 6 and all(x["new_gate"]["eligible"] for x in native)
    assert [x["slot"] for x in reports] == list(range(1, 7)) and len(
        {v["boot"] for v in reports + native}
    ) == 8
    assert all(
        v["run"] == run and v["source"] == originals and v["boot"] not in v["forbidden_boots"]
        for v in reports
    )
    assert (
        schedule["source"] == originals
        and run == 41501796384
        and all(v["qa"] == "ece4528e7e0e2d35a8fb4072fcb54ec7a245f5a8" for v in reports)
        and all(
            v["study"] == "61f7cd62c90929d985e9943bfb74a1788bef3e348e032c0ba1afb09b7968e5d7"
            for v in reports
        )
        and all(
            v["qa"] == v["reader_qa"] == "4b73020e7799d43f448b6ac703d82bb8b923b96b" for v in native
        )
        and all(
            u["raw"] == v["raw"]
            and u["slot"] == v["slot"]
            and u["boot"] == v["boot"]
            and u["raw"]["id"] != u["reader"]["id"]
            and u["raw"]["job"] != u["reader"]["job"]
            and u["terminal"] == v["terminal_sha256"]
            for u, v in zip(final["slots"], reports, strict=True)
        )
        and len({v["raw"]["id"] for v in reports})
        == len({v["reader"]["id"] for v in final["slots"]})
        == 6
    )
    assert [v["assignment"] for v in reports] == schedule["blocks"]
    orders = [r["roles"] for r in schedule["blocks"]]
    assert len(set(map(tuple, orders))) == 6 and all(sorted(o) == sorted(roles) for o in orders)
    raw_count = 0
    out = {}
    for suite in ("option", "e2e"):
        out[suite] = {}
        for ph in ("old", "new", "unchanged"):
            row = []
            footprints = []
            rss = []
            slot_guards = []
            for i, v in enumerate(reports):
                assert all(v["kits"][r]["driver"]["sha"] == drivers[r] for r in roles)
                a, b, c = {}, {}, {}
                for role in roles:
                    pm = v["counts"][suite][role][ph]
                    assert (
                        pm["phase"] == ph
                        and pm["enabled"] == pm["running"] > 0
                        and pm["status"] == 0
                    )
                    # count.c writes these five fields in this literal order.
                    # Reconstruct its original bytes, including the newline, and
                    # compare with the file read from the large native ZIP.
                    physical = {
                        k: pm[k] for k in ("pid", "instructions", "enabled", "running", "status")
                    }
                    raw_pm = (json.dumps(physical, separators=(",", ":")) + "\n").encode()
                    assert hashlib.sha256(raw_pm).hexdigest() == pm["raw_sha256"]
                    a[role] = pm["instructions"]
                    raw_count += 1
                    z = v["controls"][suite][role][ph]
                    b[role] = z["storage"]["allocated"]["allocated"]
                    c[role] = z["rss"]["kernel_maxrss_kib"]
                    assert (
                        a[role] > 0
                        and b[role] > 0
                        and c[role] > 0
                        and (role != "P" or z["storage"]["optional_tail_bytes"] == 0)
                    )
                    q = v["oracles"][suite][role]
                    assert (
                        q["invalid"]["error"] == "E0308"
                        and q["old"]["elf"] != q["new"]["elf"] == q["clean-new"]["elf"]
                    )
                    assert all(
                        q[k]["elf"] == q["new"]["elf"]
                        and q[k]["verdict"] == q["clean-new"]["verdict"]
                        for k in (
                            "new",
                            "unchanged",
                            "repair",
                            *(("restored-new",) if suite == "e2e" else ()),
                        )
                    )
                    cohort = final["absolute_and_controls"][suite][ph][i]
                    check = cohort["all_roles"][role]
                    assert (
                        cohort["absolute_instructions"][role] == a[role]
                        and check["allocated"] == b[role]
                        and check["kernel_maxrss_kib"] == c[role]
                    )
                    assert (
                        check["raw_counter_sha256"] == pm["raw_sha256"]
                        and check["rows_sha256"] == z["storage"]["rows_sha256"]
                    )
                    if ph == "new":
                        if suite == "e2e":
                            assert (
                                q["old"]["verdict"]["count"] == 151
                                and q["new"]["verdict"]["count"] == 152
                            )
                        expected = (1, 0) if suite == "option" else (2, 1)
                        nr = v["native_rosters"][suite][role][ph]
                        assert (nr["true_rustcs"], nr["actual_native"]) == expected
                assert len({v["oracles"][suite][role][ph]["elf"] for role in roles}) == 1
                row.append(a)
                footprints.append(b)
                rss.append(c)
            cell = final["all_endpoint_estimates"][suite][ph]
            assert cell["joint_right_tail"] == tail(row, orders, None)
            comparisons = {}
            for left, right in pairs:
                chosen = cell["contrasts"][left + "_" + right]
                differences = [Fraction(x[left] - x[right], x[left]) for x in row]
                assert (
                    float(median(differences)) == chosen["median_savings"]
                    and [float(min(differences)), float(max(differences))]
                    == chosen["individual_median_interval"]
                )
                assert chosen["positive"] == sum(v > 0 for v in differences) and chosen[
                    "ties"
                ] == sum(v == 0 for v in differences)
                assert chosen["conditional_right_tail"] == tail(row, orders, (left, right))
                assert chosen["all_over_10_percent"] == all(
                    v > Fraction(1, 10) for v in differences
                )
                assert chosen["all_over_2x"] == all(2 * x[right] < x[left] for x in row)
                comparisons[left + "_" + right] = {
                    "savings_percent": 100 * float(median(differences)),
                    "median_limits_percent": [
                        100 * float(min(differences)),
                        100 * float(max(differences)),
                    ],
                    "favorable": chosen["positive"],
                    "conditional_tail": chosen["conditional_right_tail"],
                    "every_gt_10_percent": chosen["all_over_10_percent"],
                    "every_gt_2x": chosen["all_over_2x"],
                    "median_allocation_delta": median(x[right] - x[left] for x in footprints),
                    "median_rss_delta_kib": median(x[right] - x[left] for x in rss),
                }
            out[suite][ph] = {
                "measurements": row,
                "physical_allocated": footprints,
                "maxrss_kib": rss,
                "comparisons": comparisons,
                "joint_right_tail": cell["joint_right_tail"],
            }
    assert raw_count == 108 and final["old_C2_two_pair_2x_screen"] is False
    assert final["primary_over_10_percent_each_of_6"] == {
        r: out["option"]["new"]["comparisons"]["P_" + r]["every_gt_10_percent"]
        for r in ("C2", "C3b")
    }
    return out


def selftest():
    o = list(map(list, permutations(roles)))
    flat = [dict.fromkeys(roles, 20) for _ in o]
    assert tail(flat, o, None) == [720, 720] and tail(flat, o, pairs[0]) == [8, 8]
    ordered = [dict(P=4, C2=3, C3b=1) for _ in o]
    assert tail(ordered, o, None) == [8, 720] and all(
        tail(ordered, o, pair) == [1, 8] for pair in pairs
    )
    print("Exact integer tie and complete randomization distribution controls pass.")


if __name__ == "__main__":
    selftest()
    if "--self-test-only" not in sys.argv:
        m = json.loads((here / "receipts.json").read_bytes())
        r = [open_original(x) for x in m["measurements"]]
        n = [open_original(x) for x in m["admissions"]]
        d = open_original(m["decision"])
        s = json.loads((here / "protocol.json").read_bytes())
        print(json.dumps(verify(n, r, d, s, m["run"]), indent=2, sort_keys=True))
