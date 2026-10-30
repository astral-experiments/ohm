"""Replay the twelve observed returns, or reopen the 24 original Callgrind profiles."""

import argparse
import json
from pathlib import Path
import re
import sys

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from read_counters import HEAD, ORDINARY, RETURNS, verify

INSTRUMENTED = "e8b5cf57d5879b7c688206d1a16e89b471ae5f6dd5d11b375cd6d1473bb92a81"


def summarize(data):
    assert (data["head"], data["ordinary"], data["instrumented"]) == (
        HEAD,
        ORDINARY,
        INSTRUMENTED,
    )
    assert len(data["mirrors"]) == 2
    fingerprints = set()
    results = []
    for i, run in enumerate(data["mirrors"]):
        assert set(run) == set(RETURNS)
        for phase in RETURNS:
            total = {}
            assert set(run[phase]) == {"Off", "Full", "Packed"}
            for arm, row in run[phase].items():
                procs = row["rustcs"]
                assert set(procs) == {"ruff_python_ast", "ruff_python_parser"}
                for job in procs.values():
                    assert job["Ir"] > 0
                    for field in ("argv", "log", "profile"):
                        assert re.fullmatch("[0-9a-f]{64}", job[field])
                    assert job["profile"] not in fingerprints
                    fingerprints.add(job["profile"])
                total[arm] = sum(p["Ir"] for p in procs.values())
                assert total[arm] == row["total"]
            default = total["Off"] / total["Packed"]
            current = total["Full"] / total["Packed"]
            assert default == data["Off_over_Packed"][phase][i]
            assert current == data["Full_over_Packed"][phase][i]
            results.append(
                {
                    "order": i + 1,
                    "phase": phase,
                    "two_rustcs_Ir": total,
                    "default_over_packed": default,
                    "packed_instructions_percent_over_uncompressed": 100
                    * (1 / current - 1),
                }
            )
    assert len(fingerprints) == 24
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--raw", nargs=2, type=Path, metavar=("ORDINARY_ZIP", "COUNTER_ZIP")
    )
    args = parser.parse_args()
    data = json.loads((BASE / "instruction-profiles.json").read_bytes())
    if args.raw:
        assert verify(*args.raw, INSTRUMENTED) == data
    print(json.dumps(summarize(data), indent=2))
