"""Independently report both executable controls and retain every adverse GNU observation."""
from hashlib import sha256
from pathlib import Path
import io,json,subprocess,sys,zipfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import verify_native
H=lambda b:sha256(b).hexdigest()
RUN=41077287252
QA='fb9a8ed44dfd2a0c5a38ba6838c333790cb9854d'
REPO='astral-experiments/ohm'

def acquire(gh,root,admit=False):
 def get(path):return subprocess.check_output([gh,'api',f'repos/{REPO}/'+path])
 root.mkdir(parents=True,exist_ok=True)
 workflow=json.loads(get(f'actions/runs/{RUN}'))
 assert workflow['head_sha']==QA and workflow['status']=='completed'
 metadata=json.loads(get(f'actions/runs/{RUN}/artifacts'))['artifacts']
 jobs=json.loads(get(f'actions/runs/{RUN}/jobs'))['jobs']
 assert len(jobs)==2 and all(x['status']=='completed' for x in jobs)
 names={'gnu-physical-'+n+'-provider':n for n in ('signed','293')}
 assert set(names)=={x['name'] for x in metadata},metadata
 res={}; records={}
 for a in metadata:
  tag=names[a['name']]
  assert 0<a['size_in_bytes']<520*2**20 and not a['expired'] and a['workflow_run']['head_sha']==QA
  b=get(f'actions/artifacts/{a["id"]}/zip');key=H(b);assert 'sha256:'+key==a['digest'] and len(b)==a['size_in_bytes']
  with zipfile.ZipFile(io.BytesIO(b)) as z:
   assert len(z.namelist())==len(set(z.namelist()))
   # Source groups and action failures are independently accounted for even if an early native phase did not complete.
   failed=[(n,z.read(n).decode(errors='replace')[-1000:]) for n in z.namelist() if n.endswith('/failure.txt')]
   if 'native-group.json' not in z.namelist() or 'independent-native.json' not in z.namelist():
    res[tag]={'artifact':key,'incomplete':True,'files':len(z.namelist()),'terminal_phases':[n for n in z.namelist() if n.endswith('/completed.json')],'failed':failed}
    continue
   result=verify_native.verify(z)
   wire=z.read('independent-native.json');assert result==json.loads(wire) and result['total_Cargo']==324 and result['cargo']==tag
   if (root/'independent-product.json').exists():assert z.read('cargo-293-readback.json')==(root/'independent-product.json').read_bytes()
   if tag=='293':assert json.loads(z.read('cargo-substitution.json'))['to'][0]==result['cargo_elf']=='869a24e83ff84cca6e9d6cb35eb62f149aa48555cf8bb7ee9b94d44ad90d2914'
   else:assert result['cargo_elf']=='abf43741c6c75f7fd4a3bcbf1db0cfc29824a07727bde4a3974b3ea44b379c1a'
   job=next(r for r in jobs if r['name'].endswith(tag));records[tag]=result
   selected={lab:{n:{k:obs[k] for k in ('cargo_exit','answer','elf','all_processes','actual_provider_ld','selected_provider','earlier_negative','later_negative')} for n,obs in row['physical_native'].items()} for lab,row in result['checks'].items()}
   res[tag]={'cargo':result['cargo_elf'],'cargo_source':result['cargo_source'],'source':result['sources'],'hosted_terminal':result['source_terminal'],'independent':H(wire),
             'hosted_job':job['id'],'conclusion':job['conclusion'],'archives':result['all_real_elfs'],'artifact':key,'id':a['id'],'bytes':len(b),'physical_commands':324,
             'adverse':result['adverse_results'],'all_physical':selected,
             'actual_same_inode_stamps':{k:j['actual_mutations'] for k,j in result['checks'].items()}}
  del b
 if set(records)=={'293','signed'}:
  assert records['293']['sources']==records['signed']['sources']
  for tag,rr in records.items():
   assert {len(d['physical_native']) for d in rr['checks'].values()}=={18}
   if tag=='signed':
    for place in ('direct','library'):
     ds=rr['checks']['M-undeclared-'+place]['physical_native']
     for n in ('higher','same-inode-malformed','missing'):
      assert ds[n]['actual_provider_ld']==0
      empty=ds['empty-'+n];assert (ds[n]['cargo_exit'],ds[n]['answer'])!=(empty['cargo_exit'],empty['answer'])
 healthy=set(records)=={'293','signed'} and not records['293']['adverse_results'] and workflow['conclusion']=='success'
 out={'run':RUN,'QA':QA,'safety':healthy,'subjects':res}
 wire=(json.dumps(out,sort_keys=True,indent=2)+'\n').encode()
 op=root/'matched-provider-readback.json'
 if op.exists():assert op.read_bytes()==wire
 else:op.open('xb').write(wire)
 print('safety',healthy,'completed commands',[(n,v.get('physical_commands'),len(v.get('adverse',[]))) for n,v in res.items()],H(wire),flush=True)
 if admit:assert healthy,'GNU native fallback has a material divergence; keep all results and stop the performance arm'
 return out
if __name__=='__main__':acquire(sys.argv[1],Path(sys.argv[2]),len(sys.argv)>3 and sys.argv[3]=='require-safe')
