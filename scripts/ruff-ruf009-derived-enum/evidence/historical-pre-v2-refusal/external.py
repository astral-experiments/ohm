import sys
import pathlib,struct,hashlib,json,collections,zipfile,subprocess,zlib,gzip
from pathlib import Path
D=Path(sys.argv[1]).resolve();z=zipfile.ZipFile(D/'worker.zip');B=D/'external-bodies';B.mkdir(exist_ok=True)
sha=lambda b:hashlib.sha256(b).hexdigest()
def data(r,s):return json.loads(z.read(f'{r}/{s}/external-products.json'))
def obj(k):
 out=B/k
 if not out.exists():
  raw=subprocess.run(['zstd','-dcq'],input=z.read('members/'+k+'.external.zst'),stdout=subprocess.PIPE,check=True).stdout;assert sha(raw)==k;out.write_bytes(raw)
 return out.read_bytes()
def elf(b):
 assert b[:6]==b'\x7fELF\x02\x01';eh=struct.unpack_from('<16sHHIQQQIHHHHHH',b)
 sections=[struct.unpack_from('<IIQQQQIIQQ',b,eh[6]+i*eh[11])for i in range(eh[12])];a=sections[eh[13]];names=b[a[4]:a[4]+a[5]]
 out={};heads=[]
 for s in sections:
  at=s[0];nm=names[at:names.index(0,at)].decode();raw=b[s[4]:s[4]+s[5]] if s[1]!=8 else b'';assert nm not in out
  out[nm]=(s,raw);heads.append(s)
 ph=[struct.unpack_from('<IIQQQQQQ',b,eh[5]+i*eh[9]) for i in range(eh[10])]
 return out,heads,ph,eh
out={}
for r in 'PC':
 out[r]={}
 for aa,bb in [('ordinary-buggy-cold','kernel-buggy-cold'),('ordinary-edited','empty-edit')]:
  a,b=data(r,aa),data(r,bb);pair={}
  for name in ('get_size_derive2','get_size2'):
   xa,=[q for q in a if q[1]==name];xb,=[q for q in b if q[1]==name];x,y=obj(xa[-1]),obj(xb[-1]); rec={'bytes':[len(x),len(y)],'sha256':[sha(x),sha(y)],'same_len_differing_bytes':sum(a!=b for a,b in zip(x,y)) if len(x)==len(y) else None}
   if name=='get_size_derive2':
    A,As,Ap,Ah=elf(x);K,Ks,Kp,Kh=elf(y);assert set(A)==set(K)
    rec['elf_headers_equal']=Ah==Kh;rec['program_headers_equal']=Ap==Kp;rec['section_headers_equal']=As==Ks;rec['sections']={}
    for n in A:
     t,u=A[n],K[n]
     if t==u:continue
     rec['sections'][n]={'flags':t[0][2],'size':[len(t[1]),len(u[1])],'bytes_differ':sum(a!=b for a,b in zip(t[1],u[1])) if len(t[1])==len(u[1]) else None,'sha256':[sha(t[1]),sha(u[1])]}
    rec['pt_load']=[{'flags':p[1],'size':p[5],'sha256':[sha(x[p[2]:p[2]+p[5]]),sha(y[q[2]:q[2]+q[5]])]} for p,q in zip(Ap,Kp)if p[0]==q[0]==1]
    rec['build_id']=[subprocess.check_output(['readelf','-n',str(B/v)],text=True).split('Build ID: ')[1].splitlines()[0]for v in rec['sha256']]
    print(r,bb,'diffbytes',rec['same_len_differing_bytes'],'sections',[(s,t['bytes_differ'])for s,t in rec['sections'].items()],'PT',[(p['flags'],p['sha256'][0]==p['sha256'][1])for p in rec['pt_load']],flush=True)
   pair[name]=rec
  out[r][aa+'/'+bb]=pair
(D/'external-section-receipt.json').write_text(json.dumps(out,indent=1,sort_keys=True)+'\n')
