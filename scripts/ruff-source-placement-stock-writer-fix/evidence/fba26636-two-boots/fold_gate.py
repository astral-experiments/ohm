"""Evaluate the separate, prespecified #340 project decision with exact integer thresholds."""

from pathlib import Path
from hashlib import sha256
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_score import results


def evaluate(path, condition):
    assert sha256(condition.read_bytes()).hexdigest() == "1dd29b0ba93c25ed533f859b392803d4cbc75acdb28742e165b63d9432d0a087"
    spec = json.loads(condition.read_bytes())
    data = json.loads(path.read_bytes())
    assert spec["run"] == data["run"] and spec["qa"] == data["qa"]
    assert data["sources"]["Stock4"] == spec["candidate"]
    cells = {(suite, phase, boot): (cols[0]["instructions"], cols[2]["instructions"])
             for boot, suite, phase, cols in results(path)}
    compared = {}
    for suite, phase in (("option", "new"), ("option", "old"), ("e2e", "new"), ("e2e", "old")):
        pairs = [cells[suite, phase, i] for i in (1, 2)]
        compared[suite + "/" + phase] = {
            "P_and_corrected": pairs,
            "candidate_uses_at_least_20pct_fewer_on_both": all(y * 100 <= x * 80 for x, y in pairs),
            "candidate_uses_over_1pct_more_on_both": all(y * 100 > x * 101 for x, y in pairs),
        }
    rejected = [k for k, v in compared.items() if k != "option/new" and v["candidate_uses_over_1pct_more_on_both"]]
    edit = compared["option/new"]["candidate_uses_at_least_20pct_fewer_on_both"]
    return dict(candidate=spec["candidate"], run=spec["run"], cases=compared,
                settings_edit_passes=edit, heldout_or_cold_veto=rejected,
                recommended_next_step=("six_confirmation_hosts" if edit and not rejected else "withhold_from_340"))


if __name__ == "__main__":
    out = evaluate(Path(sys.argv[1]), Path(sys.argv[2]))
    print(json.dumps(out, indent=2, sort_keys=True))
