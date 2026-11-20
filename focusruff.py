from pathlib import Path
import resource
import hashlib, json, os, re, shutil, subprocess, sys, time
wd=Path.cwd()
root=Path(os.environ['RUNNER_TEMP'])/'replay'
root.mkdir()
out=wd/'counts'
out.mkdir()
inputs=wd/'scripts/session_replays'
fixture=json.loads((inputs/'ruff-rust-1.100.json').read_text())
sdk=root/'sdk'
kit=wd/'kits'
source=wd/'source'
target=root/'target'
shared=root/'shared'
def run(*args,**opts):subprocess.run(list(map(str,args)),check=True,**opts)
def git(*args):return subprocess.check_output(['git',*args],cwd=source)
def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def install(arm):
    folder=kit/arm
    tarball,=list(folder.rglob('*.tar.gz'))
    rustdir='rust-1.100.0-dev-x86_64-unknown-linux-gnu'
    h=digest(tarball)
    if arm=='2':
        assert h=='a6a1621e4581940e93ff7f9720b6102f6589185539650633a4235410f0bbd26d'
    else:
        checkfile=tarball.with_suffix('.gz.sha256')
        assert h==checkfile.read_text().split()[0]
        prov,=list(folder.rglob('*-provenance.json'))
        expected={'b':'138b9b74a947f60ba231d42608866d70b55843eb','n':'52f3173594b1847f9571b6cef6fad9deac5a4fd9','f':'af392995e5ca93b70fc487b45dfdf6604dbbbc84'}
        assert json.loads(prov.read_text())['sources']['rust']['revision']==expected[arm]
    run('tar','xzf',tarball,'-C',root)
    run('sh',root/rustdir/'install.sh','--prefix='+str(sdk),'--disable-ldconfig','--without=rust-docs')
    shutil.rmtree(root/rustdir)
    run('rustup','toolchain','link','ohm-1.100.0-3',sdk)
    return h
def objects(stamp):
    result={}
    for name in ('ty_python_semantic','ty_test'):
        units=[]
        for directory in root.glob('**/incremental/**/'+name+'-*/s-*'):
            if not directory.is_dir():continue
            files=[path.stat() for path in directory.glob('*.o')]
            fresh=[stat for stat in files if stat.st_mtime_ns>=stamp]
            if fresh:units.append(dict(total=len(files),written=len(fresh),bytes=sum(stat.st_size for stat in fresh)))
        result[name]=units
    print('objects',result,flush=True)
    return result
def prime(tag):
    archive=install(tag)
    if tag=="f": assert archive=="9d3e4a2df0ee55cd154c063dcb02f792b60b94d972c7ecb707a4acf2ea8a6dc2"
    d=out/tag
    d.mkdir()
    git('reset','--hard',fixture['base_revision'])
    for patch in fixture['setup_patches']:
        path=inputs/patch['patch']
        assert digest(path)==patch['sha256']
        git('apply',str(path))
    env={k:os.environ[k] for k in ('PATH','HOME','USER','LANG','TMPDIR','LOGNAME','SSL_CERT_FILE','SSL_CERT_DIR') if k in os.environ}
    env.update(fixture['environment'])
    env.update(CARGO_BUILD_JOBS='8',RUSTUP_TOOLCHAIN='ohm-1.100.0-3',MEASURE_CLIPPY=str(sdk/'bin/clippy-driver'),
        CARGO_TARGET_DIR=str(target),CARGO_BUILD_BUILD_DIR=str(shared),
        CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST='all',CARGO_TERM_COLOR='never')
    run('cargo','+ohm-1.100.0-3','fetch','--locked','--target','x86_64-unknown-linux-gnu',env=env,cwd=source)
    env['CARGO_NET_OFFLINE']='true'
    rows=[]
    for idx,step in enumerate(fixture['warmup']+fixture['steps']):
        if idx==11: break
        if step['kind']=='edit':
            run('git','apply','-',input=git('diff','--binary',step['parent'],step['commit']),cwd=source)
            continue
        assert step['program']=='cargo'
        receipt=d/f'{idx}.tsv'
        cmd=['cargo','+ohm-1.100.0-3',*step['args']]
        print(tag,idx,cmd,flush=True)
        stamp=time.time_ns()
        start=time.perf_counter()
        path=receipt.with_suffix('.log')
        with path.open('w') as f:
            run(*cmd,cwd=source,env=env,stdout=f,stderr=subprocess.STDOUT)
        n=time.perf_counter()-start
        tests=re.findall(r'(\d+) tests? run',path.read_text())
        rows.append(dict(step=idx,label=step['label'],seconds=n,tests=tests,objects=objects(stamp) if idx==11 else {}))
    idx=states/'verify-index'
    shutil.copyfile(source/'.git/index',idx)
    genv=dict(os.environ,GIT_INDEX_FILE=str(idx))
    run('git','add','-A',cwd=source,env=genv)
    tree=subprocess.check_output(['git','write-tree'],cwd=source,env=genv).decode().strip()
    assert tree=='f8f06a00db94b2a3b23bdfcb31e84849ae709ebf',tree
    assert len(rows)==8, len(rows)
    snap=states/tag
    snap.mkdir()
    for folder in (sdk,source,target,shared):
        folder.rename(snap/folder.name)
    return dict(archive=archive,tree=tree,rows=rows),env

def copy(src,dst):
    run('cp','-a','--reflink=auto',src,dst)

def sample(i,tag):
    snap=states/tag
    for folder in (sdk,source):
        (snap/folder.name).rename(folder)
    for folder in (target,shared):
        copy(snap/folder.name,folder)
    step=(fixture['warmup']+fixture['steps'])[11]
    assert step['label']=='Run the expanded component-cycle regressions'
    cmd=['cargo','+ohm-1.100.0-3',*step['args']]
    path=out/f'{i}-{tag}.log'
    using=resource.RUSAGE_CHILDREN
    with path.open('w') as f:
        stamp=time.time_ns()
        usage=resource.getrusage(using)
        start=time.perf_counter_ns()
        run(*cmd,cwd=source,env=envs[tag],stdout=f,stderr=subprocess.STDOUT)
        elapsed=(time.perf_counter_ns()-start)/1e9
        after=resource.getrusage(using)
    record=dict(pos=i,tag=tag,elapsed=elapsed,user=after.ru_utime-usage.ru_utime,system=after.ru_stime-usage.ru_stime,
                objects=objects(stamp),tests=re.findall(r'(\d+) tests? run',path.read_text()),
                compiled=re.findall(r'Compiling (\S+)',path.read_text()))
    print(record,flush=True)
    assert record['tests']==['1']
    assert record['objects']['ty_python_semantic']
    for folder in (sdk,source):
        folder.rename(snap/folder.name)
    for folder in (target,shared):
        shutil.rmtree(folder)
    return record

states=wd/'snapshots'
states.mkdir()
source.rename(states/'initial')
order=sys.argv[1]
assert len(order)==8 and all(set(order[i:i+2])=={'2','f'} for i in range(0,8,2))
result=dict(order=order,cpu=subprocess.check_output(['lscpu']).decode(),
            boot=digest(Path('/proc/sys/kernel/random/boot_id')),
            primes={},samples=[])
envs={}
for tag in order[:2]:
    copy(states/'initial',source)
    result['primes'][tag],envs[tag]=prime(tag)
for i,t in enumerate(order):
    result['samples'].append(sample(i,t))
    (out/'counts.json').write_text(json.dumps(result,indent=2))
with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a') as f:
    print('## Component-cycle command',file=f)
    print('\nEach measurement restores a fresh copy of both artifact trees saved after the full prefix and third edit. Source and SDK paths and timestamps are preserved. CPU seconds include descendants of the original nextest invocation.\n',file=f)
    print('| Pair | SDK | Elapsed | User CPU | System CPU |\n|---|---|---:|---:|---:|',file=f)
    for r in result['samples']:
        tag='−2' if r['tag']=='2' else '#455'
        print(f"| {1+r['pos']//2} | {tag} | {r['elapsed']:.3f} | {r['user']:.3f} | {r['system']:.3f} |",file=f)
