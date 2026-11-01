"""Reject stale native output, wrong closed inputs and incorrect physical link topology."""

import copy
import gzip
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from worker import validate, checksum


def run():
    src = HERE / "cases.json.gz"
    assert checksum(src) == "cd5efc19c46f06f99c7d13d3b370e722d3ec7312139fcfc4307503790e197f1a"
    packet = json.loads(gzip.decompress(src.read_bytes()))
    prefix = Path(packet["prefix"])
    for name, rows in packet["rows"].items():
        validate(name, rows, prefix)
    cases = [
        ("script", "bad", "code", 0),
        ("script", "new", "tag", 17),
        ("script", "new", "elf", "0" * 64),
        ("script", "new-repeat", "writes", []),
        ("script", "unchanged", "seals", {"invented": "sealed"}),
        ("library", "unchanged", "relay", []),
        ("library", "unchanged", "driver_queries", []),
        ("library", "unchanged", "seals", {}),
        ("library", "unchanged", "seals", {"/foreign/declared-native/seal": "sealed"}),
        ("library", "forced-bad", "writes", []),
        ("startup", "empty-bad", "writes", []),
        ("startup", "forced-bad", "writes", [{"output": "reader", "startup": ["/foreign/crti.o"]}]),
        ("startup", "return", "elf", "1" * 64),
        ("startup", "bad", "provider", [0, 0, 1, 99, "?"]),
    ]
    for name, phase, key, value in cases:
        rows = copy.deepcopy(packet["rows"][name])
        rows[phase][key] = value
        try:
            validate(name, rows, prefix)
        except (KeyError, ValueError):
            continue
        raise AssertionError((name, phase, key))
    print("45 recorded ordinary visits reopened; all", len(cases), "native-input mutations refused.")


if __name__ == "__main__":
    run()
