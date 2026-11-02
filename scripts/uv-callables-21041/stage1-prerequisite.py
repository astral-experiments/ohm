"""Reject a build unless its independently hashed earlier native trial clears the registered threshold."""
from fractions import Fraction
from hashlib import sha256
from math import comb
from pathlib import Path
from statistics import median
import json,re,sys
REG='4ee4df862fa133649f49f07a92ed4ba6279f9b96a95f78751a35b68dc3da0df8'
def verify(q):
    assert q['registration_sha256']==REG and q['workflow']=={'run':41412729838,'job':125169398989,'head':'b36f8a39c3f58c9900f73407cf54120443e98e9a','conclusion':'success','attempt':1}
    assert q['boot']=='b48533ba-18c2-433d-a56e-5d7d03110bab' and q['calibration_sha256']=='6d5e1282d97ced84548e6ff4fe8ebf32243e23f679798109d49915124a9121e8'
    assert q['native_compilers']==['f22825348d834ad9a8ef3934647181fb69f778ae','b9b3f6bba90145e25eb3b76864cfd0b5f4cbdc1f']
    assert q['selector']=='uv_metadata' and q['event']=='instructions:u threads of actual rustc' and q['holds']==[0]*4+[1]*4
    assert isinstance(q['result']['artifact'],int)and q['result']['artifact']!=13125969207 and q['result']['bytes']>1<<20
    assert all(re.fullmatch('[0-9a-f]{64}',k)for k in (q['result']['sha256'],q['independent_sha256'],*q['original_process_records']))
    rows=q['raw_control_candidate'];assert len(rows)==8 and len(set(q['original_process_records']))==16 and all(len(pair)==2 and all(type(n)is int and n>0 for n in pair)for pair in rows)
    ratios=[Fraction(candidate,control)for control,candidate in rows];count=sum(r< Fraction(4,5)for r in ratios)
    probability=Fraction(sum(comb(8,k)for k in range(count,9)),256)
    assert probability<=Fraction(1,20) and median(ratios[:4])<Fraction(4,5) and median(ratios[4:])<Fraction(4,5)
    return count,probability
def main(p):
    here=Path(__file__).resolve().parent;cfg=json.loads((here/'domain-source.json').read_bytes());raw=p.read_bytes()
    assert sha256(raw).hexdigest()==cfg['stage1_qualification_sha256'];count,pvalue=verify(json.loads(raw))
    print('Verified prior uv_metadata native threshold',count,'of 8',float(pvalue))
if __name__=='__main__':main(Path(sys.argv[1]))
