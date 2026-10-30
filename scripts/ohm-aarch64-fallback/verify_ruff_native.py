"""Check each physical fixed-Cargo Ruff admission, independent reference output and job identity."""
from hashlib import sha256
import json,runpy,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import frontend
ORIG=HERE.parent/'ohm-aarch64-confirm'
s=runpy.run_path(str(ORIG/'reopen.py'))
H=lambda b:sha256(b).hexdigest()
key=lambda v:H(json.dumps(v,sort_keys=True,separators=(',',':')).encode())
def verify(path, expected_sources=None, expected_drivers=None, cargo_sha='869a24e83ff84cca6e9d6cb35eb62f149aa48555cf8bb7ee9b94d44ad90d2914'):
 expected_sources=s['source'] if expected_sources is None else expected_sources
 expected_drivers=s['drivers'] if expected_drivers is None else expected_drivers
 a=s['Study'](path)
 try:
  phases=s['subject']['lib']['PHASES'];env=a.J('ruff-native-eligibility.json');select=runpy.run_path(str(ORIG/'verify_transitions.py'))['verify'](a.z)
  assert env['sources']==expected_sources and env['drivers']==expected_drivers and a.J('cargo-substitution.json')['to'][0]==env['cargo']==cargo_sha
  assert not any('/profiles/cg.' in p or p.endswith('/counter-unavailable.json') for p in a.all)
  assert set(env['roles'])==set('ANM') and env['all_nine']==H(a.get('all-nine-actual-transitions.json'))
  reference=env['roles']['A'];globals_=a.native.__globals__
  globals_['OLD'],globals_['NEW'],globals_['INV']=reference['old'],reference['new'],reference['units']
  assert reference['old']!=reference['new']
  details={};actual={}
  for role in 'ANM':
   rr={};lab='ruff-native-'+role
   results=a.J(lab+'/complete.json');bind=env['roles'][role]
   for k in ('units','old','new','old_objects','new_objects','old_value','new_value'):assert bind[k]==reference[k]
   assert H(a.get(lab+'/complete.json'))==bind['native_terminal'] and results['measured'] is None
   for phase in phases:
    p=lab+'/'+phase
    kind='invalid' if phase=='invalid' else ('old' if phase=='old-empty' else 'edited')
    x=a.native(lab,phase,kind);native=a.J(p+'/native.json')
    physical=s['NATIVE'](a.z,p,native);rr[phase]={'code':x['code'],'typed':x['typed'],'counts':physical,'rustcs':x['rustc'],'reader':x.get('reader'),'archive':x.get('raw_archive')}
    if phase in ('edit','unchanged-1','unchanged-2'):
     want=s['hard'][role]|({'ruff_python_ast'} if phase=='edit' else set())
     assert set(x['rustc'])==want and len(want)==len(x['rustc']) and not x['links'] and not x['probes'] and set(physical)<={'cargo','rustcs','rustup-dispatch'}
     marks=x['markers']
     assert marks==bind['native'][phase]['marker'] and all(marks[k]==[k in s['hard'][role],k not in s['hard'][role]] for k in marks)
   first=a.J(lab+'/edit/native.json');ast,=[r for r in first['rustcs'] if r['crate']=='ruff_python_ast'];cargo,=first['cargo'];state=env['roles'][role]['actual_env']
   assert a.J(lab+'/edit/real-cargo-and-AST-environment.json')==state
   own=a.J('all-named-start-identities.json')[role]
   for r,v,exe in ((ast,state['ast'],'rustc'),(cargo,state['cargo'],'cargo')):
    assert r['pid']==v['pid'] and r['argv']==v['argv'] and v['physical']=={k:own['bin/'+exe][k] for k in ('dev','ino')}
    assert not set(('CI','CARGO_INCREMENTAL','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','RUSTC_WRAPPER')).intersection(v['environment_keys'])
   assert state['ast']['flags']==frontend.flags(ast['argv'])==bind['actual_flags'] and ast['argv']==bind['actual_argv']
   shard=select['namespaces'][role];assert shard==bind['namespace']
   positions=[];norm=[]
   for i,arg in enumerate(ast['argv']):
    if '/'+shard+'/' in arg:
     assert ast['argv'][i-1] in ('--extern','--out-dir','-L') and arg.count('/'+shard+'/')==1
     arg=arg.replace('/'+shard+'/','/<compiler-namespace>/');positions.append(i)
    norm.append(arg)
   assert positions==env['namespace_positions'] and norm==env['raw_normalized_argv'] and len(norm)==env['argv_count']
   details[role]=rr;actual[role]={'raw_argv':H(json.dumps(ast['argv'],separators=(',',':')).encode()),'namespace':shard,
      'ordinary_ast_env_verified':True}
  assert set(a.native_refs)=={'old','edited'} and len(a.native_refs['old'])==len(a.native_refs['edited'])==95 and len(a.elf)==2
  assert key(a.native_refs['old'])==reference['old_objects'] and key(a.native_refs['edited'])==reference['new_objects']
  return {'roles':details,'cargo':env['cargo'],'sources':expected_sources,'drivers':expected_drivers,'status':'complete native eligibility, zero counts','reference':{k:reference[k] for k in ('old','new','units','old_objects','new_objects','old_value','new_value')},
    'argv_count':env['argv_count'],'namespace_positions':env['namespace_positions'],'actual_ast':actual,'terminal':H(a.get('ruff-native-eligibility.json'))}
 finally:a.z.close()
if __name__=='__main__':
 data=verify(Path(sys.argv[1]));b=(json.dumps(data,indent=2,sort_keys=True)+'\n').encode();Path(sys.argv[2]).open('xb').write(b);print(data['reference'],H(b))
