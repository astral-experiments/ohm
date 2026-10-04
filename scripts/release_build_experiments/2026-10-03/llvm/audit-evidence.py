"""Validate complete exported evidence before publication, then print raw pairs."""
import hashlib,json,statistics,sys
from pathlib import Path
harness_sha=hashlib.sha256((Path(__file__).parent/'measure.py').read_bytes()).hexdigest()
inputs={Path(arg).name:json.loads(Path(arg).read_text()) for arg in sys.argv[1:]}
validation=next((d for d in inputs.values() if d.get('host')=='charlie-serc-4'),None)
for arg in sys.argv[1:]:
 d=json.loads(Path(arg).read_text())
 if d.get('host')=='charlie-serc-4':continue
 w='ruff' if 'paired-ruff' in d['builds'] else 'uv'
 layout=d['cache_layout']['cache-layout-deep.json'][w]
 cold_layout=layout['targets']['cold'];assert cold_layout['compiled_artifact_counts']['.rlib']>150
 assert not cold_layout['symlinks_outside_target']
 assert set(layout['cargo_home_registry_dirs'])=={'src','cache','index'}
 for sample in cold_layout['samples']:
  assert sample['resolved'].startswith(f'/tmp/codex-cargo-targets/{w}/isolated/release-llvm/cold/')
 for scope,expected in [('paired',4 if w=='ruff' else 2),('cold',3 if w=='ruff' else 1)]:
  data=d['builds'][f'{scope}-{w}'];assert data['complete']
  rows=data['samples'];assert len(rows)==expected*2
  for row in rows:
   assert row['valid'] and row['compilation_observed'] and row['returncode']==0,row['name']
   assert row['harness_sha256']==harness_sha
   assert row['wall_seconds']>0 and row['max_rss_kib']>0
   assert not row['external_compilation'] and not row['monitor_errors'] and not row['cargo_lock_contention']
  if scope=='paired':assert len({r['artifact']['source_sha256'] for r in rows})==expected
  for n in range(1,expected+1):
   a=next(r for r in rows if r['name']==f'pair-{n}-baseline');b=next(r for r in rows if r['name']==f'pair-{n}-merge')
   if scope=='paired':assert a['artifact']['source_sha256']==b['artifact']['source_sha256']
   else:
    for row,variant in [(a,'baseline'),(b,'merge')]:
     assert row['artifact']['compiled_packages']>150
     assert row['artifact']['binary_sha256']==d['binaries'][f'{variant}-{w}']['sha256'],(w,row['name'],'cold binary/runtime binary mismatch')
   print(w,scope,n,round(a['wall_seconds'],3),round(b['wall_seconds'],3),round(b['wall_seconds']/a['wall_seconds'],6))
  print('paired geomean',data['paired_geomean_ratio'])
 cohort=validation if w=='ruff' else d
 assert cohort is not None, 'Ruff requires separate Serc4 validation cohort'
 runtime=cohort['runtime'][f'runtime-{w}-final'];assert runtime['monitor']['valid']
 assert runtime['monitor']['harness_sha256']==harness_sha
 preliminary=d['runtime']['runtime-ruff-v2' if w=='ruff' else 'runtime-uv']
 workloads=['check','format-check'] if w=='ruff' else ['trio','jupyter']
 for workload in workloads:
  rows=[r for r in runtime['samples'] if r['workload']==workload];assert len(rows)==48
  expected_code=2 if workload=='format-check' else 0
  assert all(r['returncode']==expected_code for r in rows)
  for key in ['stdout_sha256','stderr_normalized_sha256']+(['lock_sha256'] if w=='uv' else []):
   assert len({r[key] for r in rows})==1
   assert rows[0][key]==next(r[key] for r in preliminary['samples'] if r['workload']==workload)
  ratios=[]
  for n in range(24):
   a=next(r for r in rows if r['repetition']==n and r['variant']=='baseline')
   b=next(r for r in rows if r['repetition']==n and r['variant']=='merge')
   ratios.append(b['wall_seconds']/a['wall_seconds'])
  print(w,'runtime',workload,'paired geomean',statistics.geometric_mean(ratios),'range',min(ratios),max(ratios))
 if w=='ruff':
  v=cohort['builds']['flag-validation'];assert v['complete'] and len(v['samples'])==2
  assert all(r['valid'] and r['compilation_observed'] and r['harness_sha256']==harness_sha for r in v['samples'])
  assert len({r['artifact']['source_sha256'] for r in v['samples']})==1
  assert all(g['idle_percent']>=95 and not g['external_compilers'] and g['free_bytes']>=20*1024**3 for g in cohort['validation_idle_gates'].values())
  for name in ['baseline-ruff','merge-ruff']:
   assert cohort['binaries'][name]==d['binaries'][name]
  assert cohort['final-provenance.json']['toolchains']['stage1']==d['final-provenance.json']['toolchains']['stage1']
  parity=json.loads(d['provenance']['flag-validation/parity.json']['text'])
  assert parity['pass_trace_bytes']>1000
  a=next(r for r in v['samples'] if r['name']=='unprofiled-off');b=next(r for r in v['samples'] if r['name']=='unprofiled-on')
  print('actual flag contextual pair',a['wall_seconds'],b['wall_seconds'])
 print('Audit passed:',arg)
