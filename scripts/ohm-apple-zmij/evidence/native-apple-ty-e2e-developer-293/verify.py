"""Recompute the separate macOS ty_server test build endpoints from the original clocks."""
import argparse
import hashlib
import itertools
import json
import math
import statistics
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from calibrate import fields

PREFIX = "ty-clock-confirmation/"
ENDPOINTS = ("edit", "repeat-1", "repeat-2", "edit+repeat-1")


def paired(values, order):
    ratios = [parent / candidate for parent, candidate in values]
    ranked = sorted(ratios)
    differences = [math.log(ratio / 2) for ratio in ratios]
    period = [v if seq == "PC" else -v for seq, v in zip(order, differences)]
    observed = statistics.mean(differences)
    assignments = list(itertools.combinations(range(12), 6))
    count = sum(
        sum(v if i in slots else -v for i, v in enumerate(period)) / 12 >= observed - 1e-12
        for slots in assignments
    )
    return {
        "parent": statistics.median(row[0] for row in values),
        "child": statistics.median(row[1] for row in values),
        "median": statistics.median(ratios),
        "ci": [ranked[2], ranked[-3]],
        "p2": count / len(assignments),
        "ratios": ratios,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, help="also compare every clock record with the full Actions ZIP")
    args = parser.parse_args()
    independent = json.loads((HERE / "independent.json").read_text())
    with zipfile.ZipFile(HERE / "clocks.zip") as archive:
        if args.original is not None:
            with args.original.open("rb") as source:
                assert hashlib.file_digest(source, "sha256").hexdigest() == independent["sha256"]
            with zipfile.ZipFile(args.original) as original:
                assert all(original.read(name) == archive.read(name) for name in archive.namelist())
        def read(name):
            return json.loads(archive.read(PREFIX + name))

        register, hosted = read("registration.json"), read("result.json")
        order = register["order"]
        assert order == hosted["order"] == independent["order"] and order.count("PC") == order.count("CP") == 6
        assert register["primary"] == "repeat-1" and hosted["complete"]
        for name in ENDPOINTS:
            elapsed, cpu = [], []
            for pair, seq in enumerate(order, 1):
                clocks = {}
                for role in seq:
                    path = f"pair-{pair:02}/{role}/{name}/"
                    point = read(path + "point.json")
                    clock = point["cargo"]
                    assert clock["stop_ns"] - clock["start_ns"] == clock["ns"] > 0
                    report = "combined-time.txt" if name == "edit+repeat-1" else name + "/time.txt"
                    original = fields(archive.read(PREFIX + path + report).decode())
                    assert all(clock[key] == value for key, value in original.items())
                    clocks[role] = clock["ns"], original["user"] + original["system"]
                    assert point["product"]["inventory"] == point["expected"]["inventory"]
                    assert len(set(point["product"]["inventory"])) == 195
                elapsed.append([clocks[role][0] for role in "PC"])
                cpu.append([clocks[role][1] for role in "PC"])
            result = paired(elapsed, order)
            published = hosted["elapsed"][name]
            assert published["raw_PC"] == elapsed
            assert published["median_ratio"] == result["median"]
            assert published["median_CI_96.14pct"] == result["ci"]
            assert published["one_sided_balanced_sharp_2x_p"] == result["p2"]
            assert result == independent["elapsed"][name]
            assert paired(cpu, order) == independent["tree_cpu"][name]
            print(name, result["median"], result["ci"], result["p2"])
        assert not hosted["twofold_first_repeat"] and not independent["primary_met"]
        assert independent["reopened_programs"] == 96
        assert all(reference["tests"] == 195 for reference in independent["terminal_empty"].values())


if __name__ == "__main__":
    main()
