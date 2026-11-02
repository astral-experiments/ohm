"""Apply the preregistered two tests to the six independently received pairs."""
import itertools
import json
import math
from pathlib import Path
import statistics
import sys

import native

PLAN = Path(__file__).with_name("replication.json")


def assess(pairs):
    pairs = sorted(pairs, key=lambda r: r["block"])
    assert [r["block"] for r in pairs] == list(range(1, 7))
    orders = json.loads(PLAN.read_bytes())["orders"]
    assert ["".join(r["order"]) for r in pairs] == orders and {r["plan"] for r in pairs} == {native.sha(PLAN)}
    assert len({r["entry"]["boot"] for r in pairs}) == 6
    for field in ("qa", "run", "plan"):
        assert len({r["entry"][field] for r in pairs}) == 1
    result, contrasts = [], []
    for r, order in zip(pairs, orders, strict=True):
        p, c = (r["roles"][s]["instructions"] for s in "PC")
        for role in "PC":
            sample = r["roles"][role]; count = sample["pmu"]
            assert count["instructions"] == sample["instructions"] > 0
            assert count["enabled"] == count["running"] > 0 and count["status"] == 0
            assert sample["edit_admissions"] == (63 if role == "C" else 0)
        contrasts.append(math.log(p/c) if order == "PC" else math.log(c/p))
        result.append({"block":r["block"], "order":order, "P":p, "C":c, "reduction":1-c/p})
    n = len(result); deltas = [r["reduction"] for r in result]
    assert all(x != 0 for x in deltas), "a zero reduction requires separate sign-test handling"
    small = min(sum(x > 0 for x in deltas), sum(x < 0 for x in deltas))
    p_sign = min(1, 2*sum(math.comb(n, j) for j in range(small+1))/2**n)
    received = sum(math.log(r["P"]/r["C"]) for r in result)/n
    possible = [sum(y if i in plus else -y for i, y in enumerate(contrasts))/n
                for plus in itertools.combinations(range(n), 3)]
    assert len(possible) == 20
    p_order = sum(t >= received-1e-14 for t in possible)/len(possible)
    return {"pairs":result, "median_reduction":statistics.median(deltas), "median_interval":[min(deltas),max(deltas)],
            "interval_coverage":1-2/2**n, "sign_p_two_sided":p_sign, "balanced_randomization_p_one_sided":p_order,
            "passed":min(deltas) >= 0.05 and p_sign <= 0.05 and p_order <= 0.05}


if __name__ == "__main__":
    if not __debug__ or len(sys.argv) != 7:
        raise SystemExit("usage: assess.py PAIR1 PAIR2 PAIR3 PAIR4 PAIR5 PAIR6")
    print(json.dumps(assess([json.loads(Path(p).read_bytes()) for p in sys.argv[1:]]), indent=2))
