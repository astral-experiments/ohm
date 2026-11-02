"""Trace a genuine unchanged Cargo link and preserve the inputs behind its decision."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import consumer
from install import HOST, RECORDS, ROOT, SDK, save, sha

SRC = Path(os.environ['GITHUB_WORKSPACE']) / 'ruff'
STATE = ROOT / 'state'
OLD = 'bb868838d75876c3b016d8cf1687d33eae80daa6'
NEW = '9c53b5de3aae4b1832eb7ee137647dda2466f888'
LOCK = '26d7be8317b0e44be0d60b31f6660dd4e07ed4c19be4e6748124d07068fd7fa7'
COMMAND = ['cargo','+ohm','test','--no-run','-p','ruff_db','--lib','--locked','--offline','-j2','--message-format=json']
SNAPSHOTS = ['diagnostic::render::full::tests::output','diagnostic::render::full::tests::syntax_errors']
MARKER = re.compile(rb'[a-zA-Z0-9/_.\\:-]{0,180}ohm-(?:untracked|recheck|native|checked|proc-macro|foreign)[a-zA-Z0-9/_.:-]{0,110}')

def git(*args):
    return subprocess.check_output(['git','-C',SRC,*args],text=True).strip()

def environment():
    proxies=ROOT/'proxies';proxies.mkdir()
    rustup=Path(shutil.which('rustup')).resolve(strict=True)
    for name in ('rustc','rustdoc','cargo'):(proxies/name).symlink_to(rustup)
    toolchains=ROOT/'rustup/toolchains';toolchains.mkdir(parents=True)
    (toolchains/'ohm').symlink_to(SDK)
    (ROOT/'rustup/settings.toml').write_text('version = "12"\nprofile = "minimal"\n')
    for name in ('home','cargo-home','tmp'):(ROOT/name).mkdir()
    return {'HOME':str(ROOT/'home'),'PATH':str(proxies)+':/usr/bin:/bin','RUSTUP_HOME':str(toolchains.parent),
            'RUSTUP_AUTO_INSTALL':'0','CARGO_HOME':str(ROOT/'cargo-home'),'CARGO_TERM_COLOR':'never',
            'CARGO_TARGET_DIR':str(STATE/'target'),'CARGO_BUILD_BUILD_DIR':str(STATE/'build'),'TMPDIR':str(ROOT/'tmp'),
            'CARGO_CACHE_AUTO_CLEAN_FREQUENCY':'never','RUST_BACKTRACE':'0','LC_ALL':'C'}

def run_logged(folder,name,args,env):
    with (folder/(name+'.stdout')).open('wb') as out,(folder/(name+'.stderr')).open('wb') as err:
        proc=subprocess.run(args,cwd=SRC,env=env,stdout=out,stderr=err,timeout=720)
    if proc.returncode:
        raise RuntimeError((name,proc.returncode,(folder/(name+'.stderr')).read_bytes()[-6500:].decode(errors='replace')))

def test_artifact(rows):
    assert rows[-1]=={'reason':'build-finished','success':True}
    arcs=[r for r in rows if r['reason']=='compiler-artifact']
    test,=[r for r in arcs if r['target']['name']=='ruff_db' and r['target']['kind']==['lib'] and r['profile']['test']]
    roster=sorted([[r['package_id'],r['target']['name'],r['target']['kind'],r['features'],r['profile']['test']] for r in arcs])
    return Path(test['executable']),roster,sorted([r['target']['name'] for r in arcs if not r['fresh']])

def collect_markers(folder):
    markers=[];copied=0
    for path in STATE.rglob('*'):
        if not path.is_file() or path.is_symlink():continue
        selected=path.suffix=='.d' or ('.fingerprint' in path.parts and path.name.startswith('dep-'))
        named='ruff_db' in str(path) and (selected or '.fingerprint' in path.parts)
        if not (selected or named) or path.stat().st_size>12<<20:continue
        raw=path.read_bytes()
        observed=sorted({m.group().decode(errors='replace') for m in MARKER.finditer(raw)})
        name=path.relative_to(STATE)
        if observed:markers.append({'file':str(name),'markers':observed,'sha256':hashlib.sha256(raw).hexdigest()})
        if observed or named:
            where=folder/'inputs'/name;where.parent.mkdir(parents=True,exist_ok=True)
            where.with_name(where.name+'.gz').write_bytes(gzip.compress(raw,compresslevel=2,mtime=0));copied+=1
    (folder/'markers.json').write_text(json.dumps(dict(files=copied,records=markers),sort_keys=True,indent=2))

def native(executable,folder,env):
    listing=subprocess.check_output([executable,'--list','--format','terse'],cwd=SRC,env=env)
    assert len([s for s in listing.splitlines() if s.endswith(b': test')])==126
    (folder/'tests.list').write_bytes(listing)
    for test in SNAPSHOTS:
        run_logged(folder,test.split('::')[-1],[executable,'--exact',test,'--test-threads=1'],dict(env,INSTA_UPDATE='no'))
        assert b'1 passed; 0 failed' in (folder/(test.split('::')[-1]+'.stdout')).read_bytes()
    return hashlib.sha256(listing).hexdigest()

def main(role):
    assert role in ('22','23','253') and git('rev-parse',NEW+'^')==OLD and len(git('diff','--name-only',OLD,NEW).splitlines())==2
    assert sha(SRC/'Cargo.lock')==LOCK and not git('status','--porcelain')
    env=environment()
    save("environment.json",env)
    tools={k:subprocess.check_output([k,'+ohm','-vV'],env=env,text=True) for k in ('cargo','rustc')}
    save('versions.json',tools)
    git('checkout','--quiet','--detach',OLD)
    run_logged(RECORDS,'fetch',['cargo','+ohm','fetch','--locked','--target',HOST],env)
    observer=ROOT/'observe-exec'
    subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',HERE.parent/'ruff-heldout-mono-fold/observe_exec.c','-o',observer],check=True)
    visits={}
    old_sessions=set();old_pins={};old_objects={}
    refused=False
    for phase in ('old','edit','unchanged-1','unchanged-2','exec','fingerprint','clean'):
        if phase=='edit':git('checkout','--quiet','--detach',NEW)
        if phase=='clean':STATE.rename(ROOT/'prior-state')
        assert sha(SRC/'Cargo.lock')==LOCK and not git('status','--porcelain')
        folder=RECORDS/phase;folder.mkdir()
        argv=COMMAND
        visit_env=dict(env,CARGO_NET_OFFLINE='true')
        if phase=='exec':
            trace=folder/'execs';trace.mkdir();argv=[observer,trace,*COMMAND]
        if phase=='fingerprint':
            visit_env['CARGO_LOG']='cargo::core::compiler::fingerprint=trace,cargo::compiler::fingerprint=trace'
        run_logged(folder,'cargo',argv,visit_env)
        rows=[json.loads(line) for line in (folder/'cargo.stdout').read_bytes().splitlines()]
        exe,roster,dirty=test_artifact(rows)
        st=exe.stat()
        visits[phase]=dict(path=str(exe),roster=roster,dirty=dirty,sha256=sha(exe),dev=st.st_dev,
                           inode=st.st_ino,mtime_ns=st.st_mtime_ns,bytes=st.st_size)
        if phase in ('old','edit') and not refused:
            pins={}
            try:
                sessions,pins,objects=consumer.capture(STATE,old_sessions,tools['rustc'].splitlines()[0].removeprefix('rustc '),folder)
                save(phase+'/consumer-objects.json',objects)
                if phase=='old':
                    old_sessions,old_pins,old_objects=sessions,pins,objects
                else:
                    save('edit/retained-consumer.json',consumer.retained(old_objects,objects,old_pins))
            except (AssertionError,OSError,ValueError,KeyError) as e:
                # Optional CGU observations cannot decide the native correctness controls.
                refused=True
                save('consumer-refused.json',dict(phase=phase,error=repr(e)))
            finally:
                if phase=='edit' or refused:
                    for handle in (*old_pins.values(),*pins.values()):handle.close()
        if phase in ('old','edit','fingerprint'):
            collect_markers(folder)
        if phase=='old':
            visits[phase]['tests']=native(exe,folder,env)
        if phase in ('unchanged-2','exec','fingerprint','clean'):
            visits[phase]['tests']=native(exe,folder,env)
        save('visits.json',visits)
    baseline=visits['old']; reference=visits['clean']
    assert baseline['sha256']!=reference['sha256']
    assert all(q['sha256']==reference['sha256'] for k,q in visits.items() if k!='old')
    assert all(q['roster']==baseline['roster'] for q in visits.values())
    assert all(q['tests']==baseline['tests'] for q in visits.values() if 'tests' in q)
    trace=(RECORDS/'fingerprint/cargo.stderr').read_bytes()
    assert b'fingerprint' in trace and len(trace)>6000
    for path in RECORDS.rglob('*'):
        if path.is_file() and path.suffix in ('.stdout','.stderr') and path.stat().st_size>1<<17:
            path.with_suffix(path.suffix+'.gz').write_bytes(gzip.compress(path.read_bytes(),compresslevel=2,mtime=0));path.unlink()
    save('accepted.json',dict(role=role,head=os.environ['GITHUB_SHA'],repo=git('rev-parse','HEAD'),command=COMMAND,
                              unchanged_dirty=visits['unchanged-1']['dirty'],elf=reference['sha256'],units=len(baseline['roster'])))
if __name__=='__main__':main(sys.argv[1])
