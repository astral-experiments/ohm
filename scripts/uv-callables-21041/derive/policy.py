"""Preregister the terminal compiler as the sole confirmatory endpoint."""
from fractions import Fraction
from math import comb
from statistics import median

def assess(metrics):
    endpoint="uv_client"
    observed=metrics[endpoint]["raw_control_candidate"]
    if len(observed)!=8 or any(type(v)is not int or v<=0 for pair in observed for v in pair) or any(len(p)!=2 for p in observed):
        raise ValueError("requires both positive original integer counts in all eight uv_client pairs")
    ratios=[Fraction(b,a) for a,b in observed]
    limit=Fraction(4,5)
    wins=sum(v<limit for v in ratios)
    prob=Fraction(sum(comb(8,i) for i in range(wins,9)),2**8)
    holds=[median(ratios[:4]),median(ratios[4:])]
    return {"primary":endpoint,"strict_candidate_over_control_below":float(limit),"raw_candidate_over_control":[float(x)for x in ratios],
            "wins":wins,"one_sided_exact_sign_p_ties_counted_against":float(prob),"two_hold_median_ratios":list(map(float,holds)),
            "qualified":all(v<limit for v in holds) and prob<=Fraction(1,20),
            "secondary":"eight real compiler PIDs and their sum, inherited whole Cargo and separate native blocking wall"}
