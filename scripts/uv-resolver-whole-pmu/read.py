"""Read every enrolled raw Cargo stream and hardware clock before calculating paired factors."""
import hashlib
import itertools
import json
import random
import re
import statistics
import sys
from pathlib import Path


def need(ok, text):
    if not ok:
        raise ValueError(text)


def load(path):
    return json.loads(path.read_bytes())


def planner(cfg):
    output = []
    for seed in cfg["holds"]:
        r = random.Random(seed)
        perms = list(itertools.permutations(cfg["arms"]))
        r.shuffle(perms)
        modes = [cfg["modes"], list(reversed(cfg["modes"]))] * 3
        r.shuffle(modes)
        output.append([{"arms": list(a), "modes": m} for a, m in zip(perms, modes, strict=True)])
    return output


def clock(row):
    keys = {"code", "instructions", "event_errno", "start", "stop", "enabled", "running", "user_us", "system_us"}
    need(set(row) == keys and all(type(v) is int for v in row.values()) and row["code"] == row["event_errno"] == 0 and
         row["instructions"] > 0 and row["enabled"] == row["running"] > 0 and 0 < row["start"] < row["stop"] and
         row["user_us"] + row["system_us"] > 0, "missing, multiplexed, malformed or failed ancestor counter")
    return row["instructions"]


def factors(rows, before, after):
    ratios = [r[before] / r[after] for r in rows]
    ordered = sorted(ratios)
    holds = [statistics.median(ratios[:6]), statistics.median(ratios[6:])]
    return {"paired_ratios": ratios, "paired_median": statistics.median(ratios),
            "hold_medians": holds, "median_interval_99_365_percent": [ordered[1], ordered[-2]],
            "every_pair_exceeds_2x": all(r > 2 for r in ratios),
            "qualifies_at_2x": ordered[1] > 2 and min(holds) > 2}


def verify(folder, cfg, mode, mask):
    timed = folder / "whole-clock.json"
    need(timed.is_file() == (mode == "pmu"), "mixed PMU and uninstrumented observations")
    for phase in ("cold", "unchanged-parent", "first-edit", "unchanged-child"):
        row = load(folder / (phase + ".json"))
        stderr = (folder / (phase + ".stderr")).read_bytes()
        stdout = (folder / (phase + ".stdout")).read_bytes()
        expect = ["uv-resolver"] if phase == "cold" else (
            cfg["expected_first_dirty"] if phase == "first-edit" else cfg["expected_unchanged_dirty"])
        dirty = sorted(x.decode() for x in re.findall(rb"^\s*(?:Checking|Compiling) ([\w-]+) v", stderr, re.M))
        need(row["exit"] == 0 and row["argv"][1:] == cfg["argv"] and
             Path(row["argv"][0]).parts[-3:] == ("rc23-trait-work", "bin", "cargo") and
             dirty == row["dirty"] and (all(x in dirty for x in expect) if phase == "cold" else dirty == expect) and
             row["cpus"] == mask and len(row["cpu_before"]) == len(row["cpu_after"]) == 8 and
             row["ns"] == row["end_ns"] - row["start_ns"] > 0, ("Cargo history or dirty roster", folder, phase))
        if "stdout_sha256" in row:
            need(hashlib.sha256(stdout).hexdigest() == row["stdout_sha256"] and
                 hashlib.sha256(stderr).hexdigest() == row["stderr_sha256"], "raw Cargo streams changed")
        if phase == "first-edit":
            native_row = row
    if mode == "native":
        need("observer_argv" not in native_row, "native wall includes an observer")
        return native_row["ns"] / 1e9
    pmu = load(timed)
    observer = native_row["observer_argv"]
    need(Path(observer[0]).parts[-3:] == ("logs", "observers", "plain") and
         Path(observer[1]).name == "whole-clock.json" and Path(observer[1]).parent.name == folder.name and
         observer[2:] == native_row["argv"] and
         native_row["start_ns"] <= pmu["start"] < pmu["stop"] <= native_row["end_ns"], "wrong counter scope")
    return clock(pmu)


def read(root):
    cfg = load(root / "protocol.json")
    plan = planner(cfg)
    need(load(root / "orders.json") == plan, "registration order changed")
    need(hashlib.sha256((root / "workspace-edit.patch").read_bytes()).hexdigest() == cfg["case"]["patch"], "patch changed")
    host = load(root / "host.json")
    meter = load(root / "calibration.json")
    need(meter["unmultiplexed_calibration_clocks"] == 28 and host["cpus"] == meter["ready"]["affinity"] and host["boot"] == meter["ready"]["boot"] and
         meter["abi"]["config"] == "PERF_COUNT_HW_INSTRUCTIONS" and meter["abi"]["inherit"] == 1 and
         meter["abi"]["exclude_kernel"] == 1 and meter["abi"]["exclude_hv"] == 1 and
         meter["abi"]["enable_on_exec"] == 1 and len(set(host["cpus"])) == 8, "hardware authority or boot changed")
    raw_calibration = root / "pmu-calibration"
    saved = sorted((raw_calibration / "calibration").glob("whole-*-*.json"))
    need(len(saved) == 28 and all(clock(load(p)) > 0 for p in saved) and
         hashlib.sha256((raw_calibration / "observers/plain").read_bytes()).hexdigest() == meter["plain_sha256"] and
         load(raw_calibration / "meter-ready.json") == meter["ready"], "original hardware calibrations failed readback")
    need(load(root / "active-cargo.json")["sha256"] == cfg["signed"]["cargo_sha256"] and
         load(root / "native/completed.json") == {"arms":["base", "nominal", "both"], "trait_edits":7,
                                                   "solvers":["default", "next"], "cache_transitions":18},
         "native fixtures or common Cargo failed")
    for arm in cfg["arms"]:
        for role, count in (("A", 1), ("B", 2)):
            w = load(root / f"uv-exclusion-{arm}-{role}.json")
            base = "workspace::tests::exclude_package"
            expected = sorted(([base] if count == 1 else [base, base + "_with_normalized_glob_and_escaped_root"]))
            need(w["passed"] == expected, "wrong uv behavior")
    trials = root / "trials"
    expect = set()
    for arm in cfg["arms"]:
        name = "excluded-pmu-" + arm
        verify(trials / name, cfg, "pmu", host["cpus"])
        expect.add(name)
    measures = {m: [] for m in cfg["modes"]}
    for h, hold in enumerate(plan, 1):
        for n, group in enumerate(hold, 1):
            for mode in group["modes"]:
                measure = {}
                for arm in group["arms"]:
                    name = f"h{h}-{n:02}-{mode}-{arm}"
                    measure[arm] = verify(trials / name, cfg, mode, host["cpus"])
                    expect.add(name)
                measures[mode].append(measure)
    need({p.name for p in trials.iterdir()} == expect and len(expect) == 75, "missing or extra trial")
    summary = {}
    for mode, rows in measures.items():
        summary[mode] = {"metric": "inherited userspace hardware instructions" if mode == "pmu" else "ordinary wall seconds",
                         "rows": rows, "medians": {a: statistics.median(r[a] for r in rows) for a in cfg["arms"]},
                         "comparisons": {a + "/" + b: factors(rows, a, b)
                                         for a, b in (("base", "both"), ("signed", "both"), ("signed", "base"))}}
    return {"results": summary, "boot": host["boot"], "enrolled_trios_per_mode": 12, "calibration_sha256":meter["plain_sha256"],
            "rust": {**{k: cfg["sdk_artifacts"][k]["source_commit"] for k in ("base","both")}, "signed":cfg["signed"]["rust"]},
            "cargo": cfg["measured_cargo"], "scope":"One runner boot, two balanced holds, one historical uv-resolver first edit."}


if __name__ == "__main__":
    root = Path(sys.argv[1]).resolve(strict=True)
    answer = read(root)
    (root / "summary.json").write_text(json.dumps(answer, indent=2, sort_keys=True) + "\n")
    print(json.dumps({m: v["comparisons"] for m,v in answer["results"].items()}, sort_keys=True))
