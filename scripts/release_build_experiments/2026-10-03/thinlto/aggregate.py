#!/usr/bin/env python3
"""Collect compact evidence without dropping unsuccessful or contaminated samples."""
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import tomllib
import bench

ROOT=bench.ROOT
OUT=bench.OUT
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()

def summarize(row,path):
    result={k:v for k,v in row.items() if k!='outside_cpu'}
    cpu=[r['outside_cpu_percent'] for r in row.get('outside_cpu',[])]
    result['outside_cpu']={'samples':len(cpu),'mean_percent':statistics.mean(cpu) if cpu else None,'max_percent':max(cpu) if cpu else None,'samples_above_one_core':sum(x>100 for x in cpu),'compiler_overlap':bench.compiler_overlap(row)}
    memory=[sample['memory_kib'] for sample in row.get('outside_cpu',[]) if 'memory_kib' in sample]
    result['memory']={'min_available_kib':min(x['MemAvailable:'] for x in memory) if memory else None,'max_swap_used_kib':max(x['SwapTotal:']-x['SwapFree:'] for x in memory) if memory else None}
    result['raw_json']={'path':str(path),'sha256':sha(path)}
    log=path.with_suffix('.log')
    if log.exists():
        text=log.read_text()
        result['log']={'path':str(log),'sha256':sha(log),'size_bytes':log.stat().st_size}
        result['root_rustc_invocations']=sum('Running `' in line and '/bin/rustc ' in line and f'--crate-name {row["repo"]} ' in line and '--crate-type bin' in line for line in text.splitlines())
        result['thinlto_info_logged']='INFO rustc_codegen_llvm::back::lto' in text
        if row['phase']=='entry-edit':
            assert result['root_rustc_invocations']==1,result
        assert not result['thinlto_info_logged'],path
    return result

samples=[]
for path in sorted(OUT.glob('*.json')):
    row=json.loads(path.read_text())
    if isinstance(row,dict) and 'elapsed_s' in row:
        samples.append(summarize(row,path))
runtime=[]
for path in sorted((OUT/'runtime').glob('*.json')):
    row=json.loads(path.read_text())
    if isinstance(row,dict) and 'elapsed_s' in row:
        runtime.append(summarize(row,path))
rejected=[]
for directory,reason in [
    ('exploratory-hashless-results','Unsafe initial candidate lacked the combined-index hash guard; stopped incomplete context build and excluded all results.'),
    ('exploratory-logged-results','ThinLTO informational logging was enabled; stopped incomplete context build and excluded all results.'),
    ('rejected-busy-host-results','Entire Arc cohort on original 32-CPU host excluded because sustained unrelated validation activity returned; not pooled with new 16-CPU host.'),
    ('rejected-owned-map-results','Earlier implementation deep-cloned the work-product map per worker; superseded by Arc sharing at ed3bc629. Not mixed with final results. Some samples also overlap outside compilation.'),
]:
    for path in sorted((ROOT/directory).glob('*.json')):
        row=json.loads(path.read_text())
        if isinstance(row,dict) and 'elapsed_s' in row:
            rejected.append({'reason':reason,'row':{k:v for k,v in row.items() if k!='outside_cpu'},'raw_sha256':sha(path)})
source=ROOT/'ohm-rust'
get=lambda *args:subprocess.check_output(args,cwd=source,text=True).strip()
evidence={
    'schema_version':1,
    'candidate':'Opt-in incremental ThinLTO dependency object reuse',
    'measurement_host':'charlie-openai-1',
    'rejected_host':'charlie-oss-1',
    'transfer_archive_sha256':'915786ccec1c5f08e63e99259491c4066ccfdbfaafa2d332049d8086d725621b',
    'flag':'-Zohm-thin-lto-dependency-cache=yes',
    'scope':'Explicit ThinLTO plus incremental compilation. Does not change the default fat-LTO release profile.',
    'source_base':'348339ddae4288ebb3af97d204b19479fef8f5f2',
    'source_head':json.loads((ROOT/'source-manifest.json').read_text())['source_head'],
    'source_diff_sha256':json.loads((ROOT/'source-manifest.json').read_text())['diff_sha256'],
    'tested_source_sha256':json.loads((OUT/'tested-source-sha256.json').read_text()),
    'compiler_provenance':json.loads((OUT/'provenance.json').read_text()),
    'environment_audit':json.loads((OUT/'environment-audit.json').read_text()),
    'machines':{repo:json.loads((OUT/f'{repo}-machine.json').read_text()) for repo in ['uv','ruff']},
    'workload_pins':{repo:pin for repo,(pin,_) in bench.CONFIG.items()},
    'release_profiles':{repo:tomllib.loads((ROOT/repo/'Cargo.toml').read_text())['profile']['release'] for repo in bench.CONFIG},
    'pair_selection':{repo:json.loads((OUT/f'{repo}-pair-acceptance.json').read_text()) for repo in bench.CONFIG},
    'selection_rule':'At least 95% CPU idle for 5 seconds before each build. First two complete AB and two complete BA pairs without observed outside compiler activity and with mean outside CPU at most 5% of machine capacity; retain and label whole excluded pairs.',
    'mechanism':json.loads((OUT/'mechanism.json').read_text()),
    'rejected_implementation_provenance':json.loads((ROOT/'rejected-owned-map-results/provenance.json').read_text()),
    'runtime_corpus':{'repository':'python/cpython','commit':'0b05ead877f909b7efe712db758012d9dbece7ce','archive_sha256':sha(ROOT/'corpus/cpython-v3.12.7.tar.gz')},
    'harnesses':{name:sha(ROOT/name) for name in ['bench.py','library-bench.py','runtime-bench.py']},
    'samples':samples,'runtime_samples':runtime,'rejected':rejected,
    'runtime_stderr_equivalence':json.loads((OUT/'runtime/stderr-equivalence.json').read_text()),
    'correctness_logs':{str(p):sha(p) for p in [ROOT/'compiler-tests-arc.log']},
    'interpretation_limits':['Locally built optimized stage1 compiler without PGO; this is not a timing of the distributed PGO toolchain.','Four accepted counterbalanced entrypoint edit pairs per CLI; tiny black_box body edits measure a favorable reuse case.','Cold profile and fat profile context have one sample each, not a repeated speedup claim.','One library edit pair per CLI is directional only.','Peak RSS is wait4 maximum child process RSS, not aggregate process-tree memory.'],
}
(OUT/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
print(json.dumps({'samples':len(samples),'runtime_samples':len(runtime),'source_head':evidence['source_head'],'evidence_sha256':sha(OUT/'evidence.json')}))

