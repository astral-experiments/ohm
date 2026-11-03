"""Reject individual changes to the actual completed six-boot observation."""

from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recompute as audit


def main():
    reports = json.loads((audit.here / "receipts.json").read_text())
    inputs = (
        [audit.open_original(item) for item in reports["admissions"]],
        [audit.open_original(item) for item in reports["measurements"]],
        audit.open_original(reports["decision"]),
        json.loads((audit.here / "protocol.json").read_text()),
        reports["run"],
    )
    audit.verify(*inputs)
    for kind in ("instruction", "repeated-boot", "compiler", "complete-elf", "storage", "roster", "randomization"):
        args = deepcopy(inputs)
        native, slots, final, protocol, run = args
        first = slots[0]
        if kind == "instruction":
            first["counts"]["option"]["P"]["new"]["instructions"] += 1
        elif kind == "repeated-boot":
            slots[1]["boot"] = first["boot"]
        elif kind == "compiler":
            first["source"]["C3b"] = first["source"]["P"]
        elif kind == "complete-elf":
            first["oracles"]["e2e"]["C2"]["repair"]["elf"] = "0" * 64
        elif kind == "storage":
            first["controls"]["option"]["C2"]["new"]["storage"]["allocated"]["allocated"] += 4096
        elif kind == "roster":
            first["native_rosters"]["e2e"]["P"]["new"]["actual_native"] = 0
        else:
            final["all_endpoint_estimates"]["option"]["new"]["joint_right_tail"][0] += 1
        try:
            audit.verify(*args)
        except AssertionError:
            continue
        raise AssertionError("accepted a corrupted recorded value in " + kind)
    print("All 108 counter payloads and the seven independent corruption checks passed.")


if __name__ == "__main__":
    main()
