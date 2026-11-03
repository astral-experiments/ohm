"""Measure the stock signed compiler's contribution to an ordinary unchanged Ruff check and build."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

here=Path(__file__).resolve().parent
sys.path.insert(0,str(here.parent/'ruff-foreign-span-observer'))
import worker as w
sys.path.insert(0,str(here))
import live_tasks

order=['whole','simultaneous','simultaneous','whole','whole','simultaneous','simultaneous','whole']
schedule=['build']
owners=('ruff_linter','salsa')
tree=w.proof/'instructions';tree.mkdir()
def save(path, obj):
    path.write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n')
def identity(path):
    stat=path.stat()
    return [stat.st_dev,stat.st_ino]
def cost(folder):
    images={};totals=Counter();creates={}
    for line in (folder/'epochs.tsv').read_text().splitlines():
        row=line.split()
        if row[0]=='I':
            _,seq,group,tid,when,action=row
            fields=(folder/(f'{int(seq):05}.nul')).read_bytes().split(b'\0')
            assert fields[-1]==b'' and int(fields[0])==int(group) and int(seq) not in images
            images[int(seq)]=(list(map(int,fields[1:3])),os.fsdecode(fields[3]),list(map(os.fsdecode,fields[4:-1])))
            creates[int(seq)]=action
        elif row[0]=='C':
            _,seq,group,tid,retired,enabled,running=map(str,row)
            assert int(seq) in images and int(enabled)==int(running) and (not int(retired) or int(running)>0)
            totals[int(seq)]+=int(retired)
        else:assert row[0] in ('M','W')
    return images,totals,creates
def capture(cmd, method, dst, env, cwd):
    dst.mkdir()
    actual=list(cmd)
    path=shutil.which(cmd[0],path=env['PATH'])
    assert path is not None
    if method in ('whole','simultaneous'):
        actual=[str(whole),str(dst/'hardware.json'),path,*cmd]
    elif method=='tasks':
        (dst/'tasks').mkdir()
        actual=[str(tasks),str(dst/'tasks'),*cmd]
    else:assert method=='ordinary'
    w.guard()
    with (dst/'stdout').open('wb')as o,(dst/'stderr').open('wb')as e:
        if method=='simultaneous':
            observation=live_tasks.observe(actual,library=library,sdk=w.sdk,dst=dst,cwd=cwd,env=env,stdout=o,stderr=e,subjects=('ty_python_semantic',) if dst.name=='detector-calibration' else owners)
            save(dst/'live-threads.json',observation)
        else:
            answer=subprocess.run(actual,cwd=cwd,env=env,stdout=o,stderr=e)
            assert answer.returncode==0,(dst,(dst/'stderr').read_text()[-1800:])
    if method in ('whole','simultaneous'):
        obs=json.loads((dst/'hardware.json').read_text())
        assert obs['status']==0 and obs['enabled']==obs['running']>0 and obs['instructions']>0
        return obs['instructions']
    if method=='tasks':
        return sum(cost(dst/'tasks')[1].values())
    return None
def probe(exe):
    results={}
    for key,deco,expr in [('field','attr.define','attr.field(factory=list)'),('attributes','attr.attributes','list()'),('common','attr.define','list()'),('clean','attr.define','1')]:
        source=f'import attr\n@{deco}\nclass Example:\n    value: list[int] = {expr}\n'
        p=subprocess.run([exe,'check','--isolated','--no-cache','--select','RUF009','--output-format','json','--stdin-filename','case.py','-'],input=source,text=True,capture_output=True)
        assert not p.stderr and p.returncode in (0,1)
        records=json.loads(p.stdout);assert [m['code'] for m in records]==['RUF009']*p.returncode
        results[key]=[p.returncode,records]
    return results
def run_phase(mode,label,method):
    dst=tree/(mode+'-'+label)
    cmd=['cargo','+ohm',mode,'-p','ruff','--bin','ruff','--locked','--offline','-j4','--message-format=json']
    total=capture(cmd,method,dst,env,w.work)
    rows=[json.loads(line)for line in (dst/'stdout').read_bytes().splitlines()]
    assert rows[-1]=={'reason':'build-finished','success':True}
    arts=[r for r in rows if r['reason']=='compiler-artifact']
    assert len(arts)=={'check':360,'build':350}[mode]
    roster=sorted((r['package_id'],r['target']['name'],r['target']['kind'],sorted(r['features']),r['fresh'])for r in arts)
    ty,=[r for r in arts if r['target']['name']=='ty_python_semantic' and r['target']['kind']==['lib']]
    files=list(map(Path,ty['filenames']))
    metadata,={p.with_suffix('.rmeta') for p in files if p.suffix in ('.rlib','.rmeta') and p.with_suffix('.rmeta').is_file()}
    dep=metadata.with_name(metadata.stem.removeprefix('lib')+'.d')
    dependency_bytes=dep.read_bytes()
    assert os.fsencode(dep)+b'/ohm-foreign-span-bytes' in dependency_bytes
    (dst/'ty.d').write_bytes(dependency_bytes)
    if label=='settled':
        with (dst/'ty.rmeta.zst').open('wb') as fp:
            subprocess.run(['zstd','-q','-c','-3',metadata],stdout=fp,check=True)
    data={'source':w.git('rev-parse','HEAD'),'command':cmd,'mode':mode,'label':label,'method':method,'total':total,
          'roster_sha256':hashlib.sha256(json.dumps(roster,sort_keys=True).encode()).hexdigest(),'units':len(arts),
          'dirty':sorted([r['target']['name'],r['target']['kind']]for r in arts if not r['fresh']),
          'ty_rmeta':w.hf(metadata),'ty_depinfo':w.hf(dep)}
    if mode=='build':
        exe,=[Path(r['executable'])for r in arts if r['target']['name']=='ruff' and r['target']['kind']==['bin'] and r.get('executable')]
        result=probe(exe)
        expected=[1,0,1,0] if data['source']==w.OLD else [0,1,1,0]
        assert [r[0]for r in result.values()]==expected
        data.update(binary=w.hf(exe),probes=result)
    payloads={}
    for owner in owners:
        art,=[r for r in arts if r['target']['name']==owner and r['target']['kind']==['lib']]
        path,={Path(n).with_suffix('.rmeta') for n in art['filenames'] if n.endswith(('.rmeta','.rlib'))}
        info=path.with_name(path.stem.removeprefix('lib')+'.d')
        payloads[owner]={'rmeta':w.hf(path),'depinfo':w.hf(info),'artifacts':{Path(n).name:w.hf(n) for n in art['filenames']}}
    data['owner_inputs']=payloads
    if label=='settled':
        for art in arts:
            if art['fresh']: continue
            for name in art['filenames']:
                file=Path(name)
                for dep in (file.with_name(file.stem.removeprefix('lib')+'.d'),):
                    if file.suffix=='.rlib' and dep.is_file():
                        (dst/(dep.name+'.raw')).write_bytes(dep.read_bytes())
    if method=='simultaneous':
        observation=json.loads((dst/'live-threads.json').read_text())
        lower=observation['instructions']
        assert 0<lower<=total
        data.update(owners_lower=observation['by_crate'],owner_fraction=lower/total)
    save(dst/'result.json',data)
    print(mode,label,method,'retired',total,'nonfresh',len(data['dirty']),flush=True)
    return data

assert w.git('rev-parse','HEAD')==w.NEW and w.git('rev-parse','HEAD^')==w.OLD and w.hf(w.work/'Cargo.lock')==w.OLDLOCK and not w.git('status','--porcelain')
assert os.environ['GITHUB_RUN_ATTEMPT']=='1' and os.environ['GITHUB_SHA']==os.environ['REVIEWED_HEAD'] and os.uname().machine=='x86_64'
pre={'source':[w.OLD,w.NEW],'lock':w.OLDLOCK,'order':order,'modes':schedule,'sdk_manifest':w.hf(w.src/'sdk.json'),
     'counter_sha256':{p.name:w.hf(p)for p in here.glob('*.c')},'live_observer_sha256':w.hf(here/'live_tasks.py'),'purpose':'Test independently whether ordinary stock ruff_linter and salsa rustc together exceed half of the unchanged native Ruff build. No forced build or ptrace on the measured histories.',
     'admit':'All four observed normal commands must have both exact compiler children and the same positive combined lower bound above 50%, with each owner above 10%, to nominate a 2x instruction opportunity. Count only fully scheduled physically authenticated threads, omit unverifiable samples entirely and report their raw values. Controls retain exact source/roster, both owner products, Ty, final ELF and four RUF009 verdicts. Observed whole totals must lie within 5% of the four untouched controls.'}
save(tree/'registered.json',pre)
env=w.install()
whole=w.root/'whole_count';tasks=w.root/'exec_count'
for program in (whole,tasks):
    subprocess.run(['/usr/bin/cc','-O2','-Wall','-Wextra','-Werror',here/(program.name+'.c'),'-o',program],check=True)
runtime_ids={'rustc':identity(w.sdk/'bin/rustc'),'cargo':identity(w.sdk/'bin/cargo'),'wild':identity(next((w.sdk/'lib/rustlib').glob('*/bin/wild-ld/ld.bfd')))}
save(tree/'runtime-file-ids.json',runtime_ids)
library_path=w.root/'libtask_count.so'
subprocess.run(['/usr/bin/cc','-Wall','-Wextra','-Werror','-O2','-shared','-fPIC',here/'task_count.c','-o',library_path],check=True)
library=live_tasks.load_library(library_path)
fd=live_tasks.attach(library,os.getpid())
before=live_tasks.count(fd)['instructions']
sum(range(2000000))
after=live_tasks.count(fd)['instructions']
assert after>before+10000000
child_before=live_tasks.count(fd)['instructions']
subprocess.run(['/usr/bin/python3','-IB','-c','sum(range(6000000))'],check=True)
child_after=live_tasks.count(fd)['instructions']
os.close(fd)
assert child_after-child_before<5000000
save(tree/'single-thread-calibration.json',{'self_delta':after-before,'external_child_delta':child_after-child_before})
for method in ('whole','tasks'):
    for kind in ('thread','child'):
        vals=[]
        for heavy in (False,True):
            part='sum(range(6000000))' if heavy else 'None'
            code='import threading;t=threading.Thread(target=lambda:'+part+');t.start();t.join()' if kind=='thread' else 'import sys,subprocess;subprocess.run([sys.executable,"-IB","-c",'+repr(part)+'],check=True)'
            vals.append(capture(['/usr/bin/python3','-IB','-c',code],method,tree/f'calibrate-{method}-{kind}-{int(heavy)}',env,w.work))
        assert vals[1]>vals[0]+10000000
# Check the live detector on this worker's procfs before fetching Ruff dependencies.
fixture=w.root/'live-detector-fixture'
(fixture/'src').mkdir(parents=True)
(fixture/'Cargo.toml').write_text('[package]\nname="ty_python_semantic"\nversion="0.1.0"\nedition="2024"\n')
(fixture/'src/lib.rs').write_text(''.join(f'pub fn f{i}(v:u64)->u64{{v.wrapping_add({i})}}\n' for i in range(8000)))
test_output=tree/'detector-calibration'
test_total=capture(['cargo','+ohm','check','--offline','-j1'],'simultaneous',test_output,dict(env,CARGO_TARGET_DIR=str(fixture/'target')),fixture)
assert 0<json.loads((test_output/'live-threads.json').read_text())['instructions']<=test_total
w.git('switch','--detach',w.OLD)
subprocess.run(['cargo','+ohm','fetch','--locked','--target','x86_64-unknown-linux-gnu'],env=env,cwd=w.work,check=True)
env['CARGO_NET_OFFLINE']='true'
for mode in schedule:
    w.git('switch','--detach',w.OLD)
    old=run_phase(mode,'old','ordinary')
    w.git('switch','--detach',w.NEW)
    edit=run_phase(mode,'edit','ordinary');settled=run_phase(mode,'settled','ordinary')
    if mode=='build':assert old['binary']!=edit['binary']==settled['binary']
    runs=[run_phase(mode,str(i),method) for i,method in enumerate(order)]
    for r in runs:
        for k in ('source','roster_sha256','dirty','ty_rmeta','ty_depinfo','owner_inputs')+(('binary','probes') if mode=='build' else ()):
            assert r[k]==settled[k],(mode,r['label'],k)
    controls=[r['total'] for r in runs if r['method']=='whole']
    paired=[{'whole':r['total'],'owners_lower':r['owners_lower'],'fraction':r['owner_fraction']} for r in runs if r['method']=='simultaneous']
    summary={'ordinary_whole':controls,'simultaneous':paired,'all_majority':all(r['fraction']>.5 and all(v/r['whole']>.1 for v in r['owners_lower'].values()) for r in paired),
             'within_five_percent_of_control_range':all(min(controls)*.95<r['whole']<max(controls)*1.05 for r in paired)}
    save(tree/(mode+'-summary.json'),summary)
    assert summary['within_five_percent_of_control_range'],(mode,summary)
