"""Project only public identities, edges, counters, metadata and verdicts from the two originals."""
from collections import Counter
from pathlib import Path
import argparse,hashlib,json,sys,zipfile
here=Path(__file__).resolve().parent
sys.path.insert(0,str(here/'helpers'))
import reverse_graph as g
digest=lambda b:hashlib.sha256(b).hexdigest()
p=argparse.ArgumentParser();p.add_argument('first',type=Path);p.add_argument('later',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
sources=[('first',a.first,'e85366bc775a176d9818e12875c9b08d61a22f882182f9b93142b9d6c0826cd7',['normal-ruff']),('later',a.later,'4e1b2405231b9d854129809a1b5984eb96b52d6052c7fc4ef233067ed4572fcd',['observed-ruff','normal-ruff_dev'])]
members={};jenc=lambda x:(json.dumps(x,sort_keys=True,separators=(',',':'))+'\n').encode();bind={}
for label,path,hist,lanes in sources:
 with path.open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==hist
 with zipfile.ZipFile(path)as z:
  for lane in lanes:
   unique=label+'-'+lane;pre=unique+'/'
   for phase in ('initial-consumer','producer-NEW','producer-OLD','unchanged-consumer'):
    old=lane+'/'+phase;out=pre+phase
    for k in ('selected.json','stable.json','changed.json','native.json','real-compiler.json','help-0.stdout','help-1.stdout'):
     n=old+'/'+k
     if n not in z.namelist():continue
     b=z.read(n)
     if k=='real-compiler.json':
      rr=json.loads(b);b=jenc([{'crate':x['crate'],'type':x['kind'],'link_only':any(y in ('link-only','-Zlink-only')for y in x['argv']),'argv_sha256':digest(jenc(x['argv']))}for x in rr])
     members[out+'/'+k]=b
    s=json.loads(z.read(old+'/selected.json'));m='metadata/'+s['meta_sha']+'.zst';members[m]=z.read(m)
    if label=='later' and lane=='observed-ruff' and phase in ('initial-consumer','producer-OLD'):
     q=g.Graph(z,phase)
     proj={'ident':q.ident,'kind':q.kind,'edges':q.edges,'roots':q.roots,'locals':q.locals,
           'payload':{i:sorted((digest,addr,n)for (digest,addr),n in cs.items())for i,cs in q.payload.items()if cs},
           'allocation_sites':[[i,j,pc,n]for (i,j),sites in sorted(q.addrs.items())if q.kind[j]==21 for pc,n in sorted(sites.items())],
           'allocation_ids':{i:g.u(q.rows[i],8,8)for i in range(len(q.rows))if q.kind[i]==21},
           'source_files':{n:digest(z.read(old+'/'+n))for n in ('graph.bin','register.bin','payload.bin')}}
     members[out+'/topology.json']=jenc(proj)
   for phase in ('settled-original','settled-original-again','settled-after','settled-after-again'):
    n=lane+'/'+phase+'/physical-floor.json'
    if n in z.namelist():members[pre+phase+'/physical-floor.json']=z.read(n)
   bind[unique]={'original':hist,'input_lane':lane}
members['sources.json']=jenc(bind)
with zipfile.ZipFile(a.output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6)as z:
 for n,b in sorted(members.items()):
  x=zipfile.ZipInfo(n);x.compress_type=zipfile.ZIP_DEFLATED;z.writestr(x,b)
print('retained',len(members),a.output.stat().st_size,digest(a.output.read_bytes()))
