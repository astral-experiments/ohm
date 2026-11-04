"""Census Cargo's default workspace test build and its real compiler and linker children."""
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import mmap
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess as sp
import sys
import time
import tomllib
import urllib.request

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/'ruff-foreign-span-observer'))
import worker as w

SPEC = json.loads((HERE/'workspace29697-registration.json').read_bytes())
OLD, NEW = SPEC['old'], SPEC['new']
CMD = SPEC['command']
PROOF = w.proof
PHYSICAL = {}


def write(path, data):
    content = json.dumps(data, separators=(',', ':'), sort_keys=True).encode()
    path.write_bytes(gzip.compress(content, mtime=0) if path.suffix == '.gz' else content+b'\n')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def select(revision):
    w.git('switch','--detach',revision)
    assert w.git('rev-parse','HEAD') == revision and not w.git('status','--porcelain')
    assert all(w.hf(w.work/name) == digest for name,digest in SPEC['source'][revision].items())


def inputs(env):
    assert not any(p.exists() for p in (w.target,w.shared,w.home))
    online = dict(env)
    online.pop('CARGO_NET_OFFLINE',None)
    sp.run(['cargo','+ohm','fetch','--locked'],env=online,cwd=w.work,check=True,timeout=720)
    lock=tomllib.loads((w.work/'Cargo.lock').read_text())
    expected = {p['name']+'-'+p['version']+'.crate':p for p in lock['package'] if p.get('source','').startswith('registry+')}
    assert len(expected)==SPEC['registry'] and not any(p.get('source','').startswith('git+') for p in lock['package'])
    cache,=(w.home/'registry/cache').iterdir()
    for name,rec in expected.items():
        f=cache/name
        if not f.exists():  # Locked, possibly target-only archive untouched by fetch on this host.
            url='https://static.crates.io/crates/'+rec['name']+'/'+name
            with urllib.request.urlopen(url,timeout=50) as src,f.open('xb') as out:shutil.copyfileobj(src,out)
        assert w.hf(f)==rec['checksum']
    assert {p.name for p in cache.iterdir()}==set(expected)
    env['CARGO_NET_OFFLINE']='true'
    return {n:r['checksum'] for n,r in expected.items()}


def exec_proof(td):
    def identity(p):
        x=p.stat();return x.st_dev,x.st_ino
    sdk_rustc=identity(w.sdk/'bin/rustc')
    sdk_wild=identity(w.sdk/'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd')
    images={};parents={};by_tgid=defaultdict(list);counters=defaultdict(lambda:[0,0,0]);outer=[]
    for line in (td/'epochs.tsv').read_text().splitlines():
        v=line.split()
        if v[0]=='F':
            parent,caller,child,event=map(int,v[1:])
            assert child not in parents;parents[child]=parent
        elif v[0]=='C':
            epoch,tgid,tid,ins,enable,run=map(int,v[1:]);assert min(ins,enable,run)>=0 and enable>=run
            for i,n in enumerate((ins,enable,run)):counters[epoch][i]+=n
        elif v[0]=='W':
            outer.append(list(map(int,v[1:])))
        elif v[0]=='I':
            _,idx,tg,tid,mono,why=v;idx,tg,tid=map(int,(idx,tg,tid))
            assert idx not in images and why in ('first','exec')
            file=td/f'{idx:05}.nul';raw=file.read_bytes();fields=raw.split(b'\0')
            assert fields[-1]==b'' and int(fields[0])==tg
            key=tuple(map(int,fields[1:3]));path=os.fsdecode(fields[3]);args=list(map(os.fsdecode,fields[4:-1]))
            def flag(name):return args[args.index(name)+1] if name in args else None
            mode='other';owner=None;replay=[];output=None
            if key==sdk_rustc:
                owner=flag('--crate-name')
                replay=[a for a in args[1:] if not a.startswith('-') and a.endswith('.rlink')]
                only=any(a in ('-Zlink-only','-Zlink-only=yes') or i and args[i-1]=='-Z' and a in ('link-only','link-only=yes') for i,a in enumerate(args))
                assert not only or len(replay)==1,(args,only)
                mode='link-only' if only else 'config' if not owner else 'test' if '--test' in args else 'metadata' if any(a.startswith('--emit=') and 'link' not in a.split('=',1)[1].split(',') for a in args) else 'full'
                if mode=='link-only' and not owner:owner=Path(replay[0]).stem
            elif key==sdk_wild:
                mode='Wild';output=flag('-o') or next((a.split('=',1)[1] for a in args if a.startswith('--output=')),None)
                assert output
            else:
                executable=Path(path).name
                if executable in ('ld','ld.lld','ld.gold','ld.bfd','lld','rust-lld','mold','wild','ld.wild') or executable.endswith(('-ld','-ld.bfd','-ld.gold','-ld.lld','-ld.wild')):
                    mode='native-linker/'+executable;output=flag('-o') or next((a.split('=',1)[1] for a in args if a.startswith('--output=')),None)
                elif executable=='ar' or executable.endswith(('-ar','gcc-ar')):mode='archiver'
                elif executable=='collect2' or executable in ('cc','c++','gcc','g++','clang','clang++') or executable.endswith(('-gcc','-g++','-clang')):mode='native-driver'
            entry=dict(epoch=idx,pid=tg,tid=tid,trigger=why,mode=mode,crate=owner,rlink=replay,path=path,dev=key[0],ino=key[1],argv=file.name,argv_sha256=sha(raw),output=output,source=next((a for a in args[1:] if a.endswith('.rs') and not a.startswith('-')),None),crate_types=[a for i,a in enumerate(args)if i and args[i-1]=='--crate-type'])
            images[idx]=entry
            if why=='exec':by_tgid[tg].append(entry)
    def upstream(item):
        pid=item['pid'];seen=set()
        while pid in parents:
            assert pid not in seen;seen.add(pid);pid=parents[pid]
            candidates=[r for r in by_tgid[pid] if r['epoch']<=item['epoch'] and r['mode'] in ('full','metadata','test','link-only')]
            if candidates:return candidates[-1]['epoch']
        return None
    for idx,r in images.items():
        r['counter']=counters[idx]
        if (r['mode']=='Wild' or r['mode'].startswith('native-linker/')) and r['trigger']=='exec':r['owning_rustc_epoch']=upstream(r)
    assert len(outer)==1 and outer[0][-1]==0 and outer[0][0]>0
    assert not(set(counters)-set(images))
    return {'roles':list(images.values()),'outer':outer[0],'logical_forks':len(parents),'real_execs':dict(Counter(x['mode'] for x in images.values()if x['trigger']=='exec')),'fork_or_start_images':dict(Counter(x['mode'] for x in images.values() if x['trigger']=='first'))}


def elf(path):
    with path.open('rb') as f:
        st=os.fstat(f.fileno());ident=(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
        if ident in PHYSICAL:return PHYSICAL[ident]
        with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as m:
            assert m[:6]==b'\x7fELF\x02\x01' and int.from_bytes(m[18:20],'little')==62
            soff=struct.unpack_from('<Q',m,40)[0];width,count,names=struct.unpack_from('<HHH',m,58)
            assert width==64 and 0<names<count and soff+width*count<=len(m)
            sh=lambda n:struct.unpack_from('<IIQQQQIIQQ',m,soff+width*n)
            off,size=sh(names)[4:6];strings=m[off:off+size];parts=[]
            for i in range(count):
                nm,kind,flags,addr,o,s,*rest=sh(i);name=strings[nm:strings.index(b'\0',nm)].decode()
                assert kind==8 or o+s<=len(m)
                parts.append([name,kind,flags,s,None if kind==8 else sha(memoryview(m)[o:o+s])])
            item={'sha256':sha(m),'bytes':len(m),'sections':parts}
        after=os.fstat(f.fileno())
        assert ident==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
    PHYSICAL[ident]=item
    return item


def save_elf(path):
    content=elf(path);dest=PROOF/(content['sha256']+'.elf.zst')
    if not dest.exists():
        with dest.open('xb') as f:sp.run(['zstd','-q','-3','-c',path],stdout=f,check=True)
    return content['sha256']


def run(argv,env,td,allowed=0,*,pass_fds=()):
    w.guard();start=time.monotonic();resources=[(w.avail(),shutil.disk_usage(w.root).free)]
    with (td/'stdout.jsonl').open('xb') as out,(td/'stderr').open('xb') as err:
        child=sp.Popen(argv,cwd=w.work,env=env,stdout=out,stderr=err,start_new_session=True,pass_fds=pass_fds)
        try:
            while child.poll() is None:
                mem=w.avail();free=shutil.disk_usage(w.root).free;resources.append((mem,free))
                if mem<8*2**30 or free<15*2**30 or time.monotonic()-start>70*60:raise RuntimeError(('private resource guard',mem,free))
                time.sleep(0.5)
        finally:
            if child.poll() is None:os.killpg(child.pid,signal.SIGTERM);child.wait()
    write(td/'resources.json',{'minimum_mem':min(x[0]for x in resources),'minimum_disk':min(x[1]for x in resources),'seconds':time.monotonic()-start,'exit':child.returncode})
    assert child.returncode==allowed,(td,child.returncode,(td/'stderr').read_text()[-1400:])


def inventory(name,env,graph,kind='whole'):
    td=PROOF/name;td.mkdir();a=list(CMD)
    if kind=='plain':assert a[0]=='cargo' and shutil.which(a[0],path=env['PATH'])
    elif kind=='whole':a=[w.root/'whole_count',td/'hardware.json',shutil.which('cargo',path=env['PATH']),*a]
    else:
        (td/'tasks').mkdir();a=[w.root/'exec_count',td/'tasks',*a]
    run(a,env,td)
    rows=list(map(json.loads,(td/'stdout.jsonl').read_bytes().splitlines()))
    assert rows[-1]=={'reason':'build-finished','success':True}
    outputs={};sources={};units=[]
    for msg in rows:
        if msg['reason']!='compiler-artifact':continue
        t=msg['target'];pkg=msg['package_id'];unit=[pkg,t['name'],t['kind'],sorted(msg['features']),msg['profile']['test']]
        units.append([unit,msg['fresh']])
        if pkg in graph['workspace_members'] or t['name']=='ron':
            for p in map(Path,msg['filenames']):
                assert p.is_file() and p.resolve().is_relative_to(w.root)
                if p.suffix in ('.rlib','.rmeta','.so'):
                    sources[str(p.relative_to(w.root))]=[p.stat().st_size,w.hf(p)]
        if msg.get('executable'):
            p=Path(msg['executable']);assert p.is_file() and p.resolve().is_relative_to(w.root)
            rel=str(p.relative_to(w.root)); assert rel not in outputs,(rel,pkg,t['name'])
            outputs[rel]={'unit':unit,'elf':elf(p)}
    matches=[w.root/k for k,row in outputs.items() if row['unit'][0] in graph['workspace_members'] and '/ty_server#' in row['unit'][0] and row['unit'][1:3]==['e2e',['test']]]
    if not matches:matches=[w.root/k for k,row in outputs.items()if 'ty_server' in row['unit'][0] and row['unit'][1:3]==['e2e',['test']]]
    e2e,=matches; save_elf(e2e)
    assert len(units)>500 and len(outputs)>=50
    data={'state':w.git('rev-parse','HEAD'),'units':sorted(units,key=repr),'binary':str(e2e.relative_to(w.root)),'executables':outputs,'workspace_artifacts_and_ron':sources}
    if kind=='whole':
        hw=json.loads((td/'hardware.json').read_bytes())
        assert hw['instructions']>0 and hw['running']==hw['enabled']>0 and hw['status']==0
    elif kind != 'plain':write(td/'owner-census.json.gz',exec_proof(td/'tasks'))
    write(td/'inventory.json.gz',data)
    assert not w.git('status','--porcelain')
    return data


def verdict(exe,tag,env,code):
    td=PROOF/tag;td.mkdir()
    e=dict(env,INSTA_UPDATE='no',INSTA_FORCE_PASS='0',CI='true')
    testroot=w.work/'crates/ty_server'
    listed=sp.run([exe,'--list'],cwd=testroot,env=e,check=True,capture_output=True,timeout=90);assert not listed.stderr
    names=[line.removesuffix(': test')for line in listed.stdout.decode().splitlines()if line.endswith(': test')]
    name,=[n for n in names if n.endswith('::debug_command')];assert len(set(names))==len(names)>=100
    (td/'test-list').write_bytes(listed.stdout)
    v=sp.run([exe,'--exact',name,'--nocapture'],cwd=testroot,env=e,capture_output=True,timeout=90)
    (td/'stdout').write_bytes(v.stdout);(td/'stderr').write_bytes(v.stderr)
    assert v.returncode==code and (b'1 passed;' if code==0 else b'1 failed;') in v.stdout
    if code:assert b'script_tag' in v.stdout and b'source_text' in v.stdout
    return sha(listed.stdout)


def main():
    assert os.environ['GITHUB_SHA']==os.environ['REVIEWED_HEAD'] and os.environ['GITHUB_RUN_ATTEMPT']=='1'
    assert w.hf(w.src/'sdk.json')==SPEC['sdk_manifest'] and w.git('rev-parse','HEAD')==NEW and w.git('rev-parse','HEAD^')==OLD
    assert shutil.disk_usage(w.root).free>45*2**30
    write(PROOF/'registration.json',{'study':SPEC,'head':os.environ['GITHUB_SHA'],'run':os.environ['GITHUB_RUN_ID'],'attempt':1,'runner':os.environ['RUNNER_NAME'],'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'caps':sorted(os.sched_getaffinity(0))})
    env=w.install();write(PROOF/'environment.json',env)
    for name in ('exec_count','whole_count'):
        sp.run(['cc','-Wall','-Wextra','-Werror','-O2',HERE/(name+'.c'),'-o',w.root/name],check=True)
    select(OLD);write(PROOF/'locked-registry.json.gz',inputs(env))
    graph=json.loads(sp.check_output(['cargo','+ohm','metadata','--format-version=1','--locked','--offline','--no-deps'],cwd=w.work,env=env))
    assert sorted(graph['workspace_default_members'])==sorted(graph['workspace_members'])
    assert sorted(x['name']for x in graph['packages']if x['id']in graph['workspace_default_members'])==SPEC['default_members']
    write(PROOF/'cargo-metadata.json.gz',graph)
    units=json.loads(sp.check_output([*CMD[:2],'-Zunstable-options',*CMD[2:-1],'--unit-graph'],cwd=w.work,env=env))
    assert units['version']==1 and units['roots']
    write(PROOF/'unit-graph.json.gz',units)
    for path in (w.target,w.shared):
        if path.exists():
            assert path.parent==w.root and path.is_dir() and not path.is_symlink()
            shutil.rmtree(path)
    assert not w.target.exists() and not w.shared.exists()
    old=inventory('ordinary-old',env,graph);e2e=w.root/old['binary'];names=verdict(e2e,'old-verdict',env,0)
    # Only the selected executable is kept for the genuine OLD-on-NEW native control.
    held=w.root/'OLD-before-edit';shutil.copy2(e2e,held);select(NEW)
    assert verdict(held,'old-on-new',env,101)==names
    edit=inventory('ordinary-edit',env,graph);assert verdict(w.root/edit['binary'],'edited-verdict',env,0)==names
    warm=inventory('first-unchanged',env,graph);warm2=inventory('repeat-unchanged',env,graph)
    observed=inventory('unchanged-observed',env,graph,'census')
    source=w.work/'crates/ty_server/src/session.rs';orig=source.read_bytes();td=PROOF/'invalid';td.mkdir()
    try:
        source.write_bytes(orig+b'\nconst _: u8 = "invalid workspace build";\n')
        run(CMD,env,td,101)
        messages=list(map(json.loads,(td/'stdout.jsonl').read_bytes().splitlines()))
        assert messages[-1]=={'reason':'build-finished','success':False}
        assert any(m['reason']=='compiler-message' and (m['message'].get('code') or {}).get('code')=='E0308' for m in messages)
        assert not any(m['reason']=='compiler-artifact' and 'ty_server' in m['package_id'] and m['target']['kind']==['test'] and m['target']['name']=='e2e' for m in messages)
    finally:source.write_bytes(orig)
    repair=inventory('repair',env,graph);assert verdict(w.root/repair['binary'],'repair-verdict',env,0)==names
    # All trees are private to this one ephemeral job. Keep previous proof outside them.
    for directory in (w.target,w.shared,w.home):
        assert directory.parent==w.root and directory.is_dir() and not directory.is_symlink();shutil.rmtree(directory)
    PHYSICAL.clear();inp=inputs(env);assert inp==json.loads(gzip.decompress((PROOF/'locked-registry.json.gz').read_bytes()))
    clean=inventory('independent-NEW',env,graph);assert verdict(w.root/clean['binary'],'clean-verdict',env,0)==names
    select(OLD);back=inventory('reverse-observed',env,graph,'census');assert verdict(w.root/back['binary'],'reverse-verdict',env,0)==names
    select(NEW);again=inventory('edit-observed',env,graph,'census');assert verdict(w.root/again['binary'],'edited-again-verdict',env,0)==names
    againwarm=inventory('repeat-observed',env,graph,'census')
    base=set(clean['executables']);assert all(set(x['executables'])==base for x in (old,edit,warm,warm2,observed,repair,back,again,againwarm))
    digest=lambda x,k:x['executables'][k]['elf']['sha256']
    def delta(a,b):return sorted(k for k in base if digest(a,k)!=digest(b,k))
    def dirty(x):return sorted((u for u,f in x['units']if not f),key=repr)
    results={'executables':len(base),'test_profile_executables':sum(row['unit'][-1]for row in clean['executables'].values()),'old_to_rebuilt_new':delta(old,edit),'edited_to_clean':delta(edit,clean),'edited_to_first':delta(edit,warm),'first_to_repeat':delta(warm,warm2),'first_to_observed':delta(warm,observed),'repaired_to_clean':delta(repair,clean),'reverse_to_original':delta(back,old),'again_to_clean':delta(again,clean),'again_warm_to_clean':delta(againwarm,clean),'edit_and_traced_dirty_equal':dirty(edit)==dirty(again),'warm_and_traced_dirty_equal':dirty(warm)==dirty(observed),'e2e_raw_equal_clean':all(digest(x,x['binary'])==digest(clean,clean['binary']) for x in (edit,warm,warm2,observed,repair,again,againwarm)),'e2e_old_differs':digest(old,old['binary'])!=digest(clean,clean['binary']),'binary_inventory_shas':{tag:sha(json.dumps(sorted(digest(x,k)for k in base)).encode())for tag,x in [('old',old),('new',edit),('clean',clean)]}}
    write(PROOF/'decision.json',results)
    assert results['e2e_raw_equal_clean'] and results['e2e_old_differs'] and not w.git('status','--porcelain')
    assert sum(p.stat().st_size for p in PROOF.rglob('*')if p.is_file())<=480*2**20

if __name__=='__main__':main()
