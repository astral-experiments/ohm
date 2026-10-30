"""Compare all original stock GNU provider outcomes to the two independently reopened Ohm histories."""
import argparse
import io
import json
import subprocess
import sys
import zipfile
from hashlib import sha256
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_native

RUN = 41079383532
QA = "af80b160a8236a73aef3ae71afc88c12830bc553"
BASE = "23caaefad9facf7e5c400c15f77e6c18122dd81d0efae082d8989761dded7f94"


def seal(gh, baseline, destination):
    def get(path):
        return subprocess.check_output([gh, "api", "repos/astral-experiments/ohm/" + path])

    def digest(wire):
        return sha256(wire).hexdigest()

    workflow = json.loads(get(f"actions/runs/{RUN}"))
    assert (workflow["head_sha"], workflow["status"], workflow["conclusion"]) == (QA, "completed", "success")
    item, = json.loads(get(f"actions/runs/{RUN}/artifacts"))["artifacts"]
    assert item["name"] == "gnu-physical-stock-1.99-restamped" and not item["expired"]
    assert 0 < item["size_in_bytes"] < 64 * 2**20 and item["workflow_run"]["id"] == RUN
    raw = get(f"actions/artifacts/{item['id']}/zip")
    assert len(raw) == item["size_in_bytes"] and "sha256:" + digest(raw) == item["digest"]
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert len(z.namelist()) == len(set(z.namelist())) and z.read("qa-head").decode().strip() == QA
        result = verify_native.verify(z)
        hosted = z.read("independent-native.json")
        assert json.loads(hosted) == result and result["total_Cargo"] == 108
        source = json.loads(z.read("stock-sdk.json"))
        assert source["version"] == "b940084d7eb6a299eb4bfeb8e34901bc051e7ac4" and source["plain_Cargo"]
        assert result["cargo_elf"] == source["executables"]["cargo"]
    base_bytes = baseline.read_bytes()
    assert digest(base_bytes) == BASE
    other = json.loads(base_bytes)["subjects"]
    assert set(other) == {"signed", "293"}
    groups = {}
    for name, stock in sorted(result["checks"].items()):
        role, watch, place = name.split("-")
        assert role == "S"
        comparison = {}
        for tag, candidate in other.items():
            for role in "ANM":
                matches = candidate["all_physical"][f"{role}-{watch}-{place}"]
                assert set(matches) == set(stock["physical_native"])
                changed = {}
                for phase, a in stock["physical_native"].items():
                    b = matches[phase]
                    stock_answer = [a["cargo_exit"], a["answer"]]
                    candidate_answer = [b["cargo_exit"], b["answer"]]
                    if stock_answer != candidate_answer:
                        changed[phase] = {"stock": stock_answer, "ohm": candidate_answer}
                comparison[f"{tag}/{role}"] = changed
        groups[name] = {
            "stock_differences_to_own_empty_full_elf_or_verdict": stock["differences_against_independent_clean"],
            "ordinary_runtime_or_verdict_differing_from_stock": comparison,
            "stock_actual": {n: {k: r[k] for k in ("answer", "cargo_exit", "elf", "actual_provider_ld")}
                             for n, r in stock["physical_native"].items()},
        }
    report = {"run": RUN, "QA": QA, "raw_artifact": [item["id"], len(raw), digest(raw)],
              "stock_cargo_source": result["cargo_source"], "stock_cargo_sha256": result["cargo_elf"],
              "stock_rustc_source": source["version"], "stock_rustc_sha256": source["executables"]["rustc"],
              "matched_ohm_readback": BASE, "independent_stock_readback": digest(hosted),
              "stock_terminal": result["source_terminal"], "matched_commands": 108, "groups": groups}
    wire = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        assert destination.read_bytes() == wire
    else:
        destination.open("xb").write(wire)
    print(digest(wire), len(wire), result["cargo_source"], flush=True)
    for name, group in groups.items():
        print(name, group["stock_differences_to_own_empty_full_elf_or_verdict"],
              sorted(group["ordinary_runtime_or_verdict_differing_from_stock"]["signed/M"]))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("gh")
    p.add_argument("baseline", type=Path)
    p.add_argument("destination", type=Path)
    a = p.parse_args()
    seal(a.gh, a.baseline, a.destination)
