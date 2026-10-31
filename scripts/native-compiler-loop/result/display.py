"""Format the two independent workers without pooling native counts."""

from pathlib import Path
import json, sys


def tables(out):
    workers = out["workers"]
    assert len(workers) == 2
    cell = lambda w, kind, level, phase: w["counters"]["same_profile"][kind][
        str(level)
    ][phase]
    result = {}
    for name in ("check", "build"):
        result[name] = {}
        edit = {"check": "historical-edit", "build": "historical-hunk"}[name]
        for name2, n in (
            ("cold", "cold"),
            ("neutral", "neutral-unchanged"),
            ("edit", edit),
            ("repeat", "first-unchanged"),
            ("edit+repeat", "edit_plus_repeat"),
        ):
            costs = [cell(w, name, 0, n) for w in workers]
            costs_1 = [cell(w, name, 1, n) for w in workers]
            costs_2 = [cell(w, name, 2, n) for w in workers]
            ratio = lambda count, den: [round(a / b, 5) for a, b in zip(count, den)]
            v = {}
            for role in ("parent", "candidate"):
                c = lambda cs: [x[role][0] for x in cs]
                v[role + "_O0_to_O1"] = ratio(c(costs), c(costs_1))
                v[role + "_O0_to_O2"] = ratio(c(costs), c(costs_2))
            for lv, cs in (("0", costs), ("1", costs_1), ("2", costs_2)):
                v["within_O" + lv] = [round(x["same_profile_P_over_C"], 5) for x in cs]
                v["P" + lv + "_Ginsn"] = [round(x["parent"][0] / 1e9, 6) for x in cs]
                v["C" + lv + "_Ginsn"] = [round(x["candidate"][0] / 1e9, 6) for x in cs]
                v["P" + lv + "_MiB"] = [round(x["parent"][1] / 2**20, 4) for x in cs]
                v["C" + lv + "_MiB"] = [round(x["candidate"][1] / 2**20, 4) for x in cs]
                v["candidate_minus_parent_O" + lv + "_MiB"] = [
                    round(x["candidate_minus_parent_allocated_B"] / 2**20, 4)
                    for x in cs
                ]
            result[name][name2] = v
    result["thresholds"] = {
        "mechanism": out["decision"],
        "default_O0_instruction_regression_over_3pct": [],
        "costs": [],
    }
    for w in workers:
        for level in (0, 1, 2):
            for command in ("check", "build"):
                old = cell(w, command, level, "cold")
                new = cell(w, command, level, "first-unchanged")
                result["thresholds"]["costs"].append(
                    {
                        "worker": w["row"],
                        "kind": command,
                        "level": level,
                        "cold_increase_over_5pct": old["candidate"][0]
                        / old["parent"][0]
                        > 1.05,
                        "repeat_storage_increase_over_8MiB": new["candidate"][1]
                        - new["parent"][1]
                        > 8 * 2**20,
                        "repeat_storage_increase_over_1pct": new["candidate"][1]
                        / new["parent"][1]
                        > 1.01,
                    }
                )
        for command in ("check", "build"):
            for phase, c in w["counters"]["same_profile"][command]["0"].items():
                if c["candidate"][0] / c["parent"][0] > 1.03:
                    result["thresholds"]["default_O0_instruction_regression_over_3pct"].append(
                        [
                            w["row"],
                            command,
                            phase,
                            round(c["candidate"][0] / c["parent"][0] - 1, 4),
                        ]
                    )
    return result


if __name__ == "__main__":
    print(json.dumps(tables(json.loads(Path(sys.argv[1]).read_bytes())), indent=2))
