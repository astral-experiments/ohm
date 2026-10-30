"""Recompute the registered inclusive clock endpoints directly from each Cargo process."""
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
from statistics import mean, median
import sys
from zipfile import ZipFile

def calculate(path, expected):
    with path.open("rb") as fp:
        assert hashlib.file_digest(fp, "sha256").hexdigest() == expected
    with ZipFile(path) as archive:
        prefix = "objc2-clock-confirmation/"
        read = lambda key: json.loads(archive.read(prefix + key))
        enrolled = read("registration.json")
        terminal = read("result.json")
        order = ["CP", "CP", "PC", "PC", "PC", "PC", "CP", "PC", "CP", "PC", "CP", "CP"]
        assert enrolled["order"] == terminal["order"] == order
        assert enrolled["primary"] == terminal.get("primary", "repeat-1") == "repeat-1"
        data = {k: [] for k in ("edit", "repeat-1", "repeat-2", "edit+repeat-1")}
        previous_stop = 0
        for i, seq in enumerate(order, 1):
            arm = {}
            for role in seq:
                each = {}
                for phase in ("edit", "repeat-1", "repeat-2"):
                    row = read(f"pair-{i:02d}/{role}/{phase}/result.json")["cargo"]
                    start, stop = row["start_ns"], row["stop_ns"]
                    assert previous_stop < start < stop and row["ns"] == stop - start
                    previous_stop = stop
                    each[phase] = stop - start
                each["edit+repeat-1"] = each["edit"] + each["repeat-1"]
                arm[role] = each
            for key in data:
                data[key].append([arm["P"][key], arm["C"][key]])
        metrics = {}
        for key, pairs in data.items():
            originals = terminal["metrics"]["monotonic_ns"][key]
            assert pairs == originals["raw_PC"]
            ratios = [p / c for p, c in pairs]
            logs = [math.log(r / 2) for r in ratios]
            relative = [x if o == "PC" else -x for x, o in zip(logs, order)]
            n = sum(mean(x if j in flip else -x for j, x in enumerate(relative)) >= mean(logs) - 1e-12
                    for flip in combinations(range(12), 6))
            ci = [sorted(ratios)[2], sorted(ratios)[9]]
            gate = ci[0] > 2 and n / 924 <= .05
            assert ci == originals["median_CI_96.14pct"] and n / 924 == originals["one_sided_balanced_sharp_2x_p"]
            metrics[key] = dict(median_parent=median(x for x, y in pairs)/1e9,
                                median_child=median(y for x, y in pairs)/1e9,
                                paired=median(ratios), ci=ci, p=n/924,
                                arms_above_two=sum(r > 2 for r in ratios), allocations=n,
                                gate=gate, pairs=pairs)
        assert metrics["repeat-1"]["gate"] == terminal["twofold_first_repeat"]
        return dict(archive=expected, clock_count=72, order=order, metrics=metrics)

if __name__ == "__main__":
    result = calculate(Path(sys.argv[1]), sys.argv[2])
    data = (json.dumps(result, sort_keys=True, indent=2)+"\n").encode()
    with Path(sys.argv[3]).open("xb") as fp:
        fp.write(data)
    print(hashlib.sha256(data).hexdigest(), {k:{n:v for n,v in m.items() if n!="pairs"} for k,m in result["metrics"].items()})
