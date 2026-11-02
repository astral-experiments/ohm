"""Prespecified interval rules for this new sixteen-pair panel only."""
from fractions import Fraction
from statistics import median
import hashlib,json
from pathlib import Path
P=Path(__file__).parent
SHA='3936b8c5031523f30435b1c16a21cf86249b94710ddaa6aaa36916d61892c675'
def plan():
    raw=(P/'registration.json').read_bytes();assert hashlib.sha256(raw).hexdigest()==SHA;v=json.loads(raw);assert hashlib.sha256((P/'decision.json').read_bytes()).hexdigest()==v['prior_decision_file_sha256'];assert len(v['order'])==16 and v['blocks']==[i//4 for i in range(16)];return v

def enroll(seen,receipt,pair,role):
    import re
    if set(receipt)!={'count','hold','role','sha256'}or type(pair)is not int or pair not in range(16)or receipt['hold']!=pair or receipt['role']!=role or type(receipt['count'])is not int or receipt['count']<=0 or not re.fullmatch('[a-f0-9]{64}',receipt['sha256'])or receipt['sha256']in seen:raise ValueError('wrong, duplicate, or empty independent history')
    seen.add(receipt['sha256']);return receipt['sha256']

def score(rows):
    assert len(rows)==16 and all(len(x)==2 and all(type(t)is int and t>0 for t in x)for x in rows)
    ratios=[Fraction(c,p)for p,c in rows];halves=[median(ratios[i:i+4])for i in range(0,16,4)];under=sum(5*c<6*p for p,c in rows);bad=sum(c>=2*p for p,c in rows)
    def tails(reverse):
        got=[(c,p)if reverse else(p,c)for p,c in rows];return {'over_1_5':[i for i,(p,c)in enumerate(got)if 2*c>3*p],'at_least_1_5':[i for i,(p,c)in enumerate(got)if 2*c>=3*p],'over_2':[i for i,(p,c)in enumerate(got)if c>2*p],'at_least_2':[i for i,(p,c)in enumerate(got)if c>=2*p]}
    return {'raw_parent_candidate_ns':rows,'candidate_over_parent':[str(x)for x in ratios],'paired_median_C_over_P':str(median(ratios)),'block_medians_C_over_P':[str(x)for x in halves],'strictly_below_1_20':under,'candidate_slower':tails(False),'parent_slower':tails(True),'pass':all(x<Fraction(21,20)for x in halves)and under>=15 and bad==0}
