"""Independently re-read raw native profiles and the exact committed oracle outcomes."""
from collections import Counter
from pathlib import Path,PurePosixPath
import hashlib,json,runpy,struct,sys,zipfile
H=Path(__file__).resolve().parent;S=runpy.run_path(str(H/'fixture/oracle.py'));Profile=runpy.run_path(str(H/'fixture/profile_v9.py'))['Profile']
h=lambda raw:hashlib.sha256(raw).hexdigest()
def validate(archive,outer,role):
 wanted=S['OWNERS'];assert role in('control','candidate')
 with zipfile.ZipFile(archive)as z:
  items=z.infolist();names=[x.filename for x in items];assert names==sorted(names,key=PurePosixPath)and len(names)==len(set(names))<200 and sum(x.file_size for x in items)<64<<20 and all(not PurePosixPath(n).is_absolute()and'..'not in PurePosixPath(n).parts and'\\'not in n for n in names)and z.testzip()is None
  proof=json.loads(z.read('qualified.json'));observed=json.loads(z.read('observed.json'));assert proof==json.loads(Path(outer).read_bytes())and proof['observed']==h(z.read('observed.json'))and proof['role']==observed['role']==role and proof['registered_foreign_transitions']==len(S['STATES']) and proof['warm_cold_binary_and_errors']
  counts={}
  for state,flags,result in S['STATES']:
   r=observed['states'][state];assert r['cfg']==list(flags)and r['expected']==result and h(z.read(state+'/libroster.rmeta'))==r['upstream_rmeta']
   runs={}
   for t in('warm','cold'):
    v=r[t];stderr=z.read(state+'/'+t+'/stderr');assert h(stderr)==v['stderr']and z.read(state+'/'+t+'/stdout')==b''
    assert '--crate-name'in v['args']and v['args'][v['args'].index('--crate-name')+1]=='reader'and 'roster=libroster.rlib'in v['args']and'owner=libowner.rlib'in v['args']
    if result=='E0061':
     errors=[d for d in map(json.loads,stderr.splitlines())if d.get('level')=='error'and d.get('code')];assert [d['code']['code']for d in errors]==['E0061']and errors[0]['spans'][0]['file_name']=='reader.rs'and v['outcome']=='E0061';continue
    assert not stderr and v['outcome']==0 and v['behavior']==result and len(v['binary'])==64
    name,=[n for n in names if n.startswith(state+'/'+t+'-profile/')and n.endswith('.mm_profdata')];assert int(Path(name).stem.split('-')[-1])==v['pid'];raw=z.read(name);assert h(raw)==v['profile']
    prof=Profile(raw);q=Counter();activity=0
    for typ,idx,thread,lo,hi,flags in struct.iter_unpack('<QQIIII',memoryview(prof.entries)[8:]):
     st=lo|((flags&0xffff0000)<<16);end=hi|((flags&65535)<<32)
     if st>=end or end>=0xfffffffffffe:continue
     kind=prof.label(typ);lab=prof.label(idx);activity+=kind=='GenericActivity'
     if kind=='Query'and lab.startswith('typeck_root\x1e'):q[lab.partition('\x1e')[2]]+=1
    assert activity>0 and dict(q)==v['all_typeck'];runs[t]={n:q['reader::'+n]for n in wanted};assert v['owners']==runs[t]
   assert r['warm']['stderr']==r['cold']['stderr']
   if result!='E0061':
    assert r['warm']['binary']==r['cold']['binary']and runs['cold']==dict.fromkeys(wanted,1);counts[state]=runs
  assert counts['noop']['warm']==dict.fromkeys(wanted,0) and counts['empty-edit']['warm']==proof['actual_empty_edit_typeck']==dict.fromkeys(wanted,int(role=='control'))
  return {'role':role,'source':h(z.read('observed.json')),'verified_raw_provider_counts':counts,'actual_changed_signature':'E0061','archive_sha256':h(Path(archive).read_bytes())}
