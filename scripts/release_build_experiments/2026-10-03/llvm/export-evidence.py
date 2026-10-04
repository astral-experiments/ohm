#!/usr/bin/env python3
"""Export public benchmark receipts without arbitrary environment variables."""
from collections import defaultdict
from pathlib import Path
import hashlib,json,os,platform,statistics,subprocess,time
try:
 import tomllib
except ImportError:
 tomllib=None
root=Path('/tmp/ohm-release-campaign/llvm')
evidence=root/'evidence'
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  while b:=f.read(1024*1024):h.update(b)
 return h.hexdigest()
def read_json(path):return json.loads(path.read_text())
envkeys={'CARGO_HOME','CARGO_TARGET_DIR','CARGO_BUILD_BUILD_DIR','CARGO_BUILD_JOBS','CARGO_INCREMENTAL','CARGO_PROFILE_RELEASE_LTO','CARGO_PROFILE_RELEASE_CODEGEN_UNITS','CARGO_PROFILE_RELEASE_OPT_LEVEL','RUSTC','RUSTDOC','RUSTC_WRAPPER','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','RUSTUP_TOOLCHAIN'}
def cpu_summary(path):
 d=read_json(path);top=defaultdict(float)
 for sample in d['samples']:
  for row in sample['external_activity']:top[row['name']]+=row['cpu_seconds']
 delta=[b-a for a,b in zip(d['initial_cpu_ticks'],d['samples'][-1]['total_cpu_ticks'])] if d['samples'] else [0]*8
 total=sum(delta[:8]) or 1
 return {'raw_sha256':sha(path),'raw_bytes':path.stat().st_size,'iowait_percent':delta[4]/total*100,'steal_percent':delta[7]/total*100,'outside_cpu_by_process_name':dict(sorted(top.items(),key=lambda x:-x[1])[:10])}
result={'schema_version':1,'host':platform.node(),'exported_unix':time.time(),'compiler_release':'ohm-1.99.0-1','compiler_rust_pin':'348339ddae4288ebb3af97d204b19479fef8f5f2','compiler_cargo_pin':'018a2b93409433dc5bc05c5fce838ae69e9bc396','compiler_archive_sha256':'ed158e6fbd2170cfd29af0dfc38cb0f9be0a23159a61914c9c49e0cd34342f71','builds':{},'runtime':{},'provenance':{},'plugins':{},'notes':[
'Paired shipping-compiler plugin measurements preserve PGO/BOLT provenance. Compiled implementation parity is a separate check.',
'Earlier -Zprint-llvm-passes stderr equality was only legacy machine-pass listing equality, not full optimization-pipeline proof. The corrected test uses -Zautodiff=PrintPasses stdout and asserts the mergefunc pass is present.',
'Ruff baseline-repeat was a cached artifact restoration without compilation and is excluded.',
'Ruff runtime-v1 failed an exact stderr hash assertion because the same two warnings reorder even within identical baseline runs. All raw streams from runtime-v2 were retained and the complete warning-line multiset validated.',
'Instrumented Ruff profile is attribution only: its timing was invalidated by a transient compiler ancestry observation and instrumentation materially increases runtime.',
'Cold means empty task-owned target artifacts with cached dependency downloads and default concurrency. Entry edits and cold builds are reported separately.',
'All peak RSS values are the maximum child-process RSS in KiB, not a sum of concurrent process RSS.',
]}
for directory in ['screen-ruff','screen-uv','paired-ruff','paired-uv','cold-ruff','cold-uv','flag-validation']:
 p=evidence/directory
 if not p.exists():continue
 rows=[]
 for receipt in sorted(p.glob('*.json')):
  if receipt.name.endswith(('.cpu.json','.provenance.json')):continue
  d=read_json(receipt)
  if 'wall_seconds' not in d:continue
  d['name']=receipt.stem;d['raw_receipt_sha256']=sha(receipt)
  d['environment']={k:v for k,v in d.get('environment',{}).items() if k in envkeys}
  provenance=p/(receipt.stem+'.provenance.json')
  if provenance.exists():d['artifact']=read_json(provenance)
  cpu=p/(receipt.stem+'.cpu.json')
  if cpu.exists():d['cpu_summary']=cpu_summary(cpu)
  if directory=='screen-ruff' and receipt.stem=='baseline-repeat':d['excluded_reason']='Ohm restored a prior compiler-option namespace; no compiler ran (0.289s). Original valid=true predated the explicit compilation assertion and is overridden for analysis.'
  if directory=='flag-validation':
   if receipt.stem.startswith('unprofiled-'):d['measurement_scope']='Contextual actual-flag comparison on a separately rebuilt non-PGO/BOLT compiler; one pair, separate from shipping compiler evidence.'
   else:d['excluded_from_performance_reason']='Compiler implementation parity using a separately rebuilt, non-PGO/BOLT compiler and pipeline printing.'
  rows.append(d)
 result['builds'][directory]={'complete':(p/'complete').exists(),'samples':rows}
 if directory.startswith(('paired-','cold-')):
  pairs=[]
  for n in range(1,5):
   a=next((r for r in rows if r['name']==f'pair-{n}-baseline'),None);b=next((r for r in rows if r['name']==f'pair-{n}-merge'),None)
   if a and b and a['valid'] and b['valid']:pairs.append({'pair':n,'baseline_seconds':a['wall_seconds'],'candidate_seconds':b['wall_seconds'],'candidate_over_baseline':b['wall_seconds']/a['wall_seconds'],'baseline_max_rss_kib':a['max_rss_kib'],'candidate_max_rss_kib':b['max_rss_kib']})
  result['builds'][directory]['pairs']=pairs
  if pairs:result['builds'][directory]['paired_geomean_ratio']=statistics.geometric_mean(p['candidate_over_baseline'] for p in pairs)
for directory in ['runtime-ruff','runtime-ruff-v2','runtime-ruff-final','runtime-uv','runtime-uv-final']:
 p=evidence/directory
 if not (p/'samples.json').exists():continue
 result['runtime'][directory]={'samples':read_json(p/'samples.json'),'sample_file_sha256':sha(p/'samples.json')}
 if directory=='runtime-ruff':result['runtime'][directory]['excluded_reason']='Initial runtime guard rejected nondeterministic warning ordering within identical baseline runs; replaced by strict known-warning multiset validation in runtime-ruff-v2.'
 if (p/'runtime-suite.json').exists():result['runtime'][directory]['monitor']=read_json(p/'runtime-suite.json')
 if (p/'runtime-suite.cpu.json').exists():result['runtime'][directory]['cpu_summary']=cpu_summary(p/'runtime-suite.cpu.json')
 if (p/'warning-normalization.json').exists():result['runtime'][directory]['warning_normalization']=read_json(p/'warning-normalization.json')
for name in ['machine-provenance.txt','cgroup-provenance.txt','service-cgroups.json','bootstrap.toml']:
 p=evidence/name
 if not p.exists() and (root/name).exists():p=root/name
 if p.exists():
  normalized='\n'.join(line for line in p.read_text().splitlines() if not line.startswith('Vulnerability '))+'\n'
  result['provenance'][name]={'raw_sha256':sha(p),'text_sha256':hashlib.sha256(normalized.encode()).hexdigest(),'text':normalized,'normalization':'Omit unrelated lscpu vulnerability-report lines; retain CPU model, topology, limits, and compiler provenance.'}
for name in ['std-provenance.txt','rustc-version.txt','option-help.txt','parity.json','trace-rejection.json','artifacts.json']:
 p=evidence/'flag-validation'/name
 if p.exists():result['provenance'][f'flag-validation/{name}']={'sha256':sha(p),'text':p.read_text()}
for name in ['baseline','merge','prune-merge']:
 p=root/f'plugins/{name}.so'
 if p.exists():result['plugins'][name]={'sha256':sha(p),'bytes':p.stat().st_size}
result['binaries']={p.name:{'sha256':sha(p),'bytes':p.stat().st_size} for p in (evidence/'binaries').glob('*') if p.is_file()}
for workload in ['ruff','uv']:
 p=root/workload
 if (p/'Cargo.toml').exists():
  result['provenance'][workload]={'source_pin':subprocess.check_output(['git','rev-parse','HEAD'],cwd=p,text=True).strip(),'manifest_sha256':sha(p/'Cargo.toml'),'lock_sha256':sha(p/'Cargo.lock'),'profiles':tomllib.loads((p/'Cargo.toml').read_text()).get('profile',{}) if tomllib else 'See pinned manifest (stdlib tomllib unavailable).'}
result['hypotheses']={
 'early_merge': 'Selected narrow experiment; opt-in flag leaves release optimization and fat-LTO settings intact.',
 'early_dce_then_merge': 'Single Ruff screen only; difference from merge alone is inconclusive, so no extra pass included in the patch.',
 'retain_analyses': 'Single Ruff screen essentially flat compile time with about 34 percent greater peak child RSS; binary identical to baseline. Not selected.',
 'parallel_post_lto_codegen': 'Deferred architectural direction supported by an instrumented profile, not implemented or timed as a candidate.'
}
result['cache_layout']={}
for name in ['cache-layout-inspection.json','cache-layout-deep.json']:
 p=evidence/name
 if p.exists():result['cache_layout'][name]=read_json(p)
for name in ['final-provenance.json','raw-artifacts-manifest.json']:
 p=evidence/name
 if p.exists():result[name]=read_json(p)
result['validation_artifacts']={}
for p in sorted(evidence.glob('idle-gate-*.json')):
 result.setdefault('validation_idle_gates',{})[p.name]=read_json(p)
if (evidence/'validation-host.json').exists():
 host=read_json(evidence/'validation-host.json')
 if 'lscpu' in host:host['lscpu']='\n'.join(line for line in host['lscpu'].splitlines() if not line.startswith('Vulnerability '))+'\n'
 host['raw_sha256']=sha(evidence/'validation-host.json')
 result['validation_host']=host
for name in ['migration.json','transfer-verification.json','validation-service-cgroup.json']:
 if (evidence/name).exists():result.setdefault('audit',{})[name]=read_json(evidence/name)

for name in ['compiler-build.log','compiler-tests.log','compiler-tests-legacy-trace-rejected.log']:
 p=evidence/name
 if p.exists():result['validation_artifacts'][name]={'sha256':sha(p),'bytes':p.stat().st_size,'tail':p.read_text().splitlines()[-12:]}
for directory in ['screen-ruff','paired-uv','plugin-smoke']:
 p=evidence/directory
 for name in ['rejections.json','scope-decision.json']:
  if (p/name).exists():result.setdefault('audit',{})[f'{directory}/{name}']=read_json(p/name)
def sanitize(obj):
 if isinstance(obj,dict):
  return {k:({a:b for a,b in v.items() if a in envkeys} if k=='environment' and isinstance(v,dict) else sanitize(v)) for k,v in obj.items()}
 if isinstance(obj,list):return [sanitize(x) for x in obj]
 return obj
result=sanitize(result)
(root/'compact-evidence.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(root/'compact-evidence.json', (root/'compact-evidence.json').stat().st_size)
