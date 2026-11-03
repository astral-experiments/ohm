import sys
import json,struct,subprocess,collections,hashlib
from pathlib import Path
D=Path(sys.argv[1]).resolve();B=D/'external-bodies';x=json.loads((D/'external-section-receipt.json').read_bytes());out={}
def tabs(b):
 h=struct.unpack_from('<16sHHIQQQIHHHHHH',b);ss=[struct.unpack_from('<IIQQQQIIQQ',b,h[6]+j*h[11]) for j in range(h[12])];names=b[ss[h[13]][4]:ss[h[13]][4]+ss[h[13]][5]]
 def name(pool,i):return pool[i:pool.index(0,i)].decode(errors='backslashreplace')
 section={name(names,s[0]):s for s in ss};sym=section['.symtab'];ns=ss[sym[6]];strings=b[ns[4]:ns[4]+ns[5]];syms=[]
 for p in range(sym[4],sym[4]+sym[5],sym[9]):
  n,info,vis,ind,addr,size=struct.unpack_from('<IBBHQQ',b,p)
  if info&15==2 and 0<ind<len(ss) and size:syms.append((name(strings,n),addr,size))
 return section['.text'],syms
for r in 'PC':
 arr=[]
 for tag,w in x[r].items():
  key=w['get_size_derive2']['sha256'];a,b=[(B/k).read_bytes()for k in key];ta,sa=tabs(a);tb,sb=tabs(b);assert ta==tb and sa==sb
  dbg={}
  for name,addr,num in sa:
   delta=addr-ta[3]+ta[4];left=a[delta:delta+num];right=b[delta:delta+num];c=sum(p!=q for p,q in zip(left,right))
   if c:dbg[name]=[addr,num,c]
  names=list(dbg)
  dem=subprocess.run(['c++filt','-s','rust'],input='\n'.join(names)+'\n',text=True,stdout=subprocess.PIPE,check=True).stdout.splitlines()
  ordered=sorted(zip(dem,names),key=lambda z:-dbg[z[1]][2]);arr.append([tag,[{'symbol':n,'raw':o,'addr_size_unequal':dbg[o]} for n,o in ordered]])
  print(r,tag,[(n[:80],dbg[o][2])for n,o in ordered[:4]],flush=True)
 out[r]=arr
(D/'external-macro-symbols.json').write_text(json.dumps(out,indent=1)+'\n')
