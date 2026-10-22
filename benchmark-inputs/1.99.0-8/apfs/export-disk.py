"""Audit the eight APFS cohorts before publishing allocation comparisons."""
import argparse, collections, datetime, hashlib, importlib.util, json, math, os, re, shlex, subprocess, sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location('disk_runner',HERE/'run-disk.py')
disk=importlib.util.module_from_spec(spec);spec.loader.exec_module(disk)
ROOT=disk.ROOT;REPO=disk.REPO;REPORTS=ROOT/'reports';RELEASE='ohm-1.99.0-8'
def load(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def require(test,reason):
    if not test:raise RuntimeError(reason)
def write(path,value):Path(path).write_text(json.dumps(value,indent=2)+'\n')
def normalized(command):return [x for x in command if not x.startswith('+')]
def expected_sources(scenario):
    source=ROOT/'repos'/(scenario.project+'.git')
    env=os.environ|{'GIT_INDEX_FILE':str(REPORTS/(scenario.project+'-expected-index'))}
    def git(*args,**kw):return subprocess.check_output(['git','-C',str(source),*args],env=env,**kw)
    require(git('config','user.email').decode().strip()=='charlie.r.marsh@gmail.com','Wrong source Git identity')
    git('read-tree',scenario.base_revision)
    study=disk.replay.Replay(disk.replay.parser().parse_args(['--project',scenario.project,'--scenario',str(scenario.path),'--output-dir',str(REPORTS/'source-audit')]))
    trees={0:git('write-tree').decode().strip()};patches={}
    for index,step in enumerate(scenario.steps,1):
        if step['kind']=='edit':
            patch=study.patch_bytes(scenario,source,step);patches[index]=hashlib.sha256(patch).hexdigest()
            git('apply','--cached','-',input=patch)
            trees[index]=git('write-tree').decode().strip()
    return trees,patches

def audit(evidence):
    state=load(evidence/'results.json');cell=state['cell'];project,label,mode=cell.split('-')
    require(state['state']=='complete' and not state.get('sampler_error'),'Incomplete cohort: '+cell)
    require(state['measurement_policy']=={'quiet_required':False,'timings_compared':False,'isolated_apfs_volume':True},'Unexpected measurement policy')
    preflight=load(evidence/'preflight.json');require(preflight['free_bytes']>=60*1024**3 and preflight['quiet_required'] is False,'Capacity preflight failed')
    fixture=REPO/'scripts/session_replays'/('disk-1.99.0-1-'+project+'.json')
    require(state['fixture_sha256']==sha(fixture),'Fixture changed')
    for name,key in [('run-disk.py','runner_sha256'),('apfs_meter.py','meter_sha256')]:
        require(sha(evidence/'instrumentation'/name)==state[key],'Instrumentation changed')
    require(state['selector']==(RELEASE if label=='ohm' else '1.99.0'),'Wrong toolchain')
    for tool,identity in state['toolchain_identity'].items():
        require(sha(identity['path'])==identity['sha256'],'Installed tool changed after measurement: '+tool)
    scenario=disk.replay.load_scenario(fixture);trees,patches=expected_sources(scenario)
    split=[i for i,s in enumerate(scenario.steps) if s['kind']=='edit'][1]
    first_edit=next(s['commit'] for s in scenario.steps if s['kind']=='edit')
    first_tree=trees[min(i for i in trees if i>0)];final_tree=trees[max(trees)]
    count=1 if mode=='single' else 10
    expected=[]
    for number in range(1,count+1):
        expected.append((number,'create',0,None))
        if number==1:
            expected.extend((number,'warmup',i,s) for i,s in enumerate(scenario.warmup,1))
            steps=scenario.steps if mode=='single' else scenario.steps[:split];offset=0
        else:steps=scenario.steps[split:];offset=split
        expected.extend((number,'session',i,s) for i,s in enumerate(steps,offset+1))
    require(len(state['steps'])==len(expected),'Wrong operation count: '+cell)
    commands=[];logs={};package_cache_wait_messages=0
    for observed,(number,phase,index,step) in zip(state['steps'],expected):
        require((observed['worktree'],observed['index'])==(number,index),'Operation order differs')
        kind='create' if phase=='create' else step['kind'];require(observed['kind']==kind,'Operation kind differs')
        detail=observed['detail']
        if kind=='create':
            require(detail['head']==(scenario.base_revision if number==1 else first_edit),'Created wrong checkout')
            require(detail['tree']==(trees[0] if number==1 else first_tree),'Created wrong source tree')
        elif kind=='edit':
            require(detail['patch_sha256']==patches[index],'Applied patch differs')
            require(detail['source']['tree']==trees[index],'Edited source tree differs')
        else:
            require(detail['returncode']==0,'Command failed')
            require(detail['external_compilation'] is None and detail['wall_seconds_are_performance_measurement'] is False,'Disk command treated as timing measurement')
            require(detail['phase']==phase and detail['label']==step['label'],'Wrong command phase')
            require(normalized(detail['command'])==normalized(disk.replay.Replay.command(step,state['selector'])),'Command differs from fixture')
            require(math.isfinite(detail['wall_seconds']) and detail['wall_seconds']>0,'Invalid command duration')
            path=Path(detail['log']);require(path.is_relative_to(evidence),'Log outside cohort')
            require(sha(path)==detail['log_sha256'],'Command log changed')
            text=path.read_text()
            waits=[line.strip() for line in text.splitlines() if 'blocking waiting for file lock' in line.lower()]
            require(all(line.lower()=='blocking waiting for file lock on package cache' for line in waits),'Build-directory lock contention')
            require(detail.get('package_cache_waits',[])==waits,'Package-cache wait receipt differs from log')
            package_cache_wait_messages+=len(waits)
            require(detail['tests_started']==sum(int(m.group(1)) for m in disk.replay.TEST_COUNT.finditer(text)),'Test count differs from log')
            require(not re.search(r'test result: FAILED|Summary .*\b[1-9][0-9]* failed',text),'Test failure in successful command')
            commands.append({'worktree':number,'phase':phase,'index':index,'command':normalized(detail['command']),'tests_started':detail['tests_started'],'compiler_invocations':len(detail['actual_compiler_invocations'])})
            logs[str(path)]={'sha256':sha(path),'bytes':path.stat().st_size}
        require(observed['allocation']['retained_bytes']>=0 and observed['free_bytes']>=60*1024**3,'Allocation/capacity failure')
    require(len(commands)=={('ruff','single'):13,('ruff','forks'):77,('uv','single'):20,('uv','forks'):92}[project,mode],'Wrong Cargo command count')
    completed=state['completed_worktrees'];require([x['number'] for x in completed]==list(range(1,count+1)),'Missing worktrees')
    volume=load(evidence/'volume.json');mount=Path(volume['mount'])
    source_proofs=[]
    for row in completed:
        source=row['source'];number=row['number']
        expected_tree=first_tree if mode=='forks' and number==1 else final_tree
        require(source['tree']==expected_tree,'Completed worktree source differs')
        require(disk.source_state(mount/'worktrees'/str(number))==source,'Worktree changed after endpoint')
        source_proofs.append(source)
    inode=disk.private_inode_audit(mount,label);require(not inode['cross_workspace_shared_inodes'],'Private worktree artifacts are hardlinked')
    if label=='ohm':require(sum(n.startswith('workspace/') for n in inode['namespaces'])==count,'Missing workspace namespaces')
    endpoint=state['idle'];require(endpoint['idle_seconds']>=30,'Idle interval too short')
    readings=endpoint['samples'][-5:]
    require(len(readings)==5 and len({r['native_bytes'] for r in readings})==1,'Endpoint allocation did not stabilize')
    require(all(r['crosscheck']['between_native_samples'] for r in readings),'Endpoint native and diskutil allocation disagree')
    require(endpoint['endpoint']['retained_bytes']>0,'Empty endpoint')
    require(state['baseline_bytes']==volume['baseline']['endpoint']['native_bytes'],'Baseline differs')
    samples=[json.loads(x) for x in (evidence/'allocation-samples.jsonl').read_text().splitlines()]
    require(len(samples)>=30 and all(r['free_bytes']>=60*1024**3 for r in samples),'Allocation trace missing or capacity below reserve')
    require([r['time'] for r in samples]==sorted(r['time'] for r in samples),'Allocation trace order differs')
    if label=='ohm' and mode=='forks':
        require([r['number'] for r in state['seeds']]==list(range(2,11)),'Missing worktree imports')
        for seed in state['seeds']:
            require(sha(seed['log'])==seed['sha256'] and 'Seeded ' in Path(seed['log']).read_text(),'Worktree import missing')
    runtime=[]
    if project=='uv':
        runtime=load(evidence/'runtime-checks.json')['checks'];require([x['worktree'] for x in runtime]==list(range(1,count+1)),'Missing recipient uv runtime checks')
        scopes=set()
        for check in runtime:
            require(check['returncode']==0 and check['tests']==1,'UV runtime check failed')
            for field in ['binary','test_binary','log','selection_log']:require(sha(check[field])==check[field+'_sha256'],'Runtime proof changed')
            number=check['worktree'];target=mount/'targets'/str(number)
            require(Path(check['binary'])==target/'debug/uv','Runtime check used another recipient CLI')
            require(check['selection_log'] in logs,'Runtime executable was not selected from an audited command log')
            selected=[]
            for line in Path(check['selection_log']).read_text().splitlines():
                match=re.fullmatch(r'\s*Running `(.+)`',line)
                if match:
                    args=shlex.split(match.group(1))
                    if args and Path(args[0]).name.startswith('pip_install-'):selected.append(args[0])
            require(selected==[check['test_binary']],'Runtime executable differs from the one Cargo ran')
            binary=Path(check['test_binary']);require(binary.resolve().is_relative_to(mount.resolve()),'Runtime test executable escaped its cohort')
            scope=disk.binary_scope(target,binary)
            if scope.startswith('workspace/'):
                require(label=='ohm','Stock runtime binary outside recipient target')
                require(scope in inode['namespaces'],'Runtime binary lacks a private workspace namespace')
            require(scope not in scopes,'Recipients share a private test namespace');scopes.add(scope)
    environment=state['environment']
    require(environment.get('CARGO_UNSTABLE_OHM_READY_TESTS')==None,'Test-build overlap setting differs')
    require(environment['CARGO_BUILD_JOBS']=='8' and environment['CARGO_NET_OFFLINE']=='true','Benchmark environment differs')
    require(environment['CARGO_INCREMENTAL']=='1','Incremental disabled')
    for key,value in scenario.environment.items():require(environment[key]==value,'Fixture environment differs')
    if label=='ohm':
        require(environment['CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST']=='all' and environment['CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST']=='all','Ohm trust settings differ')
    else:require('CARGO_BUILD_BUILD_DIR' not in environment,'Stock compiler used shared build directory')
    receipt={'cell':cell,'evidence':str(evidence),'results_sha256':sha(evidence/'results.json'),'fixture_sha256':sha(fixture),'commands':commands,'source_proofs':source_proofs,'logs':logs,'private_inode_audit':inode,'runtime_checks':runtime,'allocation_samples_sha256':sha(evidence/'allocation-samples.jsonl'),'sampled_peak_bytes':max(r['retained_bytes'] for r in samples),'allocation_samples':len(samples),'samples_with_concurrent_compilers':sum(bool(r['concurrent_compilers']) for r in samples),'idle_bytes':endpoint['endpoint']['retained_bytes'],'idle_seconds':endpoint['idle_seconds'],'worktrees':count,'cargo_commands':len(commands),'package_cache_wait_messages':package_cache_wait_messages}
    write(evidence/'audit.json',receipt)
    return state,receipt

def audited_cohort(evidence):
    retired=evidence/'retirement.json'
    if not retired.exists():return audit(evidence)
    proof=load(retired)
    require(proof['passed'] and proof['auditor_sha256']==sha(__file__),'Retirement lacks this live auditor')
    require(proof['audit_sha256']==sha(evidence/'audit.json'),'Live audit changed after retirement')
    expected=proof['evidence_manifest']
    require({str(p.relative_to(evidence)) for p in evidence.rglob('*') if p.is_file()}==set(expected)|{'retirement.json'},'Cohort evidence set changed')
    for name,item in expected.items():
        path=evidence/name
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(evidence),'Unsafe cohort evidence path')
        require(sha(path)==item['sha256'] and path.stat().st_size==item['bytes'],'Cohort evidence changed: '+name)
    require(sha(proof['archive'])==proof['archive_sha256'],'Verified cohort archive changed')
    state=load(evidence/'results.json');receipt=load(evidence/'audit.json')
    require(state['state']=='complete' and receipt['results_sha256']==sha(evidence/'results.json'),'Retired cohort incomplete')
    fixture=REPO/'scripts/session_replays'/('disk-1.99.0-1-'+state['cell'].split('-')[0]+'.json')
    require(state['fixture_sha256']==sha(fixture),'Retired cohort fixture changed')
    return state,receipt

def uv_runtime_setup():
    setup=load(REPO/'scripts/benchmark_results/disk.json')['uv_runtime_setup']
    original=REPO/'scripts/session_replays/uv-rust-1.99.json'
    prepared=REPO/'scripts/session_replays/disk-1.99.0-1-uv.json'
    require(sha(REPO/setup['setup_patch'])==setup['setup_patch_sha256'],'UV setup patch changed')
    preparation=load(ROOT/'source-preparation.json')['uv']
    require(preparation['fixture_sha256']==sha(prepared),'UV preparation fixture differs')
    for key in ['derived_base','derived_first_edit']:
        proof=setup[key]
        raw=subprocess.check_output(['git','-C',str(ROOT/'repos/uv.git'),'cat-file','commit',proof['derived_revision']])
        require(hashlib.sha256(raw).hexdigest()==proof['commit_object_sha256'],'UV prepared source object differs')
    setup.update(original_fixture=str(original.relative_to(REPO)),original_fixture_sha256=sha(original),prepared_fixture_sha256=sha(prepared),published_fixture=str(prepared.relative_to(REPO)),published_fixture_sha256=sha(prepared),preparation_script_sha256=sha(HERE/'prepare-disk.py'))
    return setup

def main():
    REPORTS.mkdir(exist_ok=True)
    parser=argparse.ArgumentParser();parser.add_argument('evidence',type=Path,nargs='*');args=parser.parse_args()
    if args.evidence:
        for path in args.evidence:
            state,receipt=audit(path.resolve());print(receipt['cell'],'audit passed')
        return
    cells={};excluded=[]
    selected=load(ROOT/'selected-cohorts.json')
    for path in sorted((ROOT/'evidence').glob('*/results.json')):
        state=load(path)
        if selected.get(state['cell'])!=path.parent.name:
            reason='Disk runner rejected a successful command after package-cache lock waits' if 'Cargo lock contention' in state.get('error','') else 'Superseded by identical cfg_select formatting for both toolchains'
            excluded.append({'cohort':path.parent.name,'state':state['state'],'error':state.get('error'),'reason':reason,'results_sha256':sha(path)})
            continue
        require(state['state']=='complete','Selected cohort incomplete: '+str(path))
        require(state['cell'] not in cells,'Multiple selected runs')
        cells[state['cell']]=audited_cohort(path.parent)
    require(set(cells)=={f'{p}-{l}-{m}' for p in ['ruff','uv'] for l in ['stock','ohm'] for m in ['single','forks']},'All eight cohorts are required')
    previous=load(REPO/'scripts/benchmark_results/disk.json')
    comparisons=[];identities={};hosts=[]
    for project in ['ruff','uv']:
        for mode in ['single','forks']:
            stock,sr=cells[f'{project}-stock-{mode}'];ohm,orr=cells[f'{project}-ohm-{mode}']
            keys=['worktree','phase','index','command','tests_started']
            require([{k:r[k] for k in keys} for r in sr['commands']]==[{k:r[k] for k in keys} for r in orr['commands']],'Paired commands/test counts differ')
            require(sr['source_proofs']==orr['source_proofs'],'Paired source/lockfile content differs')
            for label,state in [('stock-1.99.0',stock),(RELEASE,ohm)]:
                require(label not in identities or identities[label]==state['toolchain_identity'],'Toolchain identity changed between cohorts')
                identities[label]=state['toolchain_identity'];hosts.append(state['host'])
            for number in ([1] if mode=='single' else [2,10]):
                timing='immediate_worktree_completion_checkpoint' if number==2 else 'completed_cohort_idle_at_least_30_seconds'
                pair={l:(s['completed_worktrees'][1]['allocation']['retained_bytes'] if number==2 else s['idle']['endpoint']['retained_bytes']) for l,s in [('stock',stock),('ohm',ohm)]}
                a,b=pair['stock'],pair['ohm'];require(min(a,b)>0,'Invalid allocation')
                comparison={'project':project,'cohort':mode,'worktrees':number,'measurement_timing':timing,'stock_retained_bytes':a,'ohm_retained_bytes':b,'stock_gib':a/1024**3,'ohm_gib':b/1024**3,'bytes_saved':a-b,'percent_less_disk':100*(a-b)/a,'valid_pair':True,'mismatched_fields':[]}
                if number!=2:comparison.update(stock_idle_seconds=sr['idle_seconds'],ohm_idle_seconds=orr['idle_seconds'])
                comparisons.append({'project':project,'scenario':{1:'One complete development session',2:'Two active worktrees',10:'Ten active worktrees'}[number],'measurement_timing':timing,'comparison':comparison})
    require(all(h==hosts[0] for h in hosts),'Disk host changed between pairs')
    receipts=[r for _,r in cells.values()];require(sum(r['cargo_commands'] for r in receipts)==404,'Wrong total commands')
    require(sum(len(r['runtime_checks']) for r in receipts)==22,'Wrong runtime check count')
    report={'schema_version':1,'study':'Ohm 1.99.0-8 retained disk usage in Ruff/ty and uv development','date':datetime.date.today().isoformat(),'metric':previous['metric'],'host':hosts[0],'release_manifest':{'path':'toolchains/1.99.0/8.json','sha256':sha(REPO.parent/'release-install/manifest.json')},'toolchains':identities,'configuration':previous['configuration'],'design':previous['design'],'readme_comparisons':comparisons,'cohorts':[{k:v for k,v in r.items() if k not in ['logs','source_proofs','commands']} for r in receipts],'validation':{'status':'pass','cargo_commands':404,'worktrees':44,'post_endpoint_runtime_checks':22,'paired_sources_explicit_settings_commands_and_test_counts_match':True,'timing_comparisons':False,'concurrent_compiler_activity_invalidates_allocation':False,'samples_with_concurrent_compilers':sum(r['samples_with_concurrent_compilers'] for r in receipts)},'excluded_preparation_attempts':excluded,'provenance':{'exporter_sha256':sha(__file__),'cohort_audits':{cell:sha(Path(r['evidence'])/'audit.json') for cell,(_,r) in cells.items()},'replay_source_audit':receipts,'fixture_compatibility':load(HERE/'fixture-validation.json')},'uv_runtime_setup':uv_runtime_setup(),'native_accounting':{'authoritative':'APFS ATTR_VOL_SPACEUSED, crosschecked against diskutil volume allocation','historical_measurements_modified':False}}
    report['design']['artifact_retirement']='Each isolated volume is audited while mounted, archived with checksums, and retired before the next cohort; final publication rechecks the retained evidence.'
    report['design']['preflight']='Verify capacity; concurrent builds on other volumes are allowed. Each cohort uses an isolated APFS volume. Final endpoints wait at least 30 seconds for this workload, flush, and require stable allocation. Command timings are diagnostic only. Package-cache waits are recorded; build-directory lock contention is rejected.'
    # The repeated-run representation contains new fixture paths and hashes.
    report['workloads']={p:{'path':str(REPO/'scripts/session_replays'/('disk-1.99.0-1-'+p+'.json')),'sha256':r['fixture_sha256']} for p in ['ruff','uv'] for _,r in [cells[p+'-stock-single']]}
    formatting=REPO/'scripts/session_replays/disk-1.99.0-1-setup.json'
    report['formatting_setup']={'path':str(formatting.relative_to(REPO)),'sha256':sha(formatting),'preparation':load(formatting)}
    write(REPORTS/'disk.json',report);print('All disk cohorts audited')
if __name__=='__main__':main()
