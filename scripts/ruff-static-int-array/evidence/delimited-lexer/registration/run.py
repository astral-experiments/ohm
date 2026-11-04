from pathlib import Path
from collections import Counter
import hashlib,json,os,subprocess as sp,sys
d=Path(__file__).resolve().parent;role=sys.argv[1];sdk=Path(sys.argv[2]).resolve();assert role in ('c8','c9')
def h(b):return hashlib.sha256(b).hexdigest()
live=d/'live';live.mkdir(exist_ok=True);p=d/role;p.mkdir();real='eda9434eda0b4f8519fc2257867ab7c7dd4b59fd'if role=='c8'else'573b92c4c0d6c941b20d992465581d21a3494a3e'
env={k:os.environ[k]for k in ('PATH','HOME','LANG','TZ','USER')if k in os.environ};env['RUSTUP_HOME']=str(sdk);env['OHM_TEST_LEXER_FILE']=str(live/'observed')
rv=sp.check_output(['rustc','+ohm','-vV'],cwd=live,env=env);assert real.encode()in rv;(p/'rustc').write_bytes(rv)
def call(cmd):return sp.run(['rustc','+ohm',*cmd],env=env,cwd=live,capture_output=True)
out=call(['--edition=2024','--crate-type=proc-macro','--crate-name=tokenlens','../lens.rs','-o','libtokenlens.so']);assert out.returncode==0,(out.returncode,out.stderr)
raw=(d/'cases.json').read_bytes();cases=json.loads(raw);print(role,len(cases),h(raw),flush=True)
outputs={};errors=0
for name,case in sorted(cases.items()):
 source=bytes.fromhex(case['source']);assert h(source)==case['sha256'];(live/'input.rs').write_bytes(source)
 observed=live/'observed';observed.unlink(missing_ok=True)
 out=call(['--edition='+case['edition'],'--crate-type=lib','--crate-name=source','--error-format=json','--emit=metadata','--extern','tokenlens=libtokenlens.so','input.rs','-o','check.rmeta'])
 off=p/name;off.mkdir();(off/'stderr').write_bytes(out.stderr);(off/'stdout').write_bytes(out.stdout);body=observed.read_bytes()if observed.is_file()else b'';(off/'tokens').write_bytes(body)
 actual=out.returncode;assert actual in(0,1),(name,actual,out.stderr[-500:])
 for line in out.stderr.splitlines():json.loads(line)
 errors+=bool(actual)
 if case['kind']!='classify':
  assert (actual==0)==(case['kind']=='required-success'),(name,actual,out.stderr[:1800])
 if name.startswith('balanced-'):assert body and body.count(b'\n')>1500 and actual==0
 record=dict(source=case['sha256'],status=actual,stderr=h(out.stderr),stdout=h(out.stdout),tokens=h(body),rows=body.count(b'\n'))
 outputs[name]=record
result={'case_set':h(raw),'compiler':real,'errors':errors,'successes':len(cases)-errors,'cases':outputs}
(p/'receipt.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
if role=='c9':
 prev=json.loads((d/'c8/receipt.json').read_bytes());assert result['case_set']==prev['case_set']
 for name,v in outputs.items():
  assert v==prev['cases'][name],(name,v,prev['cases'][name])
  for n in ['stderr','stdout','tokens']:assert(p/name/n).read_bytes()==(d/'c8'/name/n).read_bytes(),(name,n)
print(role,'errors',errors,'successes',len(cases)-errors,'token records',sum(v['rows']for v in outputs.values()),flush=True)
