"""Map the differing allocated bytes of the independently compiled real macros to exact ELF symbols."""
import hashlib,json,struct,sys,subprocess
from pathlib import Path
def parse(b):
 e=struct.unpack_from('<16sHHIQQQIHHHHHH',b);assert e[:3][0][:6]==b'\x7fELF\x02\x01' and e[2]==62
 secs=[struct.unpack_from('<IIQQQQIIQQ',b,e[6]+i*64)for i in range(e[12])];st=secs[e[13]]
 def sz(i,v):start=secs[i][4]+v;return b[start:b.index(b'\0',start)].decode()
 named={sz(e[13],s[0]):(i,s)for i,s in enumerate(secs)};sym=[]
 t=named['.symtab'][1]
 for k in range(t[4],t[4]+t[5],t[9]):
  name,inf,other,section,addr,n=struct.unpack_from('<IBBHQQ',b,k)
  if section<len(secs) and addr and n and inf&15 in (1,2):sym.append((section,addr,addr+n,sz(t[6],name),inf&15))
 return named,sym
def main(d):
 fs=sorted(d.glob('*.so'));assert len(fs)==5
 base=fs[0].read_bytes();src,syms=parse(base);result={}
 for f in fs:
  b=f.read_bytes();assert hashlib.sha256(b).hexdigest()==f.stem and len(b)==len(base)
  oth,nsyms=parse(b);assert src==oth
  by_section={};owners={}
  for n,(i,s) in src.items():
   if s[1]==8:continue
   start=s[4];av=s[3];off=[k for k,(a,c)in enumerate(zip(base[start:start+s[5]],b[start:start+s[5]]))if a!=c]
   if not off:continue
   by_section[n]=len(off)
   if n=='.text':
    for k in off:
     owners_at=sorted((a,z,name)for section,a,z,name,typ in syms if section==i and a<=av+k<z)
     candidates=sorted({name for _,_,name in owners_at})
     named='|'.join(candidates);owners[named]=owners.get(named,0)+1
  decoded={k:subprocess.check_output(['c++filt','-s','rust',k],text=True).strip()for k in owners}
  result[f.stem]={'changed_section_bytes':by_section,'changed_text_owners':{decoded[k]:v for k,v in owners.items()},'total':sum(by_section.values())}
 return result
if __name__=='__main__':
 obj=main(Path(sys.argv[1]));Path(sys.argv[2]).write_text(json.dumps(obj,sort_keys=True,indent=2)+'\n')
