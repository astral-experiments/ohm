"""Price one unmodified historical Ruff edit and keep its independent native verdicts."""
from contextlib import ExitStack
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import tomllib

HERE=Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from audit import exec_roster, incremental, run, save, sha
import contact
import profile_work
import zipfile

ROOT=Path(os.environ['RUNNER_TEMP'])/'ruff-db-link-reason'
SRC=Path(os.environ['GITHUB_WORKSPACE'])/'ruff'
LOG=ROOT/'records'
SDK=ROOT/'sdk'
HOST='x86_64-unknown-linux-gnu'
OLD='a8d0fffc4d72da193b2a2ae4c53277fdf1f1794d'
NEW='88d851449d2345e11da991794f3e9bfbbd666719'
LOCK='dbd2643768bb47fb06e289d2cd1a887da1deb9dad8fc535aa055cd83936d1145'
OWNERS=('ruff_source_file','ruff_db','ruff_linter')
CMD=['cargo','+ohm','build','-p','ruff','--bin','ruff','--locked','--offline','-j4','--message-format=json']


def git(*args):
    return subprocess.check_output(['git','-C',SRC,*args]).decode().strip()


def gz(path,data):
    path.write_bytes(gzip.compress(data,compresslevel=2,mtime=0))


def clock(path):
    row=json.loads(path.read_text())
    assert row['code']==0 and row['event_errno']==0 and row['instructions']>0 and row['running']==row['enabled']>0,row
    return row['instructions']


def storage(state):
    cp=subprocess.run(['du','-s','-B1',str(state)],capture_output=True,check=True)
    apparent=subprocess.run(['du','-s','-B1','--apparent-size',str(state)],capture_output=True,check=True)
    return {'allocated':int(cp.stdout.split()[0]),'apparent':int(apparent.stdout.split()[0]),'free_bytes':shutil.disk_usage(ROOT).free}


def env_and_calibrate():
    assert os.environ['GITHUB_REPOSITORY']=='astral-experiments/ohm' and os.environ['GITHUB_REF']=='refs/heads/charlie/qa-ruff-line-end-25492-20261102'
    assert os.environ['GITHUB_RUN_ATTEMPT']=='1' and platform.machine()=='x86_64'
    catalog=json.loads((LOG/'catalog.json').read_text())
    assert catalog['id']==13144147426 and catalog['digest']=='sha256:3de34fa8799dbc8f05069bf7916012597061a9adc69b0ff0898aca936d16ee68'
    assert json.loads((LOG/'tools.json').read_text())['head']==os.environ['GITHUB_SHA']
    assert git('rev-parse','HEAD')==NEW and git('rev-parse',NEW+'^')==OLD
    assert git('diff','--name-status',OLD,NEW)=='M\tcrates/ruff_source_file/src/line_index.rs'
    assert sha(SRC/'Cargo.lock')==LOCK
    private=ROOT/'study';private.mkdir()
    for d in ('home','rustup','cargo','tmp','proxies'):(private/d).mkdir()
    real=Path(shutil.which('rustup')).resolve()
    for name in ('cargo','rustc','rustdoc','rustup'):
        (private/'proxies'/name).symlink_to(real)
    env={'HOME':str(private/'home'),'RUSTUP_HOME':str(private/'rustup'),'CARGO_HOME':str(private/'cargo'),
         'TMPDIR':str(private/'tmp'),'PATH':str(private/'proxies')+':/usr/bin:/bin','RUSTUP_AUTO_INSTALL':'0',
         'CARGO_TERM_COLOR':'never','CARGO_CACHE_AUTO_CLEAN_FREQUENCY':'never','LC_ALL':'C.UTF-8','TZ':'UTC',
         'CARGO_NET_GIT_FETCH_WITH_CLI':'true'}
    run(['rustup','toolchain','link','ohm',SDK],env,private)
    assert Path(run(['rustup','which','--toolchain','ohm','rustc'],env,private).stdout.decode().strip()).samefile(SDK/'bin/rustc')
    available=sorted(os.sched_getaffinity(0))
    assert len(available)>=4
    os.sched_setaffinity(0,available[:4])
    specs={'head':os.environ['GITHUB_SHA'],'run':os.environ['GITHUB_RUN_ID'],'old':OLD,'new':NEW,'lock':LOCK,'env':env,
             'uname':platform.uname()._asdict(),'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
             'allowed_cpus':available,'selected_cpus':sorted(os.sched_getaffinity(0)), 'cpuinfo':Path('/proc/cpuinfo').read_text().split('\n\n')[0],
             'rustc':run(['rustc','+ohm','-vV'],env,private).stdout.decode(),'cargo':run(['cargo','+ohm','-vV'],env,private).stdout.decode()}
    save(LOG/'admission.json',specs)
    for file,digest,out in [('watch.c','ee82d0f9f0410861f3680c7ebf7f26547cd3a73833290d7272e83b4e29e0d903','watch'),
                             ('calibrate.c','dacd1dd7fef85cacb44a236e0c4191d95db036a623b2a01ae3a5d76d2f3d0b0e','loop')]:
        assert sha(HERE/file)==digest
        run(['cc','-O2','-Wall','-Wextra','-pthread',HERE/file,'-o',private/out],env,private)
    admitted=[]
    for m,copies in [('0',1),('1',2),('thread',2)]:
        values=[]
        for i,n in enumerate([100000,800000,800000,100000]):
            cp=LOG/f'calibration-{m}-{i}.json'
            run([private/'watch',cp,private/'loop',m,str(n),str(copies)],env,private)
            values.append(clock(cp))
        delta=statistics.mean(values[1:3])-statistics.mean([values[0],values[3]])
        expected=2*copies*700000
        assert abs(delta-expected)<max(18000,.025*expected),(m,delta,expected)
        admitted.append([m,copies,values,delta,expected])
    save(LOG/'clocks.json',{'actual':admitted,'sampler':None})
    return private,env


def fetch(private,env):
    git('checkout','--detach',OLD)
    assert git('status','--porcelain','--untracked-files=no')=='' and sha(SRC/'Cargo.lock')==LOCK
    out=ROOT/'registry-setup'
    run(['cargo','+ohm','fetch','--locked'],{**env,'CARGO_TARGET_DIR':str(out/'target'),'CARGO_BUILD_BUILD_DIR':str(out/'build')},SRC)
    lock=tomllib.loads((SRC/'Cargo.lock').read_text())
    actual={p.name:p for p in (private/'cargo/registry/cache').glob('*/*.crate')}
    expected={p['name']+'-'+p['version']+'.crate':p['checksum'] for p in lock['package'] if 'checksum' in p}
    assert len(expected)==488 and set(actual)==set(expected),(len(actual),len(expected),sorted(set(expected)-set(actual))[:8],sorted(set(actual)-set(expected))[:8])
    for name,h in expected.items():assert sha(actual[name])==h,name
    gits=[p['source'] for p in lock['package'] if p.get('source','').startswith('git+')]
    assert len(gits)==1
    folders=[p.parent for p in (private/'cargo/git/checkouts').glob('*/*/.git')]
    heads=[run(['git','-C',p,'rev-parse','HEAD'],env,private).stdout.decode().strip() for p in folders]
    assert gits[0].rsplit('#',1)[1] in heads,(gits,heads)
    save(LOG/'registry.json',{'lock':LOCK,'crates':expected,'git_source':gits,'git_checkout_heads':heads})


def source_variants(phase,products,compilers):
    variants={(): 'no-features', ('get-size','serde'): 'get-size+serde'}
    libs={}
    for r in products:
        if r['target']['name']=='ruff_source_file':
            label=variants[tuple(sorted(r['features']))]
            lib,=[Path(f) for f in r['filenames'] if f.endswith('.rlib')]
            assert label not in libs
            libs[label]=lib
    assert sorted(libs)==sorted(variants.values())
    seen={};literal=[]
    for proc in compilers:
        a=proc['args']
        if proc['crate']=='ruff_source_file' and not proc['link_only']:
            features=tuple(sorted(f[len('feature="'):-1] for flag,f in zip(a,a[1:]) if flag=='--cfg' and f.startswith('feature="') and f.endswith('"')))
            label=variants[features]
            extra,=[v.split('=',1)[1] for v in a if v.startswith('extra-filename=')]
            assert libs[label].name=='libruff_source_file'+extra+'.rlib' and label not in seen
            seen[label]=proc['pid']
        if proc['crate']=='ruff' and '--crate-type' in a and a[a.index('--crate-type')+1]=='bin':
            paths=[Path(v.split('=',1)[1]) for flag,v in zip(a,a[1:]) if flag=='--extern' and v.startswith('ruff_source_file=')]
            archives=[p for p in paths if p.suffix=='.rlib']
            if archives:
                assert archives==[libs['get-size+serde']]
                assert all(p.with_suffix('.rlib')==libs['get-size+serde'] for p in paths)
                literal.append({'pid':proc['pid'],'paths':list(map(str,paths))})
    if phase in ('old','clean'):
        assert set(seen)==set(libs) and len(literal)==1,(phase,seen,literal)
    return libs,{'libraries':{k:str(v) for k,v in libs.items()},'physical_compilers':seen,'physical_cli_externs':literal}


def witness(folder,env,products,rows,old,libs):
    root,={Path(r['executable']) for r in products if r.get('executable') and r['target']['name']=='ruff' and 'bin' in r['target']['kind']}
    dirs={Path(f).parent for r in products for f in r['filenames'] if f.endswith(('.rlib','.rmeta','.so'))}
    native={d for r in rows if r['reason']=='build-script-executed' for d in r['linked_paths']}
    expected='lf 1 3\ncrlf '+('2' if old else '1')+' 4\ncr 1 3\nunicode '+('3' if old else '2')+' 6\n'
    typed={};commands={}
    for label,lib in sorted(libs.items()):
        argv=['rustc','+ohm','--edition=2024','--crate-name','line_end_reader',HERE/'witness.rs','--extern','ruff_source_file='+str(lib)]
        for d in sorted(dirs):argv+=['-L','dependency='+str(d)]
        for d in sorted(native):argv+=['-L',d]
        binary=folder.parent.parent/'study'/('line-reader-'+label)
        argv+=['-o',binary]
        commands[label]=list(map(str,argv))
        run(argv,env,SRC)
        result=run([binary],env,SRC)
        assert result.stdout.decode()==expected and not result.stderr,(result.stdout,result.stderr)
        typed[label]=result.stdout.decode()
    save(folder/'reader.argv.json',commands)
    version=run([root,'--version'],env,SRC)
    assert version.stdout.startswith(b'ruff ')
    cli=[root,'check','--isolated','--no-cache','--select','F401','--output-format','json','--stdin-filename','registered-crlf.py','-']
    cases=[]
    for input_bytes,status in [(b'import sys\r\n',1),(b'import sys\r\nprint(sys.version)\r\n',0)]:
        cmd=run(cli,env,SRC,exact=status,data=input_bytes)
        found=json.loads(cmd.stdout)
        assert [d['code'] for d in found]==(['F401'] if status else []) and not cmd.stderr,(found,cmd.stderr)
        cases.append({'input':input_bytes.decode(),'exit':status,'json':found})
    # This unmetered notebook exercises the production JSON caller for a deletion
    # at a cell boundary. Save what the CLI actually returns for both cell shapes.
    for cells in (['import sys\r'],['import sys\r','pass']):
        notebook={'nbformat':4,'nbformat_minor':2,'metadata':{'language_info':{'name':'python'}},
                  'cells':[{'cell_type':'code','execution_count':None,'metadata':{},'outputs':[],'source':v} for v in cells]}
        nb_cli=[str(a).replace('registered-crlf.py','registered-crlf.ipynb') for a in cli]
        cp=run(nb_cli,env,SRC,exact=1,data=json.dumps(notebook).encode())
        nb=json.loads(cp.stdout)
        assert [d['code'] for d in nb]==['F401'] and not cp.stderr,(nb,cp.stderr)
        cases.append({'notebook_cells':cells,'exit':1,'json':nb})
    verdict={'typed':typed['get-size+serde'],'typed_by_features':typed,'cli_cases':cases,'cli_version':version.stdout.decode(),'cli_sha256':sha(root),
             'archive_sha256s':{k:sha(v) for k,v in libs.items()}}
    save(folder/'verdict.json',verdict)
    return verdict


def case(phase,private,base_env,state,old=None,retain=None,profiler=None):
    folder=LOG/phase;folder.mkdir()
    trace=private/('trace-'+phase);trace.mkdir()
    state.mkdir(exist_ok=True)
    env={**base_env,'CARGO_TARGET_DIR':str(state/'target'),'CARGO_BUILD_BUILD_DIR':str(state/'build'),'CARGO_NET_OFFLINE':'true'}
    assert sha(SRC/'Cargo.lock')==LOCK and git('rev-parse','HEAD')==(OLD if phase=='old' else NEW)
    assert git('status','--porcelain','--untracked-files=no')==''
    argv=['strace','-ff','-qq','-v','-s','131072','-e','trace=execve,execveat,clone,clone3,fork,vfork','-o',trace/'exec','--']
    if profiler:
        assert phase=='edit'
        argv+=profile_work.record(profiler,private/'edit.data',env)
    cp=folder/'clock.json'
    argv += [private/'watch',cp,*CMD]
    save(folder/'command.json',{'argv':list(map(str,argv)),'env':env,'source':git('rev-parse','HEAD'),'prior_storage':storage(state)})
    p=run(argv,env,SRC,exact=None)
    gz(folder/'cargo.stdout.gz',p.stdout);gz(folder/'cargo.stderr.gz',p.stderr)
    if p.returncode!=0:
        raise RuntimeError((phase,p.returncode,p.stderr[-2800:].decode(errors='replace')))
    price=clock(cp)
    procs,links=exec_roster(trace,folder,SDK,HOST,private,env)
    rows=[json.loads(l) for l in p.stdout.splitlines()]
    assert rows[-1]=={'reason':'build-finished','success':True}
    products=[r for r in rows if r['reason']=='compiler-artifact']
    assert len(products)>150
    assert all(r['target']['src_path'] for r in products)
    libs,units=source_variants(phase,products,procs)
    save(folder/'source-units.json',units)
    contact.outputs(products,procs,folder)
    sampled=profile_work.write(folder,private,env,profiler,trace,procs,links,price) if profiler else None
    if phase in ('old','clean'):
        assert all(not r['fresh'] for r in products)
        assert set(OWNERS)<={r['crate'] for r in procs if not r['link_only']}
    ledger=incremental(state,OWNERS,old,retain)
    save(folder/'objects.json',ledger)
    target_sizes={key:storage(state/key) for key in ('target','build') if (state/key).is_dir()}
    layouts={}
    for product in products:
        parts={part for path in product['filenames'] for part in Path(path).parts if part.startswith('v2-') and len(part)==19}
        for part in parts:layouts[part]=layouts.get(part,0)+1
    assert layouts
    summary={'price':price,'dirty':sorted(r['target']['name'] for r in products if not r['fresh']),
             'roster':sorted([r['crate'],r['link_only']] for r in procs),'wild':len(links),'products':len(products),
             'sampled':sampled,'native_output_namespaces':layouts,'storage':{'overall':storage(state),'roots':target_sizes}}
    save(folder/'summary.json',summary)
    verdict=witness(folder,env,products,rows,phase=='old',libs)
    return summary,ledger,verdict


def main():
    private,env=env_and_calibrate()
    fetch(private,env)
    perf=profile_work.select(env,private)
    save(LOG/'profile-tool.json',{'path':str(perf),'sha256':sha(perf),'version':run([perf,'version','--build-options'],env,private).stdout.decode(),
         'period':profile_work.PERIOD,'stack':'dwarf,4096','restored_environment':'/usr/bin/env -i <all declared values>'})
    soft,hard=resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE,(min(max(soft,8192),hard) if hard!=-1 else max(soft,8192),hard))
    history=private/'history';clean=private/'empty-new'
    readbacks={}
    with ExitStack() as pins:
        o,pinned,old_elf=case('old',private,env,history,retain=pins)
        git('checkout','--detach',NEW)
        e,_,new_elf=case('edit',private,env,history,old=pinned,profiler=perf)
        u,_,same=case('unchanged',private,env,history,old=pinned)
        readbacks.update(old=o,edit=e,unchanged=u)
    assert shutil.disk_usage(ROOT).free>readbacks['old']['storage']['overall']['allocated']+(3<<30)
    c,_,empty=case('clean',private,env,clean)
    readbacks['clean']=c
    chains=[json.loads((LOG/ph/'exec-env.json').read_text()) for ph in ('old','edit','unchanged','clean')]
    for stage in ('watch','proxy','signed_cargo'):
        envs=[{k:v for k,v in ch[stage]['env'].items() if k not in ('CARGO_TARGET_DIR','CARGO_BUILD_BUILD_DIR')} for ch in chains]
        assert all(e==envs[0] for e in envs)
    assert old_elf['typed']!=new_elf['typed']==same['typed']==empty['typed']
    assert new_elf['cli_cases']==same['cli_cases']==empty['cli_cases']
    assert new_elf['cli_version']==same['cli_version']==empty['cli_version']
    assert all(r['products']==o['products'] for r in readbacks.values())
    gates={}
    assert sha(contact.REF)==contact.DIGEST
    with zipfile.ZipFile(contact.REF) as original:
        for phase in ('old','edit','unchanged','clean'):
            folder=LOG/phase
            def local(name):return (LOG/name).read_bytes()
            rosters=contact.compare(original.read,local,phase,folder)
            old_native=json.loads(original.read(phase+'/objects.json'));native=json.loads(local(phase+'/objects.json'))
            def object_keys(data):
                return {unit:{file:(v['sha256'],v.get('physically_reused')) for file,v in s['objects'].items()} for unit,s in data.items()}
            previous=json.loads(original.read(phase+'/verdict.json'));now=json.loads(local(phase+'/verdict.json'))
            old_chain=json.loads(original.read(phase+'/exec-env.json'));new_chain=json.loads(local(phase+'/exec-env.json'))
            entry=lambda group:{key:(v['path'],v['env']) for key,v in group.items()}
            gates[phase]={'literal_cargo_exec_environments':entry(old_chain)==entry(new_chain),'full_arguments_and_env':rosters,'native_payloads_and_donors':object_keys(old_native)==object_keys(native),
                          'typed':previous['typed_by_features']==now['typed_by_features'],'cli':previous['cli_cases']==now['cli_cases']}
        previous=json.loads(original.read('complete.json'))['visits']
        shape=lambda r:(r['roster'],r['products'],r['dirty'],r['wild'])
        gates['four_phases']={'same_dirty_owners_and_wild':all(shape(readbacks[k])==shape(previous[k]) for k in previous),
           'one_namespace':len({tuple(sorted(r['native_output_namespaces'])) for r in readbacks.values()})==1,
           'sample_counts':bool(readbacks['edit']['sampled'])}
    save(LOG/'comparison-gates.json',gates)
    save(LOG/'complete.json',{'visits':readbacks,'typed':[old_elf['typed'],new_elf['typed']],'fixed_cli':new_elf['cli_cases'],
                              'cli_sha256s':[v['cli_sha256'] for v in (old_elf,new_elf,same,empty)],'qa':os.environ['GITHUB_SHA']})
    assert all(all(v.values()) for v in gates.values()),gates


if __name__=='__main__':
    main()
