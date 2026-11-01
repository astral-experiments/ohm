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


def bridge_identity(cfg, arm, summary, files):
    driver = "lib/librustc_driver-b03bf00bec23bb9a.so"
    need(summary["labels"] == cfg["labels"][arm] and summary["rust"] == cfg["role_rust"][arm] and
         summary["cargo"] == cfg["role_cargo"][arm] and summary["bolt"] is True and
         Path(summary["sdk"]).name == "sdk-" + arm, "SDK receipt mislabeled")
    need(all(files.get(k) == v for k,v in cfg["role_core"][arm].items()) and
         summary["loaded"]["librustc_driver"] == driver and summary["loaded"]["libLLVM"] in files and
         any(k.startswith("lib/rustlib/" + cfg["target"] + "/lib/libstd-") for k in files) and
         any(k.endswith("/bin/wild-ld/ld.bfd") for k in files), "incomplete or incorrect installed runtime")
    for tool, pin in (("rustc",cfg["role_rust"][arm]), ("cargo",cfg["role_cargo"][arm])):
        need("commit-hash: " + pin in summary["banner"][tool] and "host: " + cfg["target"] in summary["banner"][tool],
             "wrong toolchain banner")


def bridge_receipts(root, cfg):
    actors = cfg["arms"]
    need(actors == ["signed", "earlier", "rebased"] and len(set(cfg["role_rust"].values())) == 3 and
         cfg["measured_cargo"] == cfg["signed"]["cargo"] and cfg["argv"] == ["check","-p","uv-resolver","--locked","--offline","-j8"],
         "registered package or release roles changed")
    final = cfg["final"]
    member = final["name"] + ".tar.gz"
    shipped_archive = next(a["digest"][7:] for k,a in cfg["signed"]["assets"].items() if k.endswith(".tar.gz"))
    archives = {"signed":shipped_archive, "earlier":cfg["sdk_artifacts"]["both"]["inner_sha256"],
                "rebased":final["pkg_files"][member]["sha256"]}
    summaries = load(root / "installed-bridge.json")
    need(set(summaries) == set(actors) and load(root / "rebased-qa-context.json") == final["qa_context"] and
         load(root / "rebased-provenance.json") == final["provenance"] and
         load(root / "rebased-qa-binaries.json") == final["expected_installed"], "rebased provenance changed")
    for arm in actors:
        need(summaries[arm]["archive_sha256"] == archives[arm], "unregistered archive")
        bridge_identity(cfg, arm, summaries[arm], load(root / f"installed-{arm}-components.json"))
    proof = load(root / "native-source.json")
    need(proof == {"base":cfg["native_source_sha256"],"bridge":cfg["native_bridge_sha256"],"fixtures":cfg["fixture_sha256"]},
         "native qualifier changed")
    native_records(root / "native", actors, cfg["format_epochs"])


def native_records(root, actors, epochs):
    values = ["3 3 3 3 3", "3 3 3 3 3", "7 3 11 13 17", "3 7 3 3 3", "3 3 3 3 3", "3 7 3 3 3", "3 3 3 3 3"]
    for arm in actors:
        for rev, answer in enumerate(values):
            for solver, kind in itertools.product(("default","next"), ("warm","clean")):
                folder = root / ("trait-" + arm)
                label = f"{rev}-{solver}-{kind}-run"
                raw = (folder / (label + ".stdout")).read_bytes()
                result = load(folder / (label + ".json"))
                need(result["exit"] == 0 and hashlib.sha256(raw).hexdigest() == result["stdout_sha256"] and
                     raw.decode().strip() == answer, "cached or clean trait result changed")
    transitions = load(root / "cache-behavior.json")
    for mode in ("native", "forced"):
        section = transitions[mode]
        headers = section["headers"]
        need(set(headers) == set(actors) and len(section["transitions"]) == 9, "incomplete migration matrix")
        for key, h in headers.items():
            need(h["format"] == epochs[key] and (mode != "forced" or h["version"] == "rustc-perf"), "incorrect cache header")
        for writer, reader in itertools.product(actors, repeat=2):
            label = writer + "-to-" + reader
            expected = "loaded" if headers[writer] == headers[reader] else "rejected"
            need(section["transitions"][label] == expected, "readback disposition inconsistent")
            case = root / "migration" / mode / label
            need(load(case / "negative.json")["exit"] == 1 and b"E0277" in (case / "negative.stderr").read_bytes(),
                 "cached negative case missing")


def read(root):
    need(hashlib.sha256((root / "protocol.json").read_bytes()).hexdigest() == '9fc9cb8e6cdcd1c9f41aba13e570624749b730feccc5df82e0d660bf267de3c6', "protocol differs from reviewed registration")
    cfg = load(root / "protocol.json")
    bridge_receipts(root, cfg)
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
         load(root / "native/completed.json") == {"arms":cfg["arms"], "trait_edits":7,
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
                                         for a, b in (("signed", "rebased"), ("earlier", "rebased"), ("signed", "earlier"))}}
    return {"results": summary, "boot": host["boot"], "enrolled_trios_per_mode": 12, "calibration_sha256":meter["plain_sha256"],
            "rust": cfg["role_rust"], "labels": cfg["labels"],
            "cargo": cfg["measured_cargo"], "scope":"One host boot, two balanced holds, ordinary default package features for uv-resolver after #20988. Earlier/rebased measures combined source and training drift."}


if __name__ == "__main__":
    root = Path(sys.argv[1]).resolve(strict=True)
    answer = read(root)
    (root / "summary.json").write_text(json.dumps(answer, indent=2, sort_keys=True) + "\n")
    print(json.dumps({m: v["comparisons"] for m,v in answer["results"].items()}, sort_keys=True))
