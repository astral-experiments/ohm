"""Reopen fixed-Cargo controls, all raw guest counters and the two separate paired baselines."""
from pathlib import Path
from hashlib import sha256
import json,os,runpy,shutil,subprocess,sys,zipfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import fixed_study as fixed
CONF=HERE.parent/'ohm-aarch64-confirm'
reader=runpy.run_path(str(CONF/'reopen.py'))
H=lambda b:sha256(b).hexdigest()
def load(p):return json.loads(p.read_bytes())
def dump(dst,val):dst.open('xb').write((json.dumps(val,indent=2,sort_keys=True)+'\n').encode())
def block(path,stage,num,git,raw_sha,order_file):
 reg=load(HERE/'admissible-native.json')
 schedules=fixed.options(stage)
 # The existing independently checked reader accepts no variable namespace fields except the registered ones.
 with zipfile.ZipFile(path) as z:
  get=lambda n:json.loads(z.read(n))
  assert get('schedule.json')==schedules
  main=get('heldout-registration.json');extra=get('fixed-cargo-registration.json');gates=get('independent-admissions.json')
  assert main['actual_cargo']==reg['cargo_elf']==gates['cargo'] and extra['stage']==stage
  assert main['additional_qualification']==H(z.read('fixed-cargo-registration.json'))
  assert gates['native_readback']==extra['independent_native']==reg['native_readback'] and gates['provider_readback']==extra['provider_receipt']==reg['provider_readback']
  assert reg==gates['admitted']==extra['qualified_ancestry'] and extra['reference']==reg['reference']
  assert get('cargo-substitution.json')['to'][0]==reg['cargo_elf']
  assert main['signed_tools']['bin/cargo']=='abf43741c6c75f7fd4a3bcbf1db0cfc29824a07727bde4a3974b3ea44b379c1a'
  initial=get('all-named-start-identities.json')
  proofs={}
  for role in 'ANM':
   p='block-'+num+'-'+role
   actual=get(p+'/edit/real-cargo-and-AST-environment.json')
   native=get(p+'/edit/native.json');ast,=[r for r in native['rustcs'] if r['crate']=='ruff_python_ast'];cargo,=native['cargo']
   for kind,row,leaf in [('ast',ast,'rustc'),('cargo',cargo,'cargo')]:
    env=actual[kind];orig=initial[role]['bin/'+leaf]
    assert env['physical']=={k:orig[k] for k in ('dev','ino')} and env['argv']==row['argv'] and env['pid']==row['pid']
    assert not {'CI','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','CARGO_INCREMENTAL','RUSTC_WRAPPER'}.intersection(env['environment_keys'])
   assert initial[role]['bin/cargo']['sha256']==reg['cargo_elf']
   assert actual['ast']['flags']==fixed.frontend.flags(ast['argv'])
   comp=get(p+'/complete.json')
   for state,alias in [('old','old'),('cold','new')]:
    assert comp[state]['reader']==reg['reference'][alias] and comp[state]['value']==reg['reference'][alias+'_value']
    assert fixed.fingerprint(comp[state]['native'])==reg['reference'][alias+'_objects']
   proofs[role]={'ordinary_ast':actual['ast']['flags'],'actual_environment_keys':{k:v['environment_keys'] for k,v in actual.items()},'complete':H(z.read(p+'/edit/real-cargo-and-AST-environment.json'))}
  if stage=='confirmation':
   pilot=get('independent-pilot.json');assert pilot['all_twelve_pilot_ratios_strictly_above_two'] and H(z.read('independent-pilot.json'))==load(HERE/'qualified-pilot.json')['analysis']
  else:assert 'independent-pilot.json' not in z.namelist()
 def canonical(args):
  norm,positions,tag=fixed.canonical(args)
  assert len(norm)==reg['actual_argc'] and positions==reg['namespace_positions'] and fixed.fingerprint(norm)==reg['normalized_argv_sha256']
  return norm,positions,tag
 fn=reader['reopen'];fn.__globals__['schedule']=schedules;fn.__globals__['canonical']=canonical
 study=fn.__globals__['Study'];native_globals=study.native.__globals__
 native_globals['OLD'],native_globals['NEW'],native_globals['INV']=(reg['reference'][k] for k in ('old','new','units'))
 one=fn(path,num,git,raw_sha,order_file)
 one.update(stage=stage,fixed_cargo=reg['cargo_elf'],fixed_native=reg['native_readback'],fixed_real_environment=proofs)
 return one
def pilot(rows,order):
 assert len(rows)==len(order)==2 and {v['block']:v['order'] for v in rows}==order and list(order.values())==['ANM','MNA']
 assert len({r['fixed_cargo'] for r in rows})==1
 assert all(r['stage']=='pilot' for r in rows)
 for k in ('source','drivers','same_source_complete_reader','ordered_objects_sha256','fixed_native'):
  assert all(r[k]==rows[0][k] for r in rows)
 data={}
 for parent in ('N','A'):
  for phase in ('first-real-edit','combined','settled'):
   ordered=[]
   for r in sorted(rows,key=lambda r:r['block']):
    def value(role):
     entries={k:sum(v.values()) for k,v in r['whole_guest_Ir_by_process'][role].items()}
     return entries['first-real-edit']+entries['immediate-repeat'] if phase=='combined' else entries[phase]
    a,b=value(parent),value('M');assert a>0 and b>0
    ordered.append([r['block'],a,b,a/b])
   data[f'{parent}/M:{phase}']=ordered
 return {'stage':'pilot','all_twelve_pilot_ratios_strictly_above_two':all(x[-1]>2 for r in data.values() for x in r),
         'sources':rows[0]['source'],'fixed_cargo':rows[0]['fixed_cargo'],'native':rows[0]['fixed_native'],'schedule':order,'distinct_boot_ids':len({r['boot'] for r in rows}),'paired_ratios':data}
def remote(stage):
 get=lambda n:json.loads(subprocess.check_output(['gh','api','repos/astral-experiments/ohm/'+n]))
 run=os.environ['GITHUB_RUN_ID'];git=os.environ['GITHUB_SHA'];assert get('actions/runs/'+run)['head_sha']==git
 order=fixed.options(stage)
 directory=Path(os.environ['RUNNER_TEMP'])/'gnu-735e1528-raw-reader';directory.mkdir();out=directory/'verified';out.mkdir()
 order_file=directory/'schedule.json';dump(order_file,order)
 arts={a['name']:a for a in get('actions/runs/'+run+'/artifacts?per_page=100')['artifacts']}
 assert set(arts)=={'gnu-735e1528-'+stage+'-'+n for n in order} and len(arts)==len(order)
 jobs=get('actions/runs/'+run+'/jobs?per_page=100')['jobs']
 qualified=[j for j in jobs if j['name'].startswith('Fixed Cargo '+stage+' Ruff block ')]
 assert len(qualified)==len({j['id'] for j in qualified})==len(order) and {j['name'].rsplit(' ',1)[-1] for j in qualified}==set(order)
 assert all(j['status']=='completed' and j['conclusion']=='success' for j in qualified)
 rows=[]
 for n in sorted(order):
  item=arts['gnu-735e1528-'+stage+'-'+n];assert item['workflow_run']['head_sha']==git and item['workflow_run']['id']==int(run) and not item['expired']
  length=item['size_in_bytes'];assert 0<length<768*2**20 and shutil.disk_usage(directory).free>length+16*2**30
  p=directory/(n+'.zip')
  with p.open('xb') as f:subprocess.run(['gh','api','repos/astral-experiments/ohm/actions/artifacts/'+str(item['id'])+'/zip'],stdout=f,check=True)
  assert p.stat().st_size==length
  one=block(p,stage,n,git,item['digest'].removeprefix('sha256:'),order_file);dump(out/('block-'+n+'.json'),one);rows.append(one);p.unlink()
 if stage=='pilot':projection=pilot(rows,order);passkey='all_twelve_pilot_ratios_strictly_above_two'
 else:
  assert len(rows)==12 and all(r['stage']=='confirmation' for r in rows)
  analyze=reader['analyze'];analyze.__globals__['schedule']=order
  projection=analyze(rows);projection.update(stage=stage,fixed_cargo=rows[0]['fixed_cargo'],native=rows[0]['fixed_native']);passkey='all_six_in_all_blocks_above_two'
 dump(out/'analysis.json',projection);print(stage,projection[passkey],flush=True);assert projection[passkey],'actual predeclared numerical gate failed; preserve all results'
if __name__=='__main__':remote(sys.argv[1])
