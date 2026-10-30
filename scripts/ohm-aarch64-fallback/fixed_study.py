"""Run the fixed-Cargo physical Ruff comparison on the schedule frozen before its native gate."""
from pathlib import Path
from hashlib import sha256
import json,runpy,sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import frontend
HOLD=runpy.run_path(str(HERE.parent/'ohm-aarch64-confirm/study.py'))
from ruff import rt,q
from study import load,save,sha

def fingerprint(v):return sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def canonical(argv):
 import re
 frontend.flags(argv)
 tag,=re.findall(r'/(v2-[0-9a-f]{16})/',argv[argv.index('--out-dir')+1])
 norm=[];positions=[]
 for i,v in enumerate(argv):
  if re.search(r'/v2-[0-9a-f]{16}/',v):
   assert i>0 and argv[i-1] in ('--out-dir','--extern','-L') and v.count('/'+tag+'/')==1
   v=v.replace('/'+tag+'/','/<compiler-namespace>/');positions.append(i)
   assert not re.search(r'/v2-[0-9a-f]{16}/',v)
  norm.append(v)
 return norm,positions,tag
def options(stage):
 schedules=load(HERE/'fixed-schedules.json')
 assert stage in ('pilot','confirmation') and set(schedules)=={'pilot','confirmation'}
 return schedules[stage]
def main(number,stage,ancestor,inputs):
 protocol=load(HERE/'admissible-native.json')
 assert protocol['cargo_elf']=='869a24e83ff84cca6e9d6cb35eb62f149aa48555cf8bb7ee9b94d44ad90d2914'
 safe=load(rt.LOG/'independent-admissions.json')
 assert safe['sources']==HOLD['SOURCE'] and safe['admitted']==protocol and safe['cargo']==protocol['cargo_elf']
 p=load(inputs/'fixed/product.json');assert p['cargo_sha256']==protocol['cargo_elf']==sha(inputs/'fixed/cargo')
 if stage=='confirmation':
  assert load(rt.LOG/'independent-pilot.json')['all_twelve_pilot_ratios_strictly_above_two']
 else:assert not (rt.LOG/'independent-pilot.json').exists()
 cert=safe['native_gate'];refs=cert['reference']
 ruff=HOLD['ruff'];ruff.OLD,ruff.NEW,ruff.INVENTORY=refs['old'],refs['new'],refs['units']
 schedule=options(stage);assert sorted(schedule).count(number)==1
 save(rt.LOG/'schedule.json',schedule)
 save(rt.LOG/'fixed-cargo-registration.json',{'stage':stage,'qualified_ancestry':protocol,'schedule':sha(HERE/'fixed-schedules.json'),
      'provider_receipt':safe['provider_readback'],'independent_native':safe['native_readback'],'reference':refs,
      'normalized_argv_sha256':safe['normalized_argv_sha256'],'argc':cert['argv_count'],'namespace_positions':cert['namespace_positions']})
 orig=q.visit
 def capture(root,phase,state,env,searches):
  if phase!='edit':return orig(root,phase,state,env,searches)
  row,measured=frontend.with_live_environment(lambda:orig(root,phase,state,env,searches),root/phase/'native.json',rt.SDK)
  norm,positions,tag=canonical(measured['ast']['argv'])
  assert len(norm)==cert['argv_count'] and positions==cert['namespace_positions'] and fingerprint(norm)==safe['normalized_argv_sha256']
  assert measured['cargo']['physical']=={n:(rt.SDK/'bin/cargo').stat().__getattribute__('st_'+n) for n in ('dev','ino')}
  save(root/phase/'real-cargo-and-AST-environment.json',measured)
  return row
 q.visit=capture
 try:
  HOLD['block'](number,ancestor,inputs,{'order_map':schedule,'cargo':(inputs/'fixed/cargo',p),'registration':sha(rt.LOG/'fixed-cargo-registration.json')})
 finally:q.visit=orig
 terminal=load(rt.LOG/'terminal.json');assert set(terminal['values'])==set('ANM') and terminal['order']==schedule[number]
 for role in 'ANM':
  rr=load(rt.LOG/('block-'+number+'-'+role)/'complete.json')
  assert fingerprint(rr['old']['native'])==refs['old_objects'] and fingerprint(rr['cold']['native'])==refs['new_objects']
  assert rr['old']['reader']==refs['old'] and rr['cold']['reader']==refs['new'] and rr['old']['value']==refs['old_value'] and rr['cold']['value']==refs['new_value']
if __name__=='__main__':main(sys.argv[1],sys.argv[2],*map(Path,sys.argv[3:]))
