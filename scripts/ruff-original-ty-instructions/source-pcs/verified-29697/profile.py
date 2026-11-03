from collections import Counter
import hashlib,json,subprocess,os,sys,zipfile
from pathlib import Path
here=Path(__file__).resolve().parent
tools=here.parent
sys.path.insert(0,str(tools))
from pc_raw import raw_records
from semantic_pcs import mappings
saved=json.loads((here/'kernel-identity.json').read_bytes());compressed=(here/'kernel.perf.zst').read_bytes()
assert hashlib.sha256(compressed).hexdigest()==saved['compressed']
buf=subprocess.run(['zstd','-dc'],input=compressed,check=True,capture_output=True).stdout
assert len(buf)==saved['bytes'] and hashlib.sha256(buf).hexdigest()==saved['sha256']
period,ips,types,depth,modes,skid=raw_records(buf)
target=json.loads((here/'profile-NEW-ty-ide.json').read_bytes())
assert not target['unclocked'] and period==1000003 and not any(types.get(k,0)for k in (2,5,6,13))
pid=target['pid'];maps=mappings(buf,pid);sel=Counter();locs=Counter();unmapped=0
for key,n in ips.items():
 proc,tid,ts,h,ip=key
 if proc!=pid:continue
 assert tid in target['threads'] and ts>=target['start_ns']
 if key in skid:sel['kernel-skid']+=n;continue
 mm=[v for v in maps if v['base']<=ip<v['base']+v['length']]
 if len(mm)!=1:unmapped+=n;sel['unbound']+=n;continue
 m=mm[0];sel[m['name']]+=n;locs[(m['name'],m['off']+ip-m['base'])]+=n
n=sum(sel.values());assert n>10000 and abs(n*period/target['instructions']-1)<.03
pack={'period':period,'selected_samples':n,'selected_instructions':target['instructions'],'raw_instructions_all_samples':types[9],'bins':dict(sel),'maps':maps,'offsets':[[name,off,k] for (name,off),k in locs.items()]}
assert n==23878 and target['instructions']==23906045449 and len(target['threads'])==184
assert sum(v for k,v in sel.items()if 'libLLVM.so.' in k)==18020
print(json.dumps({'selected_samples':n,'selected_positive_instructions':target['instructions'],'all_samples':types[9],'images':dict(sel)},sort_keys=True))
