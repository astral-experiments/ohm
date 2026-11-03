"""Source-owner lane trial on the genuine cached MonoItems. No estimates for shared inline DAGs."""
import argparse,collections,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from mono_rows import Decoder,read,check,leb
LOCAL='f106ef863df77057'
class Found(Exception):pass
class Walk(Decoder):
    def visit_kind(self,k):
        if k not in(13,17,18,19,20):return
        d=self.b[self.p+1:self.p+17].hex()
        if d.startswith(LOCAL):raise Found(d)
    def ty(self):
        k=self.b[self.p]
        if k>=128:
            off=self.u()-128;end=self.p;check(0<=off<end,'forward type shorthand');self.p=off
            try:self.ty()
            finally:self.p=end
        else:
            self.visit_kind(k);super().ty()
def resolve(b,x):
    n,defkind,sk,did,inline,link,vis,w,st,en=x
    if did.startswith(LOCAL)or n!=0:return did
    if defkind!=0:return None
    d=Walk(b,st+18)
    try:d.seq(d.arg)
    except Found as hit:return hit.args[0]
    except (ValueError,IndexError,RecursionError)as e:return None
    check(d.p<=en-4,'invalid item ends');return did
def lanes(raw,t):
    rows=read(raw,t);out=[]
    for x in rows:
        if x[4]:continue
        owner=resolve(raw,x);lane=int.from_bytes(bytes.fromhex(owner)[8:],'little')%4 if owner else None
        out.append(dict(outer=x[3],source=owner,lane=lane,MIR=x[7]))
    return out
def main(d):
    t=json.loads((d/'partition-ordinary-exact.json').read_bytes());out={}
    for name in t['old']['rows']:
        if not name.startswith(('35bor','cdh33')):continue
        res={};hist={}
        for st in('old','edit'):
            b=(d/f'partition-{st}-query-cache.bin').read_bytes();values=lanes(b,t[st]['rows'][name]);count=collections.Counter((x['outer'],x['source'],x['MIR'])for x in values);hist[st]=count
            res[st]={'values':values,'lane_counts':[sum(x['lane']==k for x in values)for k in (0,1,2,3,None)],'lane_MIR':[sum(x['MIR']for x in values if x['lane']==k)for k in (0,1,2,3,None)]}
        add=list((hist['edit']-hist['old']).elements());remove=list((hist['old']-hist['edit']).elements());res['root_signature_additions']=add;res['root_signature_removals']=remove;out[name]=res
    return out
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('root',type=Path);a.add_argument('--output',type=Path,required=True);q=a.parse_args();v=main(q.root);q.output.write_text(json.dumps(v,sort_keys=True,indent=1)+'\n')
    for n,x in v.items():print(n,len(x['root_signature_additions']),len(x['root_signature_removals']),x['old']['lane_MIR'],x['edit']['lane_MIR'],x['old']['lane_counts'],x['root_signature_additions'][:12])
