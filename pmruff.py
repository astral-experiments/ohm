from pathlib import Path
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
def arm(tag):
    archive=install(tag)
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
    git('add','-A')
    tree=git('write-tree').decode().strip()
    assert tree=='f8f06a00db94b2a3b23bdfcb31e84849ae709ebf',tree
    assert len(rows)==13
    for path in (sdk,target,shared):shutil.rmtree(path)
    return dict(tree=tree,archive=archive,rows=rows)
order=sys.argv[1][:2]
result={t:arm(t) for t in order}
data=json.dumps(result,indent=2)
(out/'counts.json').write_text(data)
a,b=order
with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a') as f:
    print('## Elapsed seconds during the Ruff edit sequence',file=f)
    print('\n2 is published −2, b is the 30-PR candidate, n adds the new compiler and LLVM changes, and f includes the Ruff fix. Each arm starts with a clean target. Each row measures elapsed seconds for the complete command.\n',file=f)
    print(f'| Command | {a} | {b} |\n|---|---:|---:|',file=f)
    for x,y in zip(result[a]['rows'],result[b]['rows']):
        assert x['label']==y['label'] and x['tests']==y['tests']
        print(f"| {x['label']} | {x['seconds']:.2f} | {y['seconds']:.2f} |",file=f)
    totals=[sum(row['seconds'] for row in result[t]['rows'][1:]) for t in order]
    print(f"| Total after warmup | {totals[0]:.2f} | {totals[1]:.2f} |",file=f)

