from pathlib import Path
import argparse,hashlib,json,subprocess,tarfile,tomllib,re
ap=argparse.ArgumentParser();ap.add_argument('ruff',type=Path);ap.add_argument('ca',type=Path);ap.add_argument('out',type=Path);x=ap.parse_args();r=x.ruff;out=x.out;out.mkdir(exist_ok=True)
sha=lambda b:hashlib.sha256(b).hexdigest();git=lambda *a:subprocess.check_output(['git','-C',r,*a]);revs=['710c60f7135879b05f6c05a34085cd7af5c19e7f','b00f68a23cedbd3a38fc25bac63638f0f11fc3f0']
locks=[git('show',v+':Cargo.lock')for v in revs];assert locks[0]==locks[1];(out/'Cargo.lock').write_bytes(locks[0]);pack=tomllib.loads(locks[0].decode())['package']
result={'ruff':revs,'lock_blob':git('rev-parse',revs[0]+':Cargo.lock').decode().strip(),'lock_sha256':sha(locks[0]),'crates':{},'application_source':{}}
for name,v in [('get-size-derive2','0.5.1'),('attribute-derive','0.10.3'),('attribute-derive-macro','0.10.3')]:
 pkg,=[p for p in pack if p['name']==name and p['version']==v];hits=list(x.ca.glob('*/'+name+'-'+v+'.crate'))+list(x.ca.glob(name+'-'+v+'.crate'));assert hits
 f=hits[0];data=f.read_bytes();assert sha(data)==pkg['checksum'];(out/f.name).write_bytes(data)
 with tarfile.open(f,'r:gz')as z:
  source=z.extractfile(name+'-'+v+'/src/lib.rs').read();assert source;count=len(z.getnames())
 result['crates'][name]={'version':v,'crate_sha256':sha(data),'source_sha256':sha(source),'bytes':len(data),'members':count}
for rev in revs:
 paths=git('grep','-l','-w','get_size',rev,'--','*.rs').decode().splitlines();hits=[]
 for row in paths:
  _,path=row.split(':',1);b=git('cat-file','blob',row);t=b.decode()
  for m in re.finditer(r'#\s*\[\s*get_size\s*\(([^()]*)\)\s*\]',t):hits.append([path,t.count('\n',0,m.start())+1,m[1],sha(b)])
  assert not re.search(r'#\s*\[\s*cfg_attr\s*\([^\]]*\bget_size\s*\(',t)
 result['application_source'][rev]=hits
assert result['application_source'][revs[0]]==result['application_source'][revs[1]] and len(result['application_source'][revs[0]])==3
(out/'verified.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
