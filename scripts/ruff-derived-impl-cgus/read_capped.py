"""Open complete enrolled Actions originals sequentially and summarize their independent pairs."""
import hashlib,json,os,shutil,statistics,subprocess as sp,sys,zipfile
from pathlib import Path
q=Path(__file__).resolve().parent;out=Path(os.environ['RUNNER_TEMP'])/'reopened';out.mkdir();r=int(os.environ['ORIGINAL_RUN']);kind=os.environ['READ_DATASET'];assert kind in('pilots','confirm');live=lambda p:json.loads(sp.check_output(['gh','api','repos/astral-experiments/ohm/'+p]));sha=lambda p:hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
def put(n,d):(out/n).write_text(json.dumps(d,sort_keys=True,indent=1)+'\n')
plan=json.loads((q/'confirmation-plan.json').read_bytes())
if kind=='pilots':
 assert r==41738655551;head=plan['primary_receiver_commit'];cases={n:('derived-impl-'+n+'-'+str(r),'Real Ruff edit '+n)for n in('28392','26372')}
else:
 head='d8596b7fafd31b4f959c7561a921d56705513956';cases={str(i):(f'confirmed-help-{i}-{r}',f'Independently initialized Ruff build {i}')for i in range(6)}
run=live('actions/runs/'+str(r));assert run['run_attempt']==1 and run['head_sha']==head and run['conclusion']=='success' and run['head_branch']=='charlie/qa-ruff-derived-impl-caps-20261103',run['conclusion'];jobs={v['name']:v for v in live('actions/runs/'+str(r)+'/jobs')['jobs']};assets={v['name']:v for v in live('actions/runs/'+str(r)+'/artifacts')['artifacts']};results={}
with zipfile.ZipFile(out/'raw-hardware-and-controls.zip','x',compression=zipfile.ZIP_DEFLATED)as raw:
 for key,(an,jn)in cases.items():
  j=jobs[jn];v=assets[an];h=v['digest'].removeprefix('sha256:');assert j['conclusion']=='success'and v['workflow_run']['id']==r and not v['expired']and v['size_in_bytes']<320*2**20
  assert shutil.disk_usage(out).free>15*2**30 and int(next(s.split()[1]for s in Path('/proc/meminfo').read_text().splitlines()if s.startswith('MemAvailable:')))>8*2**20
  a=out.parent/('original-'+key+'.zip')
  with a.open('xb')as f:sp.run(['gh','api','repos/astral-experiments/ohm/actions/artifacts/'+str(v['id'])+'/zip'],stdout=f,check=True)
  assert (a.stat().st_size,sha(a))==(v['size_in_bytes'],h);binding={'run':r,'head':head,'job':j['id'],'original':v['id'],'size':v['size_in_bytes'],'sha256':h};put(key+'-binding.json',binding)
  path=out/(key+'.json');sp.run([sys.executable,'-IB',q/'reopen.py',a,h,path],check=True,timeout=720);x=json.loads(path.read_bytes());assert x['sha256']==h and [x['roles'][k]['compiler']['source']for k in 'PC']==plan['compilers']and [x['roles'][k]['driver']for k in 'PC']==plan['driver_sha256']
  with zipfile.ZipFile(a)as z:
   if kind=='confirm':
    c=json.loads(z.read('confirmation.json'));assert c['recorded_receipt']==head and x['case']=='28392'and x['confirmation_slot']==int(key)and x['order']==plan['orders'][int(key)]
   else:assert x['case']==key and x['confirmation_slot']is None
   ns=[n for n in z.namelist()if n in('registration.json','terminal.json','confirmation.json')or (len(n.split('/'))==3 and n.split('/')[0]in ('P','C')and (n.endswith('/hardware.json')or n.endswith('/footprint.json')or n.endswith('/caps.json')or n.endswith('/program-verdict.json')or n.endswith('/lifetime.json')or n.endswith('/result.json')))]
   assert {'P/edit/hardware.json','C/edit/hardware.json','P/caps/caps.json','C/caps/caps.json'}<=set(ns);assert sum(z.getinfo(n).file_size for n in ns)<32*2**20
   for n in sorted(ns):
    e=zipfile.ZipInfo(key+'/'+n,(1980,1,1,0,0,0));e.compress_type=zipfile.ZIP_DEFLATED;raw.writestr(e,z.read(n))
  from metadata_controls import read as meta_read
  legacy=Path(os.environ['GITHUB_WORKSPACE'])/'schema/scripts/ruff-clap-config-help/evidence-release-24'
  put(key+'-typed-metadata.json',meta_read(a,legacy))
  results[key]=x;a.unlink()
if kind=='pilots':
 assert len({x['boot']for x in results.values()})==2;primary=results['28392'];decision=(primary['library_rustc_reduction_pct']>=20 or primary['whole_reduction_pct']['edit']>=50)and all(x['whole_reduction_pct']['edit']>0 for x in results.values());put('decision.json',{'registered_two_edit_gate':decision,'cases':{k:{'first_whole_reduction':v['whole_reduction_pct']['edit'],'repeat_whole_reduction':v['whole_reduction_pct']['observed-edit'],'library_rustc_reduction_secondary':v['library_rustc_reduction_pct'],'second_forward_same_metadata':{r:x['independent_forward_proof']for r,x in v['roles'].items()}}for k,v in results.items()}})
else:
 assert len({v['boot']for v in results.values()})==6 and len(set(v['sha256']for v in results.values()))==6
 def describe(values):return {'minimum':min(values),'maximum':max(values),'median':statistics.median(values),'pairs':values}
 stages=sorted(set.intersection(*(set(v['whole_reduction_pct'])for v in results.values())));whole={k:describe([v['whole_reduction_pct'][k]for v in results.values()])for k in stages};affected=describe([v['library_rustc_reduction_pct']for v in results.values()]);store={}
 for k in('cold-old','edit','empty-new'):
  store[k]=describe([v['roles']['C']['storage'][k]['allocated_unique']-v['roles']['P']['storage'][k]['allocated_unique']for v in results.values()])
 decision=whole['edit']['minimum']>0 and (affected['median']>=20 or whole['edit']['median']>=50)
 put('decision.json',{'six_boot_threshold':decision,'whole_instructions_percent_fewer':whole,'secondary_affected_lib_rustc_percent_fewer':affected,'allocated_unique_candidate_minus_parent_bytes':store,'per_boot_whole_instructions':[[v['roles'][x]['ordinary']['edit']for x in 'PC']for v in results.values()],'orders':[v['order']for v in results.values()],'boots':[v['boot']for v in results.values()],'nonparametric_median_interval_confidence':1-2*(.5**6),'two_sided_sign_p_if_all_equal_sign':2*(.5**6)})
print((out/'decision.json').read_text(),flush=True)
