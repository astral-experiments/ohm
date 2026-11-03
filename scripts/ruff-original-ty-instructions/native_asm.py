"""Unscored matched compiler discovery on the original Ruff RUF009 edit."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import os
import re
import shutil
import subprocess as sp
import sys
import tarfile
import zipfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'ruff-foreign-span-observer'))
import worker as w
sys.path.insert(0,str(Path(os.environ['GITHUB_WORKSPACE'])/'factory/scripts/ruff-matched-stage'))
import capsule as c
R=json.loads((HERE/'native-asm-registration.json').read_bytes())
def save(name,data):
    with (w.proof/name).open('x') as f: json.dump(data,f,sort_keys=True,indent=1);f.write('\n')
def gh(*args):
    return sp.check_output(['gh','api',*args],env=dict(os.environ,GH_TOKEN=os.environ['OHM_SDK_READ_TOKEN']))
def intake():
    run=json.loads(gh('repos/astral-experiments/ohm/actions/runs/'+str(R['run'])))
    assert run['head_sha']==R['factory'] and run['event']=='workflow_dispatch' and run['run_attempt']==1 and run['conclusion']=='success'
    assert c.REG['roles']['P']['revision']==R['P'] and c.REG['roles']['C']['revision']==R['C']
    assets=json.loads(gh('repos/astral-experiments/ohm/actions/runs/'+str(R['run'])+'/artifacts'))['artifacts']
    for label in ('sdk','receipts'):
        desc=R[label];row,=[a for a in assets if a['id']==desc['id']]
        assert not row['expired'] and (row['name'],row['size_in_bytes'],row['digest'])==(desc['name'],desc['bytes'],'sha256:'+desc['sha256'])
        path=w.root/(label+'.zip')
        with path.open('xb')as f: sp.run(['gh','api','repos/astral-experiments/ohm/actions/artifacts/'+str(desc['id'])+'/zip'],env=dict(os.environ,GH_TOKEN=os.environ['OHM_SDK_READ_TOKEN']),stdout=f,check=True)
        assert w.hf(path)==desc['sha256']
    rec=zipfile.ZipFile(w.root/'receipts.zip'); sdk=zipfile.ZipFile(w.root/'sdk.zip')
    assert sdk.namelist()==['matched-stage.tar.zst']; archive=w.root/'matched-stage.tar.zst'
    with archive.open('xb')as f,sdk.open('matched-stage.tar.zst')as src:shutil.copyfileobj(src,f)
    assert w.hf(archive)==rec.read('archive.sha256').decode().split()[0]
    with sp.Popen(['zstd','-dcq',str(archive)],stdout=sp.PIPE) as child:
        with tarfile.open(fileobj=child.stdout,mode='r|')as t:
            size=0
            for m in t:
                out=w.root/m.name;size+=m.size;assert size<2_000_000_000
                if m.isdir():assert m.name in ('capsule','capsule/objects');out.mkdir();continue
                assert m.isfile() and re.fullmatch(r'capsule/(?:(?:P|C|qualified)\.json|objects/[a-f0-9]{64})',m.name)
                with out.open('xb')as f,t.extractfile(m)as src:shutil.copyfileobj(src,f)
                out.chmod(m.mode&0o777)
        trailing=child.stdout.read();assert not any(trailing) and len(trailing)<131072 and child.wait()==0
    cap=w.root/'capsule'
    assert (cap/'qualified.json').read_bytes()==rec.read('accepted.json')
    for role in ('P','C'):assert (cap/(role+'.json')).read_bytes()==rec.read(role+'.json')
    source=json.loads(rec.read('accepted.json'));assert source['source_sha256']==hashlib.sha256(rec.read('source.json')).hexdigest()
    return c.reopen(cap,w.root/'tools')
def probe(exe):
    out=[]
    for deco,expr,code in [('attr.define','attr.field(factory=list)','field'),('attr.attributes','list()','attributes'),('attr.define','list()','common'),('attr.define','1','clean')]:
        source=f'import attr\n@{deco}\nclass Example:\n    value: list[int] = {expr}\n'
        r=sp.run([exe,'check','--isolated','--no-cache','--select','RUF009','--output-format','json','--stdin-filename','case.py','-'],input=source,text=True,capture_output=True)
        assert r.returncode in (0,1) and not r.stderr;msgs=json.loads(r.stdout)
        assert [m['code']for m in msgs]==['RUF009']*r.returncode
        out.append([code,r.returncode,msgs])
    return out
def archive_members(path):
    out=[]
    with path.open('rb')as f:
        assert f.read(8)==b'!<arch>\n'
        while h:=f.read(60):
            assert len(h)==60 and h[58:]==b'`\n'
            size=int(h[48:58]);name=h[:16].strip().decode('ascii');remaining=size;digest=hashlib.sha256()
            while remaining:
                b=f.read(min(remaining,1<<20));assert b;digest.update(b);remaining-=len(b)
            if size%2:assert len(f.read(1))==1
            out.append([name,size,digest.hexdigest()])
    return out
def preserve(path):
    key=w.hf(path);out=w.proof/(key+'.native.zst')
    assert path.is_file() and 0<path.stat().st_size<1_500_000_000
    if not out.exists():
        with out.open('xb')as f:sp.run(['zstd','-q','-3','-c',str(path)],stdout=f,check=True)
    return {'name':path.name,'bytes':path.stat().st_size,'sha256':key,'zstd':out.name}

def phase(role,label,kind):
    dst=w.proof/(role+'-'+label);dst.mkdir()
    cmd=['cargo','+ohm','build','-p','ruff','--bin','ruff','--locked','--offline','-j4','--message-format=json']
    path=shutil.which('cargo',path=env['PATH'])
    if kind=='whole':actual=[str(whole),str(dst/'hardware.json'),path,*cmd]
    elif kind=='census':
        (dst/'tasks').mkdir();actual=[str(tasks),str(dst/'tasks'),*cmd]
    else:actual=cmd
    w.guard()
    with (dst/'stdout.jsonl').open('xb')as o,(dst/'stderr').open('xb')as e:
        answer=sp.run(actual,cwd=w.work,env=env,stdout=o,stderr=e)
    assert answer.returncode==0,(label,(dst/'stderr').read_text()[-1600:])
    rows=[json.loads(s)for s in (dst/'stdout.jsonl').read_bytes().splitlines()]
    assert rows[-1]=={'reason':'build-finished','success':True}
    arts=[r for r in rows if r['reason']=='compiler-artifact'];assert len(arts)==350,len(arts)
    cli,=[r for r in arts if r.get('executable') and r['target']['name']=='ruff' and r['target']['kind']==['bin']]
    exe=Path(cli['executable']);verdicts=probe(exe); rev=w.git('rev-parse','HEAD')
    assert [v[1] for v in verdicts]==([1,0,1,0]if rev==w.OLD else [0,1,1,0])
    obj=dict(role=role,label=label,kind=kind,source=rev,command=cmd,elf=w.hf(exe),probes=verdicts,
             units=sorted([r['package_id'],r['target']['name'],r['target']['kind'],sorted(r['features'])]for r in arts),
             dirty=sorted([r['package_id'],r['target']['name']]for r in arts if not r['fresh']),owners={})
    if label in ('old','settled','independent-clean'):
        obj['binary']=preserve(exe)
        for args in (['-W','-S'],['-W','-n'],['-W','-l']):
            with (dst/('readelf-'+args[-1]+'.txt')).open('xb')as f:sp.run(['readelf',*args,exe],stdout=f,check=True)
    for crate in ('portable_atomic','salsa','ruff_linter','ty_python_semantic'):
        r,=[a for a in arts if a['target']['name']==crate and a['target']['kind']==['lib']]
        archive,=[Path(n)for n in r['filenames'] if n.endswith('.rlib')]
        emitted=[Path(n)for n in r['filenames'] if n.endswith('.rmeta')]
        metadata,=emitted or [archive.with_suffix('.rmeta')]
        assert metadata.is_file()
        dep=metadata.with_name(metadata.stem.removeprefix('lib')+'.d');raw=dep.read_bytes(); (dst/(crate+'.d')).write_bytes(raw)
        key=w.hf(metadata)
        info={'rmeta':key,'rlib':w.hf(archive),'dep':w.hf(dep),'marker':b'/dev/null/ohm-untracked-relink-inputs:' in raw.splitlines()}
        if label in ('settled','sample-0','independent-clean') and crate in ('salsa','ruff_linter'):
            f=w.proof/(key+'.rmeta.zst')
            if not f.is_file():
                with f.open('xb')as out:sp.run(['zstd','-q','-3','-c',str(metadata)],stdout=out,check=True)
            info['archive_members']=archive_members(archive)
        obj['owners'][crate]=info
    if kind=='whole':
        hw=json.loads((dst/'hardware.json').read_bytes());assert hw['instructions']>0 and hw['enabled']==hw['running']>0 and hw['status']==0
        obj['instructions']=hw['instructions']
    if kind=='census':
        roster=[];rustc_stat=(w.sdk/'bin/rustc').stat()
        for row in (dst/'tasks/epochs.tsv').read_text().splitlines():
            if not row.startswith('I ') or not row.endswith(' exec'):continue
            seq=int(row.split()[1]);fields=(dst/'tasks'/f'{seq:05}.nul').read_bytes().split(b'\0')
            path=Path(os.fsdecode(fields[3]));argv=list(map(os.fsdecode,fields[4:-1]))
            if (int(fields[1]),int(fields[2]))==(rustc_stat.st_dev,rustc_stat.st_ino) and '--crate-name' in argv:
                assert path.samefile(w.sdk/'bin/rustc');roster.append(argv[argv.index('--crate-name')+1])
        obj['typed_execs']=sorted(roster)
    (dst/'result.json').write_text(json.dumps(obj,indent=1,sort_keys=True)+'\n')
    print(role,label,'instructions',obj.get('instructions'), 'nominal-dirty',len(obj['dirty']), 'portable marker',obj['owners']['portable_atomic']['marker'],flush=True)
    return obj
def expected_failure(role,label,needle):
    dst=w.proof/(role+'-'+label);dst.mkdir()
    cmd=['cargo','+ohm','build','-p','ruff','--bin','ruff','--locked','--offline','-j4','--message-format=json']
    with (dst/'stdout').open('xb')as o,(dst/'stderr').open('xb')as e:
        ret=sp.run(cmd,env=env,cwd=w.work,stdout=o,stderr=e)
    raw=(dst/'stdout').read_bytes();msgs=[json.loads(s)for s in raw.splitlines()]
    return {'code':ret.returncode,'failed':ret.returncode==101 and msgs[-1]=={'reason':'build-finished','success':False} and needle in (raw+(dst/'stderr').read_bytes())}

def holdouts(role):
    roots=set();linked=[]
    wild=w.sdk/'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd';wid=(wild.stat().st_dev,wild.stat().st_ino)
    for f in (w.proof/(role+'-census')/'tasks').glob('*.nul'):
        fields=f.read_bytes().split(b'\0')
        if (int(fields[1]),int(fields[2]))!=wid: continue
        args=list(map(os.fsdecode,fields[4:-1]))
        for arg in args:
            part=Path(arg)
            if part.is_absolute() and part.suffix in ('.a','.rlib','.o','.so'):
                linked.append([str(part),w.hf(part) if part.is_file()else None])
        for n,arg in enumerate(args):
            name=args[n+1]if arg=='-L' else arg[2:]if arg.startswith('-L') else ''
            if name and (Path(name)/'libjemalloc_pic.a').is_file():roots.add(Path(name).resolve())
    assert len(roots)==1,roots
    path,=roots;assert path.is_relative_to(w.shared) or path.is_relative_to(w.target)
    save(role+'-link-inputs.json',{'inputs':linked,'jemalloc':preserve(path/'libjemalloc_pic.a')})
    shadow=path/'libm.so';body=b'not an ELF shared library\n';assert not shadow.exists()
    with shadow.open('xb')as f:f.write(body)
    try: native=expected_failure(role,'malformed-shadow',b'libm.so')
    finally:
        assert shadow.read_bytes()==body;shadow.unlink()
    repaired=phase(role,'shadow-repair','ordinary')
    files=w.git('diff','--name-only',w.OLD,w.NEW).splitlines()
    edits=[w.work/f for f in files if f.startswith('crates/ruff_linter/src/') and f.endswith('.rs')]
    assert len(edits)==1,edits
    source,=edits; original=source.read_bytes(); source.write_bytes(original+b'\nconst _: u8 = "ill-typed";\n')
    try: invalid=expected_failure(role,'invalid-Ruff-source',b'E0308')
    finally:source.write_bytes(original)
    fixed=phase(role,'source-repair','ordinary');assert not w.git('status','--porcelain')
    save(role+'-holdouts.json',{'shadow_directory':str(path),'library':w.hf(path/'libjemalloc_pic.a'),'native':native,'source':invalid})
    return repaired,fixed,native['failed']and invalid['failed']

def prepare_empty():
    assert not any(p.exists() for p in (w.target,w.shared,w.home))
    env.pop('CARGO_NET_OFFLINE',None)
    sp.run(['cargo','+ohm','fetch','--locked','--target','x86_64-unknown-linux-gnu'],cwd=w.work,env=env,check=True)
    env['CARGO_NET_OFFLINE']='true'

def park(role, kind):
    held=w.root/'parked';held.mkdir(exist_ok=True)
    for path in (w.target,w.shared,w.home):
        assert path.parent==w.root and path.is_dir() and not path.is_symlink()
        path.rename(held/(role+'-'+kind+'-'+path.name))
assert w.git('rev-parse','HEAD')==w.NEW and w.git('rev-parse','HEAD^')==w.OLD and w.hf(w.work/'Cargo.lock')==w.OLDLOCK and not w.git('status','--porcelain')
assert os.environ['GITHUB_SHA']==os.environ['REVIEWED_HEAD'] and os.environ['GITHUB_RUN_ATTEMPT']=='1' and os.uname().machine=='x86_64'
save('registered.json',R); manif=intake()
env={k:os.environ[k]for k in ('PATH','HOME','LANG','USER')if k in os.environ}
env.update(RUSTUP_HOME=str(w.ru),RUSTUP_TOOLCHAIN='ohm',CARGO_HOME=str(w.home),CARGO_TARGET_DIR=str(w.target),CARGO_BUILD_BUILD_DIR=str(w.shared),CARGO_NET_GIT_FETCH_WITH_CLI='true',LD_LIBRARY_PATH=str(w.sdk/'lib'))
(w.ru/'toolchains').mkdir(parents=True);(w.ru/'toolchains/ohm').symlink_to(w.sdk,True)
whole=w.root/'whole_count';tasks=w.root/'exec_count'
for exe in (whole,tasks):
    sp.run(['/usr/bin/cc','-Wall','-Wextra','-Werror','-O2',str(HERE/(exe.name+'.c')),'-o',str(exe)],check=True)
receipts={};safety={}
for role in R['order']:
    label={'P':'normal','C':'defer'}[role];original=Path(manif['arms'][label]['root']);original.rename(w.sdk)
    for name in ('cargo','rustc','rustdoc'):
        actual=Path(sp.check_output(['rustup','which','--toolchain','ohm',name],env=env,text=True).strip())
        assert actual.samefile(w.sdk/'bin'/name) and w.hf(actual)==manif['arms'][label]['files']['bin/'+name]
    driver,=(w.sdk/'lib').glob('librustc_driver-*.so');assert w.hf(driver)==manif['arms'][label]['files']['lib/'+driver.name]
    w.git('switch','--detach',w.OLD)
    prepare_empty();hist={}
    hist['old']=phase(role,'old','ordinary');w.git('switch','--detach',w.NEW)
    hist['edit']=phase(role,'edit','whole');hist['settled']=phase(role,'settled','whole')
    for n in range(3):hist['sample-'+str(n)]=phase(role,'sample-'+str(n),'whole')
    hist['census']=phase(role,'census','census')
    hist['shadow-repair'],hist['source-repair'],safety[role]=holdouts(role);park(role,'warm')
    prepare_empty();hist['independent-clean']=phase(role,'independent-clean','ordinary');park(role,'clean')
    assert min(len(hist[k]['dirty']) for k in ('old','independent-clean'))>330
    w.sdk.rename(original);receipts[role]=hist
summary={}
for label in receipts['P']:
    p=receipts['P'][label];c=receipts['C'][label]
    summary[label]={'same_units':p['units']==c['units'],'same_verdicts':p['probes']==c['probes'],'same_elf':p['elf']==c['elf'],
                    'P':p.get('instructions'),'C':c.get('instructions'),'P_actual':p.get('typed_execs'),'C_actual':c.get('typed_execs')}
save('summary.json',summary);assert all(safety.values()),safety
assert all(x['same_units']and x['same_verdicts'] and x['same_elf']for x in summary.values()),summary
for role,h in receipts.items():
    assert h['old']['elf']!=h['edit']['elf'] and len({x['elf']for k,x in h.items()if k!='old'})==1
    assert all(row['owners']['portable_atomic']['marker']==(role=='P') for row in h.values())
