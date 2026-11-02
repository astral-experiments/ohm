"""Exact paired inference for the two cumulative production thresholds, with ties as non-successes."""
from fractions import Fraction
from math import comb
from statistics import median

def family(wall,compilers):
    rows=[]
    for name,values,threshold in (("bare_wall",wall,Fraction(2)),("sum_of_eight",compilers,Fraction(5,4))):
        assert len(values)==8 and all(type(a)is type(b)is int and a>0 and b>0 for a,b in values)
        xs=[Fraction(a,b)for a,b in values];positive=sum(x>threshold for x in xs);ties=sum(x==threshold for x in xs)
        p=Fraction(sum(comb(8,k)for k in range(positive,9)),256)
        holds=[median(xs[:4]),median(xs[4:])]
        rows.append(dict(name=name,threshold=str(threshold),raw_control_candidate=values,paired_ratios=[float(x)for x in xs],
                         median=float(median(xs)),hold_medians=[float(x)for x in holds],both_holds_above=all(x>threshold for x in holds),
                         above=positive,below=8-positive-ties,ties=ties,all_eight_above=positive==8,p=p))
    adjusted=Fraction(0)
    for i,row in enumerate(sorted(rows,key=lambda r:r['p'])):
        adjusted=min(Fraction(1),max(adjusted,(2-i)*row['p']))
        row['holm_p']=float(adjusted);row['holm_reject_at_0_05']=adjusted<=Fraction(1,20);row['p']=float(row['p'])
    return {"tests":rows,"repeatable_2x_wall":rows[0]['all_eight_above'] and rows[0]['both_holds_above'] and rows[0]['holm_reject_at_0_05'],
            "twenty_percent_sum_of_eight_rustc_instructions":rows[1]['holm_reject_at_0_05']}
