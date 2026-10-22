"""Compare published formatter releases with paired source-identical edits."""
from __future__ import annotations
import argparse,hashlib,json,os,random,subprocess,tarfile,time
from pathlib import Path


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value,indent=2)+'\n')


def run(argv, *, cwd: Path, env: dict, log: Path | None=None) -> bytes:
    if log is not None:
        with log.open('xb') as output:
            subprocess.run(argv,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,check=True)
        return b''
    return subprocess.run(argv,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout


def orders(plan: dict, project: str, scenario: str) -> list[list[str]]:
    number=plan['pairs_per_case_and_scenario'];assert number==40
    result=[['control','candidate'],['candidate','control']]*(number//2)
    seed=plan['seed']+[case['project'] for case in plan['cases']].index(project)*10+plan['scenarios'].index(scenario)
    random.Random(seed).shuffle(result)
    return result


def plan_only(plan: dict) -> dict:
    assert plan['baseline']=='ohm-1.99.0-7' and plan['release']=='ohm-1.99.0-8'
    assert plan['warmup_pairs']==2
    assert plan['scenarios']==['unchanged','formatted-comment','leaf-rewrite']
    result={'passed':True,'timing_commands_started':False,'cases':[]}
    for case in plan['cases']:
        assert case['rewrite_before']!=case['rewrite_after']
        for scenario in plan['scenarios']:
            order=orders(plan,case['project'],scenario)
            assert len(order)==40 and sum(pair[0]=='control' for pair in order)==20
            result['cases'].append({'project':case['project'],'scenario':scenario,'pairs':len(order),'order':order})
    assert len(result['cases'])==6
    return result


def environment(campaign: Path, target: Path) -> dict:
    # These directories isolate mutable state; the published defaults stay enabled.
    result={key:value for key,value in os.environ.items() if not key.startswith(('CARGO_','RUST','OHM_'))}
    result.update(PATH=str(campaign/'tools/bin')+':'+str(Path.home()/'.cargo/bin')+':'+result['PATH'],
                  CARGO_HOME='/tmp/codex-cargo-home',CARGO_TARGET_DIR=str(target),CARGO_NET_OFFLINE='true',
                  CARGO_BUILD_JOBS='8',RUSTUP_HOME=str(Path.home()/'.rustup'),GIT_CONFIG_GLOBAL='/dev/null')
    return result


def verify_install(campaign: Path, release: str) -> dict:
    path=campaign/'release-install/verified-install.json';proof=json.loads(path.read_text())
    assert proof['passed'] and proof['release']==release and proof['target']=='x86_64-unknown-linux-gnu'
    selectors={}
    for name,component in proof['components'].items():
        assert digest(Path(component['path']))==component['sha256']
        selected=Path(subprocess.check_output(['rustup','which','--toolchain',release,name],text=True).strip())
        assert selected.resolve()==Path(component['path']).resolve(),(release,name,selected)
        selectors[name]=str(selected)
    archive=campaign/'release-install'/(release+'-x86_64-unknown-linux-gnu.tar.gz')
    assert digest(archive)==proof['archive_sha256']
    binary=Path(proof['components']['cargo']['path']).with_name('cargo-fmt')
    selected=Path(subprocess.check_output(['rustup','which','--toolchain',release,'cargo-fmt'],text=True).strip())
    assert selected.resolve()==binary.resolve()
    selectors['cargo-fmt']=str(selected)
    cargo_fmt_hash=digest(binary);members=[]
    with tarfile.open(archive,'r|gz') as contents:
        for member in contents:
            if member.isfile() and (member.name=='bin/cargo-fmt' or member.name.endswith('/bin/cargo-fmt')):
                with contents.extractfile(member) as stream:
                    assert hashlib.file_digest(stream,'sha256').hexdigest()==cargo_fmt_hash
                members.append(member.name)
    assert len(members)==1,members
    return {'receipt':str(path),'receipt_sha256':digest(path),'release':release,'components':proof['components'],'selectors':selectors,
            'cargo_fmt':{'path':str(binary),'sha256':cargo_fmt_hash,'archive_member':members[0]},
            'archive_sha256':proof['archive_sha256']}


def checkout(source: Path, revision: str, path: Path, env: dict) -> None:
    assert not path.exists()
    run(['git','clone','--shared','--no-checkout',str(source),str(path)],cwd=path.parent,env=env)
    run(['git','-C',str(path),'checkout','--detach',revision],cwd=path.parent,env=env)
    assert run(['git','rev-parse','HEAD'],cwd=path,env=env).decode().strip()==revision
    assert not run(['git','status','--porcelain','--untracked-files=all'],cwd=path,env=env)


def patch(path: Path, env: dict) -> bytes:
    return run(['git','diff','--binary','--no-ext-diff','HEAD'],cwd=path,env=env)


def tracked_hashes(path: Path, env: dict) -> dict[str,str]:
    files=run(['git','ls-files','-z'],cwd=path,env=env).decode().split('\0')
    return {name:digest(path/name) for name in files if name and (path/name).is_file()}


def file_identity(path: Path) -> dict:
    stat=path.stat()
    return {'device':stat.st_dev,'inode':stat.st_ino,'size':stat.st_size,
            'mtime_ns':stat.st_mtime_ns,'ctime_ns':stat.st_ctime_ns}


def main(args) -> None:
    plan=json.loads(args.protocol.read_text());validation=plan_only(plan)
    if args.plan_only:
        print(json.dumps(validation));return
    assert args.project in [case['project'] for case in plan['cases']]
    case=next(case for case in plan['cases'] if case['project']==args.project)
    assert not args.output.exists();args.output.mkdir(parents=True)
    out=args.output;logs=out/'logs';logs.mkdir();(out/'sources').mkdir();(out/'targets').mkdir()
    state={'state':'preparing','project':args.project,'pid':os.getpid(),'started_at':time.time(),
           'protocol_sha256':digest(args.protocol),'runner_sha256':digest(Path(__file__)),
           'source_revision':case['revision'],'source':str(args.source),'host':os.uname().nodename,
           'accepted_pairs':0,'expected_pairs':120,'measurements_started':False}
    def status(stage: str, **fields):
        state.update(state=stage,updated_at=time.time(),**fields);write_json(out/'status.json',state)
    try:
        versions={'control':plan['baseline'],'candidate':plan['release']}
        installations={lane:verify_install(args.previous_campaign if lane=='control' else args.campaign,release) for lane,release in versions.items()}
        write_json(out/'installations.json',installations)
        (out/'protocol.json').write_bytes(args.protocol.read_bytes())
        (out/'runner.py').write_bytes(Path(__file__).read_bytes())
        environments={lane:environment(args.campaign,out/'targets'/lane) for lane in ('oracle','control','candidate')}
        sources={lane:out/'sources'/lane for lane in environments}
        for lane in environments:
            checkout(args.source,case['revision'],sources[lane],environments[lane])
            run(['cargo','+'+versions.get(lane,plan['baseline']),'metadata','--offline','--locked','--no-deps','--format-version','1'],cwd=sources[lane],env=environments[lane],log=logs/(lane+'-metadata.log'))
        run(['cargo','+'+plan['baseline'],'fmt','-p',case['package']],cwd=sources['oracle'],env=environments['oracle'],log=logs/'oracle-format.log')
        baseline_patch=patch(sources['oracle'],environments['oracle']);(out/'baseline.patch').write_bytes(baseline_patch)
        baseline=(sources['oracle']/case['path']).read_bytes();assert baseline.count(case['rewrite_before'].encode())==1
        (out/'baseline.rs').write_bytes(baseline)
        baseline_hashes=tracked_hashes(sources['oracle'],environments['oracle'])
        write_json(out/'baseline-hashes.json',baseline_hashes)
        def restore(lane: str):
            path=sources[lane];env=environments[lane]
            run(['git','reset','--hard',case['revision']],cwd=path,env=env)
            if baseline_patch:
                run(['git','apply',str(out/'baseline.patch')],cwd=path,env=env)
            assert patch(path,env)==baseline_patch
        def formatter(lane: str, log: Path, timed: bool) -> dict:
            command=['cargo','+'+versions[lane],'fmt','-p',case['package']]
            with log.open('xb') as output:
                before=time.time_ns();start=time.perf_counter_ns()
                result=subprocess.run(command,cwd=sources[lane],env=environments[lane],stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT)
                elapsed=(time.perf_counter_ns()-start)/1e9;after=time.time_ns()
                result.check_returncode()
            return {'command':command,'seconds':elapsed,'started_at_ns':before,'finished_at_ns':after,'timed':timed,'log':str(log.relative_to(out))}
        # Both published lanes must format the canonical baseline identically before timing.
        for lane in versions:
            restore(lane);formatter(lane,logs/(lane+'-canonical.log'),False)
            assert patch(sources[lane],environments[lane])==baseline_patch
            assert tracked_hashes(sources[lane],environments[lane])==baseline_hashes
        status('ready for quiet gate')
        import sys
        sys.path.insert(0,str(args.campaign/'controller'))
        import host_guard
        attempt=0
        while True:
            receipt=out/('preflight-'+str(attempt)+'.json')
            try:
                host_guard.quiet(out,receipt)
                break
            except RuntimeError:
                if not receipt.exists():raise
                gate=json.loads(receipt.read_text())
                if gate['passed'] or not gate['samples']:raise
                status('waiting for quiet host',quiet_attempt=attempt)
                time.sleep(60);attempt+=1
        status('running',measurements_started=True,accepted_preflight=receipt.name,
               accepted_preflight_sha256=digest(receipt))
        samples=[];all_pairs=[]
        for scenario in plan['scenarios']:
            sequence=[['control','candidate'],['candidate','control']]+orders(plan,args.project,scenario)
            for index,order in enumerate(sequence):
                warmup=index<plan['warmup_pairs'];pair_index=index-plan['warmup_pairs']
                identity=f'{scenario}-{index:02d}'
                comment=b'' if scenario=='unchanged' else ('\n// Formatting comparison '+args.project+' '+identity+'.\n').encode()
                expected=baseline+comment
                edited=expected if scenario!='leaf-rewrite' else expected.replace(case['rewrite_before'].encode(),case['rewrite_after'].encode(),1)
                pair={'scenario':scenario,'pair':pair_index,'warmup':warmup,'order':order,'input_sha256':hashlib.sha256(edited).hexdigest(),'expected_output_sha256':hashlib.sha256(expected).hexdigest(),'lanes':{}}
                status('running',scenario=scenario,pair=pair_index,order=order)
                for lane in order:
                    restore(lane)
                    formatter(lane,logs/(identity+'-'+lane+'-warm.log'),False)
                    assert patch(sources[lane],environments[lane])==baseline_patch
                    if scenario!='unchanged':
                        (sources[lane]/case['path']).write_bytes(edited)
                    if lane==order[0]:
                        (out/(identity+'-input.rs')).write_bytes(edited)
                    before_file=file_identity(sources[lane]/case['path'])
                    pair['lanes'][lane]=formatter(lane,logs/(identity+'-'+lane+'-measured.log'),not warmup)
                    after_file=file_identity(sources[lane]/case['path'])
                    if scenario=='unchanged':assert before_file==after_file,'Unchanged source was rewritten'
                    output=(sources[lane]/case['path']).read_bytes();assert output==expected,(scenario,lane,'unexpected formatted bytes')
                    assert (output!=edited)==(scenario=='leaf-rewrite')
                    actual_hashes=tracked_hashes(sources[lane],environments[lane]);expected_hashes=dict(baseline_hashes);expected_hashes[case['path']]=hashlib.sha256(expected).hexdigest()
                    assert actual_hashes==expected_hashes,'Formatter changed another tracked file'
                    actual_patch=patch(sources[lane],environments[lane]);(out/(identity+'-'+lane+'.patch')).write_bytes(actual_patch)
                    pair['lanes'][lane].update(output_sha256=hashlib.sha256(output).hexdigest(),patch_sha256=hashlib.sha256(actual_patch).hexdigest(),all_other_tracked_files_unchanged=True,
                                              target_before=before_file,target_after=after_file)
                assert pair['lanes']['control']['patch_sha256']==pair['lanes']['candidate']['patch_sha256']
                all_pairs.append(pair);write_json(out/'all-pairs.json',all_pairs)
                if not warmup:
                    samples.append(pair);state['accepted_pairs']=len(samples);write_json(out/'samples-provisional.json',samples)
        assert len(samples)==120 and all(sum(p['scenario']==s for p in samples)==40 for s in plan['scenarios'])
        for lane,release in versions.items():
            assert verify_install(args.previous_campaign if lane=='control' else args.campaign,release)==installations[lane]
        # The caller accepts these only after the full outer monitor also succeeds.
        write_json(out/'result.json',{'schema_version':1,'project':args.project,'protocol':plan,'source_revision':case['revision'],'host':os.uname().nodename,'samples':samples,'warmup_pairs_retained':6,'outer_monitor_acceptance_required':True,'proof_limits':plan['limits']})
        status('measurements complete, pending outer monitor',completed_at=time.time())
    except BaseException as error:
        status('failed',error=repr(error));raise


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--protocol',type=Path,required=True)
    parser.add_argument('--plan-only',action='store_true')
    parser.add_argument('--project',choices=['uv','ruff'])
    parser.add_argument('--campaign',type=Path)
    parser.add_argument('--previous-campaign',type=Path)
    parser.add_argument('--source',type=Path)
    parser.add_argument('--output',type=Path)
    main(parser.parse_args())
