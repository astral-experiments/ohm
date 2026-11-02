"""Recompute the two registered workers independently and report all sixteen edit pairs."""
from fractions import Fraction
from pathlib import Path
from statistics import median
from zipfile import ZipFile
import argparse
import hashlib
import json
import subprocess
import sys


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def compare(first, second):
    plan = read(second / "replication-plan.json")
    assert plan == read(first / "replication-plan.json")
    assert sha(first / "independent-eight.json") == plan["first_result"]
    assert read(first / "origin.json")["original"] == plan["first_raw"]
    assert sha(first / "registration.json") == plan["first_registration"]
    assert sha(first / "release-lock.json") == plan["first_lock"]
    assert read(second / "replication-runner.json")["first_worker"] == read(first / "jobs.json")["jobs"][0]["runner_id"]
    first_lock = read(first / "release-lock.json")
    second_lock = read(second / "release-lock.json")
    assert first_lock.keys() == second_lock.keys()
    assert {key for key in first_lock if first_lock[key] != second_lock[key]} == {
        "registration", "excluded", "boot_list_sha256",
    }

    workers = []
    seen_seeds = set()
    sources = []
    installed = []
    cpus = []
    for directory in (first, second):
        raw = subprocess.check_output([sys.executable, "-ISB", str(directory / "verify.py")])
        study = json.loads(raw)
        assert study == read(directory / "independent-eight.json")
        sources.append(study["source"])
        with ZipFile(directory / "raw-members.zip") as records:
            intake = json.loads(records.read("intake.json"))
            cpus.append(json.loads(records.read("boot-attestation.json"))["affinity"])
            installed.append({
                role: {key: value[key] for key in ("source", "files", "effective_inventory", "runtime", "banners")}
                for role, value in intake["installed"].items()
            })
            for pair in range(1, 9):
                for arm in ("S", "F"):
                    seed = json.loads(records.read(f"native-22958/{pair}-{arm}/seed.json"))["sha256"]
                    assert seed not in seen_seeds
                    seen_seeds.add(seed)
        traces = study["all_compiler_executions"]
        workers.append({
            "worker": read(directory / "jobs.json")["jobs"][0]["runner_id"],
            "run": study["run"],
            "boot": study["boot"],
            "head": study["head"],
            "original": study["original_sha256"],
            "registered_wall_threshold_met": study["primary_wall_twofold_all_eight"],
            "kernel_traces": len(traces),
            "kernel_rustcs": sum(len(trace["units"]) for trace in traces),
            "metrics": study["metrics"],
        })

    assert sources[0] == sources[1]
    assert cpus[0] == cpus[1] and len(cpus[0]) == 8
    assert installed[0] == installed[1] and set(installed[0]) == {"S", "F"}
    assert len(seen_seeds) == 32
    assert all(len({worker[key] for worker in workers}) == 2 for key in ("worker", "run", "boot", "head", "original"))
    assert workers[0]["boot"] in plan["known_boots"] and workers[1]["boot"] not in plan["known_boots"]
    pooled = {}
    for name in workers[0]["metrics"]:
        raw = [row for worker in workers for row in worker["metrics"][name]["raw"]]
        assert len(raw) == 16
        speeds = [Fraction(before, after) for before, after in raw]
        pooled[name] = {
            "pairs": len(speeds),
            "strict_over_two": sum(speed > 2 for speed in speeds),
            "paired_median_speedup": float(median(speeds)),
            "min": float(min(speeds)),
            "max": float(max(speeds)),
        }
    return {
        "workers": workers,
        "compilers": sources[0],
        "verified_installed_sdk_inventories": {role: value["effective_inventory"] for role, value in installed[0].items()},
        "cpu_affinity": cpus[0],
        "independent_seed_histories": len(seen_seeds),
        "both_registered_wall_thresholds_met": all(w["registered_wall_threshold_met"] for w in workers),
        "all_sixteen_descriptive": pooled,
    }


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--first", type=Path, default=root.parent)
    result = compare(cli.parse_args().first, root)
    assert result == read(root / "both-workers.json")
    print(json.dumps(result, sort_keys=True, indent=2))
