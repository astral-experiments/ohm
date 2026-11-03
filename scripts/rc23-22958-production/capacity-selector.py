"""Compute prospective storage admission from a complete, independently replayed stock pilot."""
import json
from pathlib import Path
import sys

GIB = 1 << 30
STAGES = {"materialize", "prerequisites", "bolt-tools", "wild", "production", "native-qa"}
PILOT = 41369516093
HEAD = "4b08157523274b9a7546fde78ce92a0e22c9c786"

def ceildiv(n, d):
    return (n + d - 1) // d

def bytes_required(initial, consumption):
    assert 0 <= consumption < initial
    reserve = 16 * GIB
    stop = 48 * GIB
    margin = max(8 * GIB, ceildiv(consumption, 10))
    return max(250, ceildiv(consumption + reserve + stop + margin, GIB)) * GIB

def decide(path):
    intake = json.loads((path/"intake.json").read_bytes())
    result = json.loads((path/"summary.json").read_bytes())
    assert (intake["head"], intake["run"], intake["attempt"]) == (HEAD, PILOT, 1)
    assert intake["eligible_sdk"] is False and result["eligible_sdk"] is False
    assert result["full_stock_recipe_and_original_qa_completed"] is True
    assert result["only_a_capacity_observation"] is True and result["sample_below_emergency_floor"] is False
    assert result["physical_reserve_bytes"] == intake["physical_reserve"] == 16 * GIB
    assert intake["raw_free_stop"] == 48 * GIB and intake["raw_free_floor"] == 32 * GIB
    assert result["actual_workspace_fs"] == intake["filesystem"]
    assert set(result["raw_free_minimum_per_command"]) == set(result["sample_verification"]) == STAGES
    assert all(row["count"] >= 1 and row["max_gap_s"] <= 2 for row in result["sample_verification"].values())
    raw = min(result["raw_free_minimum_per_command"].values())
    assert raw == result["minimum_observed_free_with_held_reserve"] and raw >= 48 * GIB
    initial = intake["initial_available"]
    # Take the larger of the independently derived and retained peak usage.
    consumption = max(initial - (raw + 16 * GIB), result["sampled_max_net_workspace_consumption"])
    required = bytes_required(initial, consumption)
    return {"pilot_initial_bytes": initial, "pilot_highwater_bytes": consumption,
            "production_admission_bytes": required, "fit_observed_machine": initial >= required,
            "eligible_as_compiler_or_performance_evidence": False}

if __name__ == "__main__":
    if sys.argv[1:] == ["--test"]:
        assert bytes_required(282 * GIB, 130 * GIB) == 250 * GIB
        assert bytes_required(282 * GIB, 190 * GIB) == 273 * GIB
        assert bytes_required(282 * GIB, 200 * GIB) == 284 * GIB
    else:
        assert len(sys.argv) == 2
        print(json.dumps(decide(Path(sys.argv[1])), sort_keys=True))
