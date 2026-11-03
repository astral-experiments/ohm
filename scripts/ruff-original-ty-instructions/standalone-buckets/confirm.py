"""Verify six physically independent, source-matched library build pairs and their exact interval."""
import argparse
import hashlib
import json
import math
import shutil
import statistics
import subprocess
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORDERS = ("PC", "CP", "CP", "PC", "PC", "CP")
OLD_ELF = "2407856bb255264e0dca8dbd9ef31ccfbaffeb1c2bfe800543d98b899db2ca6a"
NEW_ELF = "3755b8bab1d87e837a2d671d4a6c2333059d05f877e2f7e0940cf3b276d7e24f"


def must(condition, why):
    if not condition:
        raise ValueError(why)


def source_digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def series(pairs):
    changes = [c/p - 1 for p,c in pairs]
    return {"parent_median": statistics.median(p for p,c in pairs),
            "candidate_median": statistics.median(c for p,c in pairs),
            "median_paired_change": statistics.median(changes),
            "paired_range": [min(changes), max(changes)]}


def close(directory, index, output):
    assets = json.loads(index.read_bytes())
    must(assets["conclusion"] == "success" and len(assets["jobs"]) == len(assets["assets"]) == 6, "incomplete source cohort")
    run = assets["run"]
    must(run==41660912896 and assets["head"]=="6021d694d1c5d2e1a661e19b14d2990e7bb30834", "wrong enrolled source run")
    seen_boots = set()
    results = []
    for slot, order in enumerate(ORDERS):
        job, = [v for v in assets["jobs"] if v["name"] == f"Ruff #29697 library {slot} {order}"]
        artifact, = [v for v in assets["assets"] if v["name"] == f"matched-ty-ide-library-confirm-{run}-{slot}"]
        must(job["conclusion"] == "success" and artifact["workflow_run"]["id"] == run and not artifact["expired"], "source job or archived identity")
        sha = artifact["digest"].removeprefix("sha256:")
        archive = directory / f"{slot}.zip"
        individual = directory / f"{slot}-reopened.json"
        must(archive.stat().st_size == artifact["size_in_bytes"] and source_digest(archive) == sha, "wrong raw original")
        must(shutil.disk_usage(directory).free > 16 * 2**30, "insufficient temporary native object space")
        subprocess.run([sys.executable, "-IB", str(HERE/"reopen.py"), archive, "--sha256", sha, "--work", directory, "--output", individual],check=True)
        r = json.loads(individual.read_bytes())
        boot = str(uuid.UUID(r["hardware_boot"]))
        must(boot not in seen_boots and r["slot"] == slot and r["order"] == order, "repeated boot or changed registration")
        seen_boots.add(boot)
        must(r["units"] == 259 and r["unit_graph_nodes"] == 283 and r["physical_native_clients_executed"] == 2, "changed native workload")
        must(r["unit_graph_sha256"] == '6f857fca89ed462fb1984d6e23998f660c176d5a53fdd1517342027405383573', "different full graph from first source-bound pair")
        p,c = r["histories"]
        for h in (p,c):
            elf = h["oracle_elf"]
            must(elf["old"] == OLD_ELF and {elf[s] for s in ("edit","repair","independent-clean")} == {NEW_ELF}, "cross-boot complete native ELF mismatch")
            must(h["observed_matches_primary"] and h["CGUs"] == 171, "off-clock physical roster mismatch")
        must(r["metadata"]["equal_stable_identities_and_edit_key_sets"], "different stable public change")
        warm_drift = {}
        for key, delta in r["metadata"]["within_role_transitions"].items():
            if key.endswith("to-independent-clean"):
                warm_drift[key] = {field: {"parent_changed": t["P"][2]["count"],
                                      "candidate_changed": t["C"][2]["count"],
                                      "different_keys": [len(g) for g in t["different_keys"]]}
                                   for field,t in delta.items()}
        results.append({"slot":slot, "order":order, "boot":boot, "runner":r["runner"], "job":job["id"],
                        "original":{"id":artifact["id"],"bytes":archive.stat().st_size,"sha256":sha},
                        "independent_report_sha256":source_digest(individual),"speedup":p["primary"]/c["primary"],
                        "reduction":1-c["primary"]/p["primary"],"native_bodies":r["native_bodies"],
                        "new_physical_sources_bytes":r["native_bytes"],"warm_clean":warm_drift,"roles":r["histories"]})
    prices = [p["speedup"] for p in results]
    gains = [p["reduction"] for p in results]
    n = sum(x != 1 for x in prices)
    k = min(sum(x < 1 for x in prices),sum(x > 1 for x in prices))
    sign = min(1, 2*sum(math.comb(n,i) for i in range(k+1))/2**n)
    resources = {}
    for field in ("primary","cold","noop"):
        resources[field] = series([tuple(h[field] for h in p["roles"]) for p in results])
    for field in ("allocated_unique_bytes","logical_unique_bytes","physical_files"):
        resources[field] = series([tuple(h["footprint"][field] for h in p["roles"]) for p in results])
    out = {"source_run":run, "source_head":assets["head"], "pairs":results,
           "first_pair_excluded":41659042826,"matched_source_sdk_factory":41624273152,
           "median_speedup":statistics.median(prices),"speedup_interval":[min(prices),max(prices)],
           "median_reduction":statistics.median(gains),"reduction_interval":[min(gains),max(gains)],
           "coverage_of_median_interval":1-2/2**len(gains), "exact_two_sided_sign_p":sign,
           "confirmed_twofold":all(p["speedup"]>=2 and p["roles"][1]["retained"]>p["roles"][0]["retained"] for p in results),
           "resources":resources,"verified_native_bodies":sum(v["native_bodies"] for v in results),
           "independently_executed_clients":12,"old_elf":OLD_ELF,"new_elf":NEW_ELF}
    output.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    return out


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("directory",type=Path);parser.add_argument("--assets",type=Path,required=True);parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();result=close(args.directory,args.assets,args.output)
    print(result["median_speedup"],result["speedup_interval"],result["exact_two_sided_sign_p"],result["confirmed_twofold"])
