"""Audit fixed paired samples and render the preregistered formatter statistics."""
import argparse,hashlib,importlib.util,json,math,random,statistics
from pathlib import Path

parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
root=args.root;protocol=json.loads((root/'protocol.json').read_text())
def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
frozen=json.loads((root/'frozen-files.json').read_text())
for name,sha in frozen['files'].items():assert digest(root/name)==sha,name
assert digest(root/'host_guard.py')==frozen['host_guard_sha256']
preparation=json.loads((root/'source-preparation.json').read_text());assert preparation['passed']
assert preparation['protocol_sha256']==digest(root/'protocol.json')
assert preparation['frozen_files_sha256']==digest(root/'frozen-files.json')
assert preparation['handoff_sha256']==digest(root/'host-handoff.json')
assert preparation['host_visibility_sha256']==digest(root/'host-visibility.json')
assert preparation['host_selection_sha256']==digest(root/'host-selection.json')
assert preparation['host_guard_sha256']==frozen['host_guard_sha256']
visibility=json.loads((root/'host-visibility.json').read_text());selection=json.loads((root/'host-selection.json').read_text())
assert visibility['passed'] and selection['visibility_mode']=='full-vm'
assert selection['host_visibility_sha256']==digest(root/'host-visibility.json')
assert protocol['host']==preparation['host']==selection['benchmark_host_id']==selection['hostname']==visibility['hostname']
logical_cpus=visibility['logical_cpus'];assert logical_cpus==selection['logical_cpus']
module_path=root/'run-formatting.py';spec=importlib.util.spec_from_file_location('formatter_protocol',module_path);runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
runner.plan_only(protocol)

def audit_interval(sample):
    assert sample['logical_cpu_count']==logical_cpus
    delta=[b-a for a,b in zip(sample['global_cpu_ticks_before'],sample['global_cpu_ticks_after'])]
    total=sum(delta);assert all(tick>=0 for tick in delta) and total>0
    for key,index in [('idle_fraction',3),('iowait_fraction',4),('steal_fraction',7)]:
        assert math.isclose(sample[key],delta[index]/total,rel_tol=1e-12,abs_tol=1e-12)
    scale=sample['clock_ticks_per_second']*sample['interval_seconds']*logical_cpus;assert scale>0
    contributors=sample['external_cpu_contributors']
    user=sum(p['cpu_ticks'] for p in contributors if p['uid']==sample['benchmark_uid'])/scale
    nonsecurity=sum(p['cpu_ticks'] for p in contributors if not(p['uid']==0 and p['name'].startswith('falcon-sensor')))/scale
    assert math.isclose(user,sample['external_user_cpu_fraction'],rel_tol=1e-12,abs_tol=1e-12)
    assert math.isclose(nonsecurity,sample['external_nonsecurity_cpu_fraction'],rel_tol=1e-12,abs_tol=1e-12)
    assert sample['free_bytes']>=60*1024**3
    return user,nonsecurity

def audit_continuity(rows):
    for previous,sample in zip(rows,rows[1:]):
        assert abs(sample['time']-sample['interval_seconds']-previous['time'])<.2,'CPU trace has a gap'
        assert sample['global_cpu_ticks_before']==previous['global_cpu_ticks_after'],'CPU counters are not contiguous'

assert json.loads((root/'status.json').read_text())['state']=='complete'
rows=[]
for project_index,case in enumerate(protocol['cases']):
    project=case['project'];directory=root/project;proof=json.loads((directory/'accepted.json').read_text())
    assert proof['passed'] and digest(directory/'result.json')==proof['result_sha256']
    assert digest(root/(project+'-monitor.json'))==proof['monitor_sha256']
    assert digest(root/(project+'-monitor.jsonl'))==proof['trace_sha256']
    monitor=json.loads((root/(project+'-monitor.json')).read_text());assert monitor['passed'] and monitor['returncode']==0
    assert monitor['monitor_sha256']==frozen['host_guard_sha256']
    assert monitor['trace_sha256']==proof['trace_sha256']
    assert proof['protocol_sha256']==digest(root/'protocol.json')
    assert proof['source_preparation_sha256']==digest(root/'source-preparation.json')
    project_state=json.loads((directory/'status.json').read_text())
    assert project_state['state']=='measurements complete, pending outer monitor'
    assert project_state['protocol_sha256']==proof['protocol_sha256']
    assert project_state['runner_sha256']==frozen['files']['run-formatting.py']
    gate_path=directory/project_state['accepted_preflight']
    assert digest(gate_path)==project_state['accepted_preflight_sha256']
    gate=json.loads(gate_path.read_text());assert gate['passed'] and len(gate['samples'])==6
    for sample in gate['samples']:
        audit_interval(sample)
        assert sample['idle_fraction']>=.95 and sample['iowait_fraction']<=.005 and sample['steal_fraction']<=.001
        assert not sample['competing_processes']
    audit_continuity(gate['samples'])
    trace=[json.loads(line) for line in (root/(project+'-monitor.jsonl')).read_text().splitlines()]
    assert len(trace)==monitor['samples'] and trace and not trace[-1]['runner_running']
    assert all(sample['runner_running'] for sample in trace[:-1])
    audit_continuity(trace)
    trace_start=trace[0]['time']-trace[0]['interval_seconds'];trace_end=trace[-1]['time']
    assert trace_start<=project_state['started_at']<=trace_end
    gate_start=gate['samples'][0]['time']-gate['samples'][0]['interval_seconds'];gate_end=gate['samples'][-1]['time']
    assert trace_start<=gate_start<=gate_end<=trace_end
    streak=0
    for sample in trace:
        assert 0<sample['interval_seconds']<=10,'CPU monitoring gap exceeds ten seconds'
        user,nonsecurity=audit_interval(sample)
        streak=streak+1 if nonsecurity>.05 else 0
        assert not sample['violations'] and not sample['competing_processes'] and user<=.05 and streak<3
    data=json.loads((directory/'result.json').read_text());assert data['source_revision']==case['revision']
    assert preparation['sources'][project]['revision']==case['revision']
    assert data['host']==preparation['host']
    assert data['protocol']==protocol and len(data['samples'])==120
    all_pairs=json.loads((directory/'all-pairs.json').read_text())
    assert len(all_pairs)==126 and [p for p in all_pairs if not p['warmup']]==data['samples']
    baseline=(directory/'baseline.rs').read_bytes()
    baseline_hashes=json.loads((directory/'baseline-hashes.json').read_text())
    assert hashlib.sha256(baseline).hexdigest()==baseline_hashes[case['path']]
    assert baseline.count(case['rewrite_before'].encode())==1
    for scenario_index,scenario in enumerate(protocol['scenarios']):
        pairs=[pair for pair in data['samples'] if pair['scenario']==scenario]
        warmups=[pair for pair in all_pairs if pair['scenario']==scenario and pair['warmup']]
        assert [pair['pair'] for pair in warmups]==[-2,-1]
        assert [pair['order'] for pair in warmups]==[['control','candidate'],['candidate','control']]
        assert len(pairs)==40 and [pair['pair'] for pair in pairs]==list(range(40))
        assert [pair['order'] for pair in pairs]==runner.orders(protocol,project,scenario)
        before=[];after=[]
        for pair in pairs:
            assert not pair['warmup']
            identity=scenario+'-'+str(pair['pair']+protocol['warmup_pairs']).zfill(2)
            assert digest(directory/(identity+'-input.rs'))==pair['input_sha256']
            expected=baseline+(b'' if scenario=='unchanged' else ('\n// Formatting comparison '+project+' '+identity+'.\n').encode())
            edited=expected if scenario!='leaf-rewrite' else expected.replace(case['rewrite_before'].encode(),case['rewrite_after'].encode(),1)
            assert (directory/(identity+'-input.rs')).read_bytes()==edited
            assert hashlib.sha256(expected).hexdigest()==pair['expected_output_sha256']
            for lane,release in [('control',protocol['baseline']),('candidate',protocol['release'])]:
                sample=pair['lanes'][lane]
                assert sample['command']==['cargo','+'+release,'fmt','-p',case['package']]
                assert sample['timed'] and sample['seconds']>0 and sample['all_other_tracked_files_unchanged']
                assert gate_end<=sample['started_at_ns']/1e9<=sample['finished_at_ns']/1e9<=trace_end
                assert sample['output_sha256']==pair['expected_output_sha256']
                assert digest(directory/(identity+'-'+lane+'.patch'))==sample['patch_sha256']
                assert (directory/sample['log']).is_file()
                if scenario=='unchanged':assert sample['target_before']==sample['target_after']
            control=pair['lanes']['control'];candidate=pair['lanes']['candidate']
            assert control['patch_sha256']==candidate['patch_sha256']
            assert sorted(pair['lanes'],key=lambda lane:pair['lanes'][lane]['started_at_ns'])==pair['order']
            first,last=[pair['lanes'][lane] for lane in pair['order']]
            assert first['finished_at_ns']<=last['started_at_ns']
            before.append(control['seconds']);after.append(candidate['seconds'])
        logs=[math.log(b/a) for a,b in zip(before,after)]
        seed=protocol['bootstrap_seed']+10*project_index+scenario_index;randomizer=random.Random(seed)
        bootstrap=sorted(math.exp(statistics.mean(randomizer.choices(logs,k=len(logs)))) for _ in range(protocol['bootstrap_resamples']))
        limits=statistics.quantiles(bootstrap,n=200,method='inclusive');interval=[limits[0],limits[-1]]
        ratio=math.exp(statistics.mean(logs))
        conclusion='faster' if interval[1]<1 else 'slower' if interval[0]>1 else 'inconclusive'
        rows.append({'project':project,'scenario':scenario,'source_revision':case['revision'],'command':['cargo','+<release>','fmt','-p',case['package']],
                     'accepted_pairs':len(pairs),'control_median_seconds':statistics.median(before),'candidate_median_seconds':statistics.median(after),
                     'candidate_over_control_geometric_ratio':ratio,'paired_time_reduction':1-ratio,'bootstrap_99_percent_ratio_interval':interval,
                     'bootstrap_99_percent_reduction_interval':[1-interval[1],1-interval[0]],'bootstrap_resamples':protocol['bootstrap_resamples'],
                     'bootstrap_seed':seed,'candidate_wins':sum(b<a for a,b in zip(before,after)),'conclusion':conclusion,'host':data['host']})
result={'schema_version':1,'release':protocol['release'],'baseline':protocol['baseline'],'accepted_pairs':240,'protocol_sha256':digest(root/'protocol.json'),
        'results':rows,'limits':protocol['limits'],'all_output_parity_checks_passed':True}
assert not args.output.exists();args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
