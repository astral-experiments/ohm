"""Bound prospective work separately on the two physically authenticated signed cohorts."""

from pathlib import Path
import json, sys

p = Path(__file__).resolve().parent
s = json.loads((p / "two-signed-hardware.json").read_bytes())


def coverage(accepted):
    out = []
    for r in s:
        t = r["whole"]
        w = r["verified_role_costs"]
        assert not set(accepted) - w.keys()
        observed = sum(w[k] for k in accepted)
        best = min(t, observed + max(0, r["outer_minus_all_epochs"]))
        out.append(
            {
                "signed_run": r["run"],
                "eligible_roles": len(accepted),
                "whole": t,
                "observed_native_for_roles": observed,
                "outer_minus_all_epochs": r["outer_minus_all_epochs"],
                "maximum_if_whole_unallocated_residue_were_eligible": best,
                "observed_native_reaches_half": 2 * observed >= t,
                "residual_inclusive_reaches_half": 2 * best >= t,
            }
        )
    return out


if __name__ == "__main__":
    reg = json.loads(Path(sys.argv[1]).read_bytes())
    assert reg["complete"]
    print(
        json.dumps(
            {k: coverage(v["strict_equal_roles"]) for k, v in reg["decisions"].items()},
            indent=2,
            sort_keys=True,
        )
    )
