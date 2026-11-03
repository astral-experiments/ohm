"""Print a readable report from the fully reverified, six-block actual hardware evidence."""

import json
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recompute as audit


def run():
    here = Path(__file__).resolve().parent
    receipt = json.loads((here / "receipts.json").read_bytes())
    native = [audit.open_original(o) for o in receipt["admissions"]]
    observations = [audit.open_original(o) for o in receipt["measurements"]]
    final = audit.open_original(receipt["decision"])
    protocol = json.loads((here / "protocol.json").read_bytes())
    data = audit.verify(native, observations, final, protocol, receipt["run"])
    print(
        "| Real workflow and phase | #337 (B) | C2 (B) | C3b (B) | #337 to C2 | #337 to C3b | C2 to C3b |"
    )
    print("|---|---:|---:|---:|---:|---:|---:|")
    for suite, name in (("option", "Ruff #28106"), ("e2e", "ty_server e2e #27836")):
        for phase, description in (("old", "cold"), ("new", "edit"), ("unchanged", "unchanged")):
            z = data[suite][phase]
            values = [f'{median(r[s] for r in z["measurements"])/1e9:.3f}' for s in audit.roles]
            for pair in ("P_C2", "P_C3b", "C2_C3b"):
                c = z["comparisons"][pair]
                low, high = c["median_limits_percent"]
                values.append(f'{c["savings_percent"]:+.3f}% [{low:+.3f}, {high:+.3f}]')
            print("| " + " | ".join([name + " " + description, *values]) + " |")
    print(
        "\nMedian absolute whole target plus shared allocated bytes, and largest individual descendant RSS (KiB), across the six actual boots.\n"
    )
    print(
        "| Workflow and phase | #337 bytes | C2 bytes | C3b bytes | #337 KiB | C2 KiB | C3b KiB |"
    )
    print("|---|---:|---:|---:|---:|---:|---:|")
    for suite, data_by_phase in data.items():
        for phase, z in data_by_phase.items():
            x = [
                f"{median(o[s] for o in z[col]):,.0f}"
                for col in ("physical_allocated", "maxrss_kib")
                for s in audit.roles
            ]
            print("| " + " | ".join([suite + " " + phase, *x]) + " |")
    primary = data["option"]["new"]
    print(
        "\nSix separately booted, complete three-role blocks. Exact schedule counts for the primary edit:"
    )
    print("Global upper tail:", *primary["joint_right_tail"], sep=" ")
    for pair, q in primary["comparisons"].items():
        print(
            pair,
            "favorable boots",
            q["favorable"],
            "/ 6; every >10%",
            q["every_gt_10_percent"],
            "; every >2x",
            q["every_gt_2x"],
            "; exact conditional upper tail",
            q["conditional_tail"],
        )
    print("Original, separate two-pair twofold screen:", final["old_C2_two_pair_2x_screen"])


if __name__ == "__main__":
    run()
