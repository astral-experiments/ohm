import json,gzip,hashlib,zipfile,sys,collections,subprocess
from pathlib import Path
from functools import lru_cache
D=Path(sys.argv[1]).resolve();z=zipfile.ZipFile(D/'worker.zip'); H=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(H));import metadata
def j(x):return json.loads(z.read(x))
def h(x):return hashlib.sha256(x).hexdigest()
@lru_cache(maxsize=2)
def table(k):return json.loads(gzip.decompress(z.read('members/'+k+'.rows.json.gz')))
def check(role,stage):return j(f'{role}/{stage}/check.json')
def external(role,s):
 return {(x[0],x[1],tuple(x[2]),x[3]):[x[4],x[5]] for x in j(f'{role}/{s}/external-products.json')}
def difference(a,b):
 return {k:[a.get(k),b.get(k)]for k in sorted(a.keys()|b.keys()) if a.get(k)!=b.get(k)}
def fmt(x):return json.dumps(x,sort_keys=True,indent=1)+'\n'
def analyze(role,s1,s2):
 pair=[check(role,s) for s in (s1,s2)];out={}
 for crate in pair[0]['metadata']:
  k1,k2=[p['metadata'][crate]['sha256'] for p in pair]
  A,B=table(k1),table(k2);rows=difference(A['rows'],B['rows']);req=difference(A['requires'],B['requires']);head=difference(A['header'],B['header'])
  out[crate]={'num':len(A['rows']),'differing_public':len(rows),'examples':list(rows.items())[:2],'requires':req,'header':head,'sha256':[k1,k2]}
 ext=[external(role,s)for s in (s1,s2)];e={repr(k):[ext[0].get(k),ext[1].get(k)] for k in sorted(ext[0].keys()|ext[1].keys()) if ext[0].get(k)!=ext[1].get(k)}
 return {'from':s1,'to':s2,'crates':out,'external_products':len(ext[0]),'different_external':e}
out={'archive_sha256':'bbad7bd93996ca2b1485456a23e2ecb19024f99b8e85117c2ac485885bc29248','roles':{}}
for role in j('worker.json')['order']:
 cases={};phases=['ordinary-buggy-cold','kernel-buggy-cold','ordinary-edited','kernel-edited','empty-edit','reverse','repair','restore-fixed']
 for tag,a,b in [('cold-observer',phases[0],phases[1]),('edit-observer',phases[2],phases[3]),('edit-clean',phases[2],'empty-edit'),('repair',phases[2],'repair'),('restored',phases[2],'restore-fixed'),('reverse',phases[0],'reverse')]:
  cases[tag]=v=analyze(role,a,b)
  concise={k:[v['crates'][k]['differing_public'],len(v['crates'][k]['requires']),list(v['crates'][k]['header'])]for k in ('ruff_linter','ruff','ty_python_semantic')}
  print(role,tag,len(v['different_external']),concise,flush=True)
 out['roles'][role]={'comparisons':cases,'edited_instructions':check(role,'ordinary-edited')['instructions'],'edited_physical':check(role,'kernel-edited')['physical'],'reverse':check(role,'reverse')['physical'],'settled':check(role,'kernel-fixed-idle2')['physical']}
(D/'semantic-diagnosis.json').write_text(fmt(out))
# Independently bind each first divergent real producer and the two consumers to native rmeta.
for role in 'PC':
 v=j(role+'/kit.json')['rustc_version'].splitlines()[0]+' (Ohm metadata 3)'
 for name in ('ruff_linter','ruff','ty_python_semantic'):
  for key in set(out['roles'][role]['comparisons']['cold-observer']['crates'][name]['sha256']):
   compressed=z.read('members/'+key+'.rmeta.zst')
   raw=subprocess.run(['zstd','-dcq'],input=compressed,stdout=subprocess.PIPE,check=True).stdout
   assert h(raw)==key and metadata.table(raw,name,v,'2024')==table(key)
(D/'decoded-first.json').write_text(fmt({'all_verified':True,'roles':2,'real_owners':['ruff_linter','ruff','ty_python_semantic'],'diagnosis':h((D/'semantic-diagnosis.json').read_bytes())}))
