"""Replay the published single-worktree and ten-worktree APFS study."""
import argparse, fcntl, hashlib, json, os, resource, shutil, subprocess, sys, threading, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import apfs_meter as meter

ROOT=Path('/private/tmp/ohm-benchmarks-1.99.0-7/apfs/disk')
REPO=Path('/private/tmp/ohm-benchmarks-1.99.0-7/ohm')
sys.path.insert(0,str(REPO/'scripts'))
import replay_sessions as replay

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):path.write_text(json.dumps(value,indent=2,default=str)+'\n')
def git(source,*args,**kwargs):return subprocess.check_output(['git','-C',str(source),*args],**kwargs)
def reserve():
    free=shutil.disk_usage(ROOT).free
    if free<60*1024**3:raise RuntimeError('Backing disk free space below 60 GiB')
    return free
def preflight(path):
    write(path,{'time':time.time(),'compilers':replay.competing_processes(),'free_bytes':reserve(),'quiet_required':False,'metric':'isolated APFS volume allocation'})

class DiskReplay(replay.Replay):
    def run_command(self,scenario,worktree,step,label,selector,repetition,index,*,phase='session'):
        # Package-cache waits change elapsed time, not allocation on this volume.
        # Keep the timing runner's strict checks unchanged.
        assert not self.options.require_idle
        arguments=self.command(step,selector)
        directory=worktree/step.get('cwd','.')
        if not directory.is_dir() or not directory.resolve().is_relative_to(worktree.resolve()):
            raise replay.BenchmarkError('Invalid command directory: '+str(directory))
        started=time.perf_counter()
        result=subprocess.run(arguments,cwd=directory,env=self.environment(scenario,label,selector,repetition),text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=self.options.timeout,check=False)
        duration=time.perf_counter()-started
        logs=self.output/'logs'/scenario.project/label/str(repetition);logs.mkdir(parents=True,exist_ok=True)
        log=logs/(('warmup-' if phase=='warmup' else '')+f'{index:02d}.log');log.write_text(result.stdout)
        reported=[m.group('crate') for m in replay.CARGO_STATUS.finditer(result.stdout)]
        invocations=replay.compiler_invocations(result.stdout) if self.options.compiler_accounting=='verbose' else None
        waits=[line.strip() for line in result.stdout.splitlines() if 'blocking waiting for file lock' in line.lower()]
        sample={'kind':'command','wall_seconds':duration,'command':arguments,'returncode':result.returncode,'cargo_reported_crates':reported,'actual_compiler_invocations':invocations,'cargo_status_without_compiler_invocation':replay.status_only_crates(reported,invocations) if invocations is not None else None,'tests_started':sum(int(m.group(1)) for m in replay.TEST_COUNT.finditer(result.stdout)),'external_compilation':None,'wall_seconds_are_performance_measurement':False,'package_cache_waits':waits,'log':str(log)}
        if result.returncode:raise replay.BenchmarkError(f'{scenario.project} {label} step {index} exited {result.returncode}; inspect {log}')
        if any(line.lower()!='blocking waiting for file lock on package cache' for line in waits):
            raise replay.BenchmarkError('Unexpected build-directory lock contention; inspect '+str(log))
        is_test=(step['program']=='just' and step['args'][0]=='test') or (step['program']=='cargo' and (step['args'][0]=='test' or step['args'][:2]==['nextest','run']))
        if is_test and sample['tests_started']==0:raise replay.BenchmarkError('Test command selected zero tests; inspect '+str(log))
        return sample
    def environment(self,scenario,label,selector,repetition):
        env=super().environment(scenario,label,selector,repetition)
        for key in list(env):
            if key.startswith('__CARGO_') or key in ('CARGO_UNSTABLE_HEADSTART','CARGO_UNSTABLE_OHM_DEFAULTS'):
                env.pop(key)
        env['PATH']=str(ROOT/'tools/bin')+':'+str(Path.home()/'.local/bin')+':'+str(Path.home()/'.cargo/bin')+':'+env['PATH']
        env['CARGO_HOME']='/private/tmp/codex-cargo-home'
        env['CARGO_TARGET_DIR']=str(self.mount/'targets'/str(repetition))
        env['TMPDIR']=str(self.mount/'tmp')
        env['UV_CACHE_DIR']=str(self.mount/'runtime/uv')
        env['XDG_CACHE_HOME']=str(self.mount/'runtime/xdg')
        env['CARGO_INCREMENTAL']='1'
        env['CARGO_TERM_COLOR']='never'
        env['UV_PYTHON']=str(Path.home()/'.local/bin/python3.12')
        env['UV_PYTHON_DOWNLOADS']='never'
        env.pop('PYTHONSAFEPATH',None)
        if scenario.project=='uv':
            env['CARGO_BIN_EXE_uv']=str(self.mount/'targets'/str(repetition)/'debug/uv')
        if label=='ohm':
            env['CARGO_BUILD_BUILD_DIR']=str(self.mount/'shared-build')
            env['CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST']='all'
        return env

def source_state(worktree):
    assert git(worktree,'config','user.email').decode().strip()=='charlie.r.marsh@gmail.com'
    indexes=ROOT/'source-indexes';indexes.mkdir(exist_ok=True)
    index=indexes/hashlib.sha256(str(worktree).encode()).hexdigest()
    env=os.environ|{'GIT_INDEX_FILE':str(index)}
    git(worktree,'read-tree','HEAD',env=env)
    git(worktree,'add','--all','--','.',env=env)
    tree=git(worktree,'write-tree',env=env).decode().strip()
    return {'head':git(worktree,'rev-parse','HEAD').decode().strip(),'tree':tree,'tracked_diff_sha256':hashlib.sha256(git(worktree,'diff','--binary','HEAD',tree)).hexdigest(),'lockfile_sha256':digest(worktree/'Cargo.lock'),'status':git(worktree,'status','--short').decode()}

from private_layout import private_inode_audit, binary_scope

def cohort(project,label,mode,attempt=1):
    from release_guard import verify_release
    verify_release()
    cell=f'{project}-{label}-{mode}'
    storage=cell if attempt==1 else cell+'-attempt'+str(attempt)
    evidence=ROOT/'evidence'/storage
    if evidence.exists():raise RuntimeError('Cohort already exists; inspect before restarting: '+cell)
    preflight_path=ROOT/(cell+'-preflight-'+str(time.time_ns())+'.json')
    preflight(preflight_path)
    evidence.mkdir(parents=True)
    shutil.copyfile(preflight_path,evidence/'preflight.json')
    instrumentation=evidence/'instrumentation';instrumentation.mkdir()
    for path in [Path(__file__),Path(meter.__file__),Path(replay.__file__),Path(__file__).with_name('private_layout.py')]:shutil.copyfile(path,instrumentation/path.name)
    fixture='disk-1.99.0-1-'+project+'.json'
    scenario=replay.load_scenario(REPO/'scripts/session_replays'/fixture)
    source=ROOT/'repos'/(project+'.git')
    selector='ohm-1.99.0-7' if label=='ohm' else '1.99.0'
    version=subprocess.check_output(['rustc','+'+selector,'--version'],text=True).strip()
    if '1.99.0' not in version or (label=='ohm' and '(ohm-1.99.0-7)' not in version):raise RuntimeError('Unexpected compiler '+version)
    identity={}
    for name in ['rustc','cargo','clippy-driver','rustfmt']:
        binary=Path(subprocess.check_output(['rustup','which','--toolchain',selector,name],text=True).strip())
        identity[name]={'path':str(binary),'sha256':digest(binary),'version':subprocess.check_output([str(binary),'--version'],text=True).strip()}
    host={'model':subprocess.check_output(['sysctl','-n','hw.model'],text=True).strip(),'logical_cpus':int(subprocess.check_output(['sysctl','-n','hw.ncpu'])),'ram_gib':int(subprocess.check_output(['sysctl','-n','hw.memsize']))/1024**3,'os':'macOS '+subprocess.check_output(['sw_vers','-productVersion'],text=True).strip(),'target':'aarch64-apple-darwin'}
    mount=Path('/private/tmp/codex-cargo-targets/ohm/isolated/release-1.99.0-7/apfs')/storage
    volume=meter.create(ROOT/'images'/(storage+'.sparseimage'),mount,'Ohm99-'+storage)
    write(evidence/'volume.json',volume)
    baseline=volume['baseline']['endpoint']['native_bytes']
    for name in ('tmp','runtime','worktrees','targets'):(mount/name).mkdir()
    options=replay.parser().parse_args(['--project',project,'--scenario',str(scenario.path),'--output-dir',str(evidence),'--upstream','1.99.0','--ohm','ohm-1.99.0-7','--jobs','8','--offline','--minimum-free-gb','60','--compiler-accounting','verbose'])
    study=DiskReplay(options);study.mount=mount
    state={'cell':cell,'attempt':attempt,'fixture':str(scenario.path),'fixture_sha256':digest(scenario.path),'runner_sha256':digest(__file__),'meter_sha256':digest(meter.__file__),'selector':selector,'compiler':version,'toolchain_identity':identity,'host':host,'measurement_policy':{'quiet_required':False,'timings_compared':False,'isolated_apfs_volume':True},'baseline_bytes':baseline,'steps':[],'completed_worktrees':[],'seeds':[],'state':'running'}
    stopped=threading.Event();sampling_error=[]
    def sample_background():
        try:
            with (evidence/'allocation-samples.jsonl').open('x') as output:
                while not stopped.is_set():
                    row=meter.sample(mount,baseline,crosscheck=False);row['free_bytes']=reserve();row['concurrent_compilers']=replay.competing_processes()
                    output.write(json.dumps(row)+'\n');output.flush();stopped.wait(1)
        except BaseException as error:sampling_error.append(repr(error));stopped.set()
    thread=threading.Thread(target=sample_background,daemon=True);thread.start()
    def checkpoint(kind,index,worktree,detail):
        if sampling_error:raise RuntimeError('Allocation sampler failed: '+repr(sampling_error))
        row={'kind':kind,'index':index,'worktree':worktree,'detail':detail,'allocation':meter.sample(mount,baseline),'free_bytes':reserve()}
        state['steps'].append(row);write(evidence/'results.json',state)
    def commands(worktree,number,steps,phase='session',offset=0):
        for index,step in enumerate(steps,start=offset+1):
            reserve();print(cell,number,phase,index,step['label'],flush=True)
            if step['kind']=='edit':
                observed=study.apply_edit(scenario,source,worktree,step)
                observed['patch_sha256']=hashlib.sha256(study.patch_bytes(scenario,source,step)).hexdigest()
                observed['source']=source_state(worktree)
            else:
                observed=study.run_command(scenario,worktree,step,label,selector,number,index,phase=phase)
                observed['log_sha256']=digest(observed['log'])
            observed['label']=step['label'];observed['phase']=phase
            checkpoint(step['kind'],index,number,observed)
    try:
        donor=mount/'worktrees/1'
        git(source,'worktree','add','--detach',str(donor),scenario.base_revision)
        checkpoint('create',0,1,source_state(donor))
        commands(donor,1,scenario.warmup,phase='warmup')
        if mode=='single':
            commands(donor,1,scenario.steps)
            state['completed_worktrees'].append({'number':1,'source':source_state(donor),'allocation':meter.sample(mount,baseline)})
        else:
            edits=[i for i,s in enumerate(scenario.steps) if s['kind']=='edit'];split=edits[1]
            commands(donor,1,scenario.steps[:split])
            first_edit=scenario.steps[edits[0]]['commit']
            state['donor']=source_state(donor)
            assert state['donor']['tree']==git(source,'rev-parse',first_edit+'^{tree}').decode().strip(),'Donor differs from first-edit checkpoint'
            state['completed_worktrees'].append({'number':1,'source':source_state(donor),'allocation':meter.sample(mount,baseline)})
            for number in range(2,11):
                study.wait_until_idle();reserve()
                worktree=mount/'worktrees'/str(number)
                if label=='ohm':
                    args=['cargo','+'+selector,'worktree','add','--detach',str(worktree),'--target-dir',str(mount/'targets'/str(number)),first_edit]
                    result=subprocess.run(args,cwd=donor,env=study.environment(scenario,label,selector,1),text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                    log=evidence/('seed-'+str(number)+'.log');log.write_text(result.stdout)
                    if result.returncode or 'Seeded ' not in result.stdout:raise RuntimeError('Workspace seed failed: '+str(log))
                    state['seeds'].append({'number':number,'log':str(log),'sha256':digest(log),'command':args})
                else:git(source,'worktree','add','--detach',str(worktree),first_edit)
                checkpoint('create',0,number,source_state(worktree))
                commands(worktree,number,scenario.steps[split:],offset=split)
                state['completed_worktrees'].append({'number':number,'source':source_state(worktree),'allocation':meter.sample(mount,baseline)})
                write(evidence/'results.json',state)
            assert source_state(donor)==state['donor'],'Frozen donor changed'
        state['idle']=meter.stable(mount,baseline,idle_seconds=30)
        state['private_inode_audit']=private_inode_audit(mount,label)
        if label=='ohm':
            namespaces=state['private_inode_audit']['namespaces']
            assert sum(n.startswith('workspace/') for n in namespaces)==(10 if mode=='forks' else 1)
        environment=study.environment(scenario,label,selector,1)
        keys={'CARGO_HOME','CARGO_TARGET_DIR','CARGO_BUILD_BUILD_DIR','CARGO_BUILD_JOBS','CARGO_INCREMENTAL','CARGO_NET_OFFLINE','CARGO_TERM_COLOR','CARGO_TERM_VERBOSE','CARGO_BIN_EXE_uv','CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST','CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST','CARGO_UNSTABLE_OHM_READY_TESTS','CARGO_PROFILE_DEV_OPT_LEVEL','CARGO_PROFILE_DEV_LTO','CARGO_PROFILE_DEV_DEBUG','UV_CACHE_DIR','UV_PYTHON','UV_PYTHON_DOWNLOADS','INSTA_FORCE_PASS','INSTA_UPDATE','MDTEST_UPDATE_SNAPSHOTS','RUSTUP_TOOLCHAIN','TMPDIR','XDG_CACHE_HOME','PATH'}
        state['environment']={k:v for k,v in environment.items() if k in keys}
        state['state']='complete'
    except BaseException as error:
        state['state']='failed';state['error']=repr(error);raise
    finally:
        stopped.set();thread.join(10)
        if sampling_error:state['sampler_error']=sampling_error;state['state']='failed'
        write(evidence/'results.json',state)
    if state['state']!='complete':raise RuntimeError('Cohort did not complete')
    print('COMPLETE',cell,flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('project',choices=['ruff','uv']);parser.add_argument('label',choices=['stock','ohm']);parser.add_argument('mode',choices=['single','forks']);parser.add_argument('--attempt',type=int,default=1);args=parser.parse_args()
    if args.attempt<1:raise SystemExit('Attempt must be positive')
    for key in list(os.environ):
        if key.startswith(('CARGO_PROFILE_','CARGO_UNSTABLE_','__CARGO_')) or key in ('RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','CARGO_BUILD_RUSTFLAGS','CARGO_BUILD_TARGET','RUSTC','RUSTDOC','RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','RUSTC_BOOTSTRAP','CARGO_BUILD_RUSTC','CARGO_BUILD_INCREMENTAL','RUSTFMT','RUSTFMT_WRAPPER','RUSTDOCFLAGS','CARGO_ENCODED_RUSTDOCFLAGS','PYTHONSAFEPATH'):os.environ.pop(key)
    soft,hard=resource.getrlimit(resource.RLIMIT_NOFILE);resource.setrlimit(resource.RLIMIT_NOFILE,(min(65536,hard),hard))
    lock=(ROOT/'run.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    cohort(args.project,args.label,args.mode,args.attempt)
