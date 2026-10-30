"""Check the inclusive clocks, reference images, native counts and balanced twofold test."""
import gzip
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
PHASES = ("edit", "repeat-1", "repeat-2")
ENDPOINTS = (*PHASES, "edit+repeat-1")
PARENT = "2035696c5316079f5b2e4373aee834839aac97e9"
CHILD = "444c0273a2e2bc0b161e988d43c882349bc2d7a6"
PRIOR = "795507e5d0bf58e49b4cbb4050fa65e1c62097ec69502b8e7655f9686b427121"


def main():
    for line in (HERE / "SHA256SUMS").read_text().splitlines():
        expected, name = line.split("  ", 1)
        assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == expected, name
    evidence = json.loads(gzip.decompress((HERE / "clocks.json.gz").read_bytes()))
    assert evidence["calibration"]["tree_CPU_calibrated"]
    assert evidence["calibration"]["retired_instruction_scope"] != "whole-tree-calibrated"
    refs = evidence["images"]
    for role in "PC":
        assert refs[role]["old"]["size"] == 194 and refs[role]["new"]["size"] == 195
        assert refs[role]["old"]["raw"] != refs[role]["new"]["raw"]
        for phase in ("edit", *PHASES[1:], "invalid", "repair"):
            row = evidence["processes"][role][phase]
            if phase == "invalid":
                assert row["exit"] == 101 and row["e2e"] is None
            else:
                assert row["e2e"] == refs[role]["new"]["raw"] and row["exit"] == 0
                assert row["e2e_link"] == (int(role == "P") if phase.startswith("repeat") else 1)
    for stage, block in evidence["stages"].items():
        registration = block["registration"]
        order = registration["order"]
        assert registration["sources"][:2] == [PARENT, CHILD] and registration["unscored_prior"] == PRIOR
        i = int(hashlib.sha256(("ty_server e2e/native v1/" + PRIOR).encode()).hexdigest(), 16) % 924
        subset = list(itertools.combinations(range(12), 6))[i]
        assert order == (["PC", "CP"] if stage == "screen" else ["PC" if j in subset else "CP" for j in range(12)])
        terminal = -1
        clocks = {key: [] for key in ENDPOINTS}
        cpus = {key: [] for key in ENDPOINTS}
        for number, pair in enumerate(block["pairs"]):
            times = {}
            cpu = {}
            for role in order[number]:
                times[role] = {}
                cpu[role] = {}
                for phase in ("cold", *PHASES):
                    r = pair[role][phase]
                    reference = refs[role]["old" if phase == "cold" else "new"]
                    assert r["image"] == reference and r["whole_image_equal"] and r["roster_equal"] and r["subject_equal"]
                    assert r["real_tests_passed"] == (1 if phase == "cold" else 2)
                    if phase == "cold":
                        continue
                    t = r["cargo"]
                    assert terminal < t["start_ns"] < t["stop_ns"]
                    terminal = t["stop_ns"]
                    assert t["ns"] == t["stop_ns"] - t["start_ns"]
                    assert abs(t["wall"] - t["ns"]/1e9) <= 0.05
                    assert [t["wall"], t["user"], t["system"]] == r["time_line"]
                    times[role][phase] = t["ns"]
                    cpu[role][phase] = t["user"] + t["system"]
                for values in (times[role], cpu[role]):
                    values["edit+repeat-1"] = values["edit"] + values["repeat-1"]
            for phase in ENDPOINTS:
                clocks[phase].append([times["P"][phase], times["C"][phase]])
                cpus[phase].append([cpu["P"][phase], cpu["C"][phase]])
        for phase, values in clocks.items():
            ratios = [a / b for a,b in values]
            full = block["checked"]["paired"][phase]
            assert [statistics.median(col)/1e9 for col in zip(*values)] == full["median_seconds"]
            assert full["paired_median"] == statistics.median(ratios) and full["ratios"] == ratios
            if stage == "confirmation":
                assert full["interval"] == [sorted(ratios)[2], sorted(ratios)[-3]]
                signed = [math.log(r/2)*(1 if o=="PC" else -1) for r,o in zip(ratios,order)]
                observed = sum(math.log(r/2) for r in ratios)/12
                exceed = sum(sum(x if j in perm else -x for j,x in enumerate(signed))/12 >= observed-1e-12
                             for perm in itertools.combinations(range(12),6))
                assert full["sharp_p"] == exceed/924
                cpu = [statistics.median(col) for col in zip(*cpus[phase])]
                print(phase, "seconds", full["median_seconds"], "paired", full["paired_median"],
                      "interval", full["interval"], "whole-tree CPU", cpu)


if __name__ == "__main__":
    main()
