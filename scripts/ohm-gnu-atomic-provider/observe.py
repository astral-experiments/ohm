"""Read original Linux strace process/files and Cargo product bodies. Never infer an execution from freshness."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
from sdk import ROOT, SDK, sha, save, digest

TARGET='aarch64-unknown-linux-gnu'
PREFIX='libqa_owned_atomic.a'
OUT=ROOT/'receipt'
OBJECTS=OUT/'objects'
DRIVER='aarch64-linux-gnu-gcc'
READER='/usr/bin/aarch64-linux-gnu-readelf'
AR='/usr/bin/aarch64-linux-gnu-ar'
def stored(data):
    h=digest(data);dest=OBJECTS/(h+'.gz')
    if not dest.is_file():dest.write_bytes(gzip.compress(data,compresslevel=4,mtime=0))
    assert gzip.decompress(dest.read_bytes())==data
    return h
def run(argv,cwd,env,timeout=120):
    return subprocess.run([str(a) for a in argv],cwd=cwd,env=env,capture_output=True,timeout=timeout)
def command(argv,cwd,env,where):
    p=run(argv,cwd,env);prefix=Path(where)
    save(prefix.with_suffix('.json'),{'argv':list(map(str,argv)),'returncode':p.returncode,
         'stdout':stored(p.stdout),'stderr':stored(p.stderr)})
    if p.returncode:raise RuntimeError((argv,p.returncode,p.stderr[-900:]))
    return p.stdout
def path_equal(a,b):
    try:return Path(a).samefile(b)
    except (FileNotFoundError,NotADirectoryError):return False

def traces(directory):
    parents={};execs={};paths={};raw_files={}
    parsed=json.JSONDecoder()
    for f in sorted(directory.glob('thread.*')):
        pid=int(f.name.split('.')[-1]);data=f.read_bytes(); raw_files[f.name]=digest(data)
        for line in data.decode(errors='replace').splitlines():
            if line.startswith(('clone(','clone3(','fork(','vfork(')):
                m=re.search(r'= (\d+)$',line)
                if m:parents[int(m[1])]=pid
            if line.startswith('execve(') and line.endswith('= 0'):
                body=line[7:];exe,x=parsed.raw_decode(body);a,_=parsed.raw_decode(body[x:].removeprefix(', ').lstrip())
                assert isinstance(a,list) and a
                tag=None;crate=None
                if path_equal(exe,SDK/'bin/rustc'):
                    crate=a[a.index('--crate-name')+1] if '--crate-name' in a else None
                    tag='link-only' if any(v.startswith('-Zlink-only') for v in a) else ('full' if crate else 'compiler-probe')
                elif path_equal(exe,SDK/'bin/cargo'):tag='cargo'
                elif Path(exe).name in ('ld','ld.bfd','ld.lld','aarch64-linux-gnu-ld','aarch64-linux-gnu-ld.bfd'):
                    tag='linker'
                elif Path(exe).name.endswith(('ar','gcc','collect2')) or 'build-script' in Path(exe).name:tag='native-helper'
                execs.setdefault(pid,[]).append({'exe':exe,'argv':a,'category':tag,'crate':crate})
            if PREFIX in line and line.startswith(('open(','openat(','openat2(','newfstatat(','statx(','access(')):
                paths.setdefault(pid,[]).append(line)
    def owner(pid):
        seen=set()
        while pid not in seen:
            seen.add(pid)
            if pid in execs and execs[pid]:
                for x in reversed(execs[pid]):
                    if x['category']:
                        return [pid,x['category'],x['crate']]
            if pid not in parents:break
            pid=parents[pid]
        return None
    opened=[{'pid':pid,'owner':owner(pid),'calls':calls} for pid,calls in sorted(paths.items())]
    entries=[dict(e,pid=pid) for pid in sorted(execs) for e in execs[pid]]
    return {'execs':entries,'opened':opened,'thread_files':raw_files}
def artifact(path,work,src,env,object_bodies):
    p=Path(path);raw=p.read_bytes();store=stored(raw)
    members=run([AR,'t',p],src,env);assert members.returncode==0
    names=members.stdout.decode().splitlines();assert len(names)==len(set(names))
    summary=[]; relocations=[]
    for n in names:
        row=run([AR,'p',p,n],src,env);assert row.returncode==0
        b=row.stdout
        summary.append({'name':n,'sha256':digest(b),'length':len(b),'matches_provider_object':[
            x for x,v in object_bodies.items() if v in b]})
        if b.startswith(b'\x7fELF') and b'qa_owned_word' in b:
            (work/'read-object.o').write_bytes(b)
            r=run([READER,'-Wr',work/'read-object.o'],src,env)
            syms=run([READER,'-Ws',work/'read-object.o'],src,env)
            assert r.returncode==syms.returncode==0
            relocations.append({'name':n,'relocations':[x.strip() for x in r.stdout.decode().splitlines() if 'qa_owned_word' in x],
                                'symbols':[x.strip() for x in syms.stdout.decode().splitlines() if 'qa_owned_word' in x]})
    return {'path':str(p),'sha256':store,'members':summary,'relocations':relocations}
def kind_marker(b):
    markers={'hard':b'/dev/null/ohm-untracked-relink-inputs:', 'v2':b'/dev/null/ohm-recheck-dependent-links-v2:', 'v1':b'/dev/null/ohm-recheck-dependent-links:'}
    found=[k for k,m in markers.items() if m in set(b.splitlines())]
    assert len(found)<=1
    return found[0] if found else None
def visit(src,work,env,where,objects):
    where.mkdir(parents=True);tr=where/'tmptrace';tr.mkdir()
    cmd=['cargo','+ohm','build','-p','qa_app','--offline','--locked','--target',TARGET,'-j2','--message-format=json']
    p=run(['strace','-ff','-qq','-s','32768','-e','trace=process,file','-o',tr/'thread',*cmd],src,env)
    for n,b in [('stdout',p.stdout),('stderr',p.stderr)]: (where/(n+'.gz')).write_bytes(gzip.compress(b,mtime=0))
    raw=traces(tr)
    # A short-lived child can have only a few file probes and no exec; keep its full original trace.
    archive=where/'kernel.tar.gz'
    with tarfile.open(archive,'x:gz',compresslevel=2) as w:
        for f in sorted(tr.iterdir()):w.add(f,arcname=f.name)
    with tarfile.open(archive) as w:
        assert {m.name:digest(w.extractfile(m).read()) for m in w.getmembers()}==raw['thread_files']
    shutil.rmtree(tr)
    inv=[json.loads(l) for l in p.stdout.splitlines() if l.strip()]
    done=[r for r in inv if r.get('reason')=='build-finished']
    assert p.returncode in (0,101) and (len(done)==1 and done[0]['success']==(p.returncode==0)),(p.returncode,p.stderr[-1200:])
    rust=[e for e in raw['execs'] if e['category'] in ('full','link-only')]
    libs={};products=[]
    for j in inv:
        if j.get('reason')!='compiler-artifact':continue
        name=j['target']['name']; products.append([name,j['target']['kind'],j['fresh'],j['filenames']])
        if name in ('qa_leaf','qa_plain'):
            for f in j['filenames']:
                if f.endswith('.rlib'):libs[name]=artifact(f,work,src,env,objects)
    depfiles={}
    for base in (work/'target',work/'shared'):
        for f in base.rglob('qa_*.d'):
            b=f.read_bytes()
            if '/src/lib.rs' in b.decode(errors='replace') or 'src/main.rs' in b.decode(errors='replace'):
                depfiles[str(f)]={'kind':kind_marker(b),'sha256':stored(b)}
    output=None
    refs={j['executable'] for j in inv if j.get('reason')=='compiler-artifact' and j['target']['name']=='qa_app' and j.get('executable')}
    if p.returncode==0:
        assert len(refs)==1
        elf=Path(refs.pop());b=elf.read_bytes();assert b[:6]==b'\x7fELF\x02\x01' and b[18:20]==b'\xb7\x00'
        q=run(['qemu-aarch64','-L','/usr/aarch64-linux-gnu',elf],src,env)
        assert q.returncode==0 and q.stdout in (b'17\n',b'29\n'),(q.returncode,q.stdout,q.stderr)
        output={'sha256':stored(b),'value':int(q.stdout),'path':str(elf),'qemu_stdout':stored(q.stdout),'qemu_stderr':stored(q.stderr)}
    messages=[r['message'] for r in inv if r.get('reason')=='compiler-message']
    diagnostics=[(m.get('code'),m['message'],m.get('rendered','')) for m in messages if m.get('level')=='error']
    if p.returncode:assert PREFIX.encode() in p.stderr+p.stdout or b'qa_owned_atomic' in p.stderr+p.stdout,(p.stderr,diagnostics)
    cross_link=[r for r in raw['execs'] if r['category']=='linker' and ('aarch64' in r['exe'] or any('aarch64' in a for a in r['argv']))]
    result={'argv':cmd,'cargo_exit':p.returncode,'value':output,'libs':libs,'typed':products,'depfiles':depfiles,
            'native':raw,'cross_linker_pids':[r['pid'] for r in cross_link], 'rustc':[(r['pid'],r['category'],r['crate']) for r in rust],
            'kernel_tar':sha(archive),'stdout':digest(p.stdout),'stderr':digest(p.stderr),'diagnostics':diagnostics}
    save(where/'result.json',result)
    print(where.relative_to(OUT),p.returncode,output and output['value'],[(x[1],x[2]) for x in result['rustc']],len(cross_link),flush=True)
    return result
