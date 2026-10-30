"""Bind the genuine kernel exec argv/environment to a stable same-inode /proc observation of the unscored Cargo edit."""
import ast
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import tarfile
import threading
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from ruff_subjects import rt
sys.path.insert(0,str(HERE.parent/'ohm-aarch64-fallback'))
import frontend
import fixed_study
q=fixed_study.q
STR=r'"(?:[^"\\]|\\.)*"'
ARRAY=rf'\[(?:{STR}(?:, {STR})*)?\]'
TRACE=re.compile(rf'^execve\(({STR}), ({ARRAY}), (?:NULL|0x[^)]*|{ARRAY})\)\s+= 0$')
FORBIDDEN={'CI','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','CARGO_INCREMENTAL','RUSTC_WRAPPER'}
def digest(b):
    return sha256(b).hexdigest()
def dump(p,v):
    p.open('x').write(json.dumps(v,sort_keys=True,indent=2)+'\n')
def identity(p):
    s=p.stat();return (s.st_dev,s.st_ino)
def actual(wire,want):
    rows={}
    with tarfile.open(fileobj=io.BytesIO(wire)) as tar:
        for f in tar:
            if not f.isfile():continue
            pid=int(f.name.rsplit('.',1)[1])
            if pid not in want:continue
            for line in tar.extractfile(f).read().splitlines():
                if not line.startswith(b'execve(') or not re.search(rb'\)\s+= 0$',line):continue
                path,argv,env=ast.literal_eval(re.sub(rb'\)\s+= 0$',b')',line.removeprefix(b'execve')).decode())
                w=want[pid]
                if path!=w['path']:continue
                assert pid not in rows and argv==w['argv'] and w['terminal']==[0]
                assert isinstance(env,list) and all(isinstance(x,str) and '=' in x for x in env)
                names=[x.split('=',1)[0] for x in env];assert len(names)==len(set(names)) and not FORBIDDEN.intersection(names)
                rows[pid]={'kernel_env_names':sorted(names),'raw_event_sha256':digest(line),'argv':argv,'path':path}
    assert set(rows)==set(want)
    return rows
def observe(call,native,sdk):
    bins={r:identity(sdk/'bin'/r) for r in ('cargo','rustc')}
    stop=threading.Event();seen={};errors=[]
    def scan():
        try:
            while not stop.is_set():
                pending=[os.getpid()];visited=set()
                while pending:
                    pid=pending.pop()
                    if pid in visited:continue
                    visited.add(pid);pending.extend(frontend.children(pid));p=Path('/proc',str(pid))
                    try:
                        st=identity(p/'exe');role=next((r for r,v in bins.items() if st==v),None)
                        if not role:continue
                        raw=(p/'cmdline').read_bytes()
                        if not raw.endswith(b'\0'):continue
                        argv=list(map(os.fsdecode,raw[:-1].split(b'\0')))
                        if role=='cargo' and 'build' not in argv:continue
                        if role=='rustc' and ('--crate-name' not in argv or argv[argv.index('--crate-name')+1:][:1]!=['ruff_python_ast']):continue
                        keys=sorted(os.fsdecode(v.split(b'=',1)[0]) for v in (p/'environ').read_bytes().split(b'\0') if b'=' in v)
                        if st!=identity(p/'exe') or raw!=(p/'cmdline').read_bytes():continue
                        ident=(pid,role,digest(raw),tuple(keys))
                        if ident not in seen:seen[ident]={'pid':pid,'kind':role,'argv':argv,'environment_keys':keys,'physical':dict(zip(('dev','ino'),st))}
                    except (PermissionError,ProcessLookupError,FileNotFoundError):continue
                stop.wait(.01)
        except BaseException as e:errors.append(e)
    original=rt.record;bound=[]
    def verbose(argv,folder,*a,**kw):
        if folder==native.parent/'cargo':
            assert str(argv[0])=='strace' and '-v' not in argv and not bound
            argv=[argv[0],'-v',*argv[1:]];bound.append(str(folder))
        return original(argv,folder,*a,**kw)
    thread=threading.Thread(target=scan);thread.start();rt.record=verbose
    try:result=call()
    finally:rt.record=original;stop.set();thread.join()
    assert len(bound)==1 and not errors and bins=={r:identity(sdk/'bin'/r) for r in bins}
    n=json.loads(native.read_bytes());cargo,=n['cargo'];root,=[r for r in n['rustcs'] if r['crate']=='ruff_python_ast']
    want={v['pid']:v for v in (cargo,root)}
    wire=(native.parent/'exec.tar.gz').read_bytes()
    real=actual(wire,want)
    # Keep all stable alternatives if a legitimate argv observer loses a PID's exec transition.
    hold={'kernel':real,'live':list(seen.values()),'original_trace':digest(wire)}
    dump(native.parent/'raw-physical-environment-proof.json',hold)
    chosen={}
    for key,r,role in (('cargo',cargo,'cargo'),('ast',root,'rustc')):
        state=real[r['pid']]
        options=[s for s in seen.values() if s['pid']==r['pid'] and s['kind']==role and s['argv']==r['argv'] and s['environment_keys']==state['kernel_env_names']]
        assert len(options)==1,(role,r['pid'],len(options),[(s['kind'],s['pid'],s['argv'][:3]) for s in seen.values()])
        sole,=options;chosen[key]={**sole,'flags':frontend.flags(r['argv']) if key=='ast' else None,'kernel_exec_sha256':state['raw_event_sha256']}
    return result,chosen
def install():
    q.EXEC=TRACE
    frontend.with_live_environment=observe

def verify(z,p):
    get=lambda name:json.loads(z.read(p+'/'+name))
    h=get('raw-physical-environment-proof.json');issued=get('native.json')
    actual_live=get('real-cargo-and-AST-environment.json')
    cmd=get('cargo/command.json')
    assert cmd['argv'][:2]==['strace','-v']
    trace=z.read(p+'/exec.tar.gz');assert h['original_trace']==digest(trace)
    cargo,=issued['cargo'];root,=[v for v in issued['rustcs'] if v['crate']=='ruff_python_ast']
    kernel=actual(trace,{v['pid']:v for v in (cargo,root)})
    assert {str(k):v for k,v in kernel.items()}==h['kernel']
    for name,real,kind in [('cargo',cargo,'cargo'),('ast',root,'rustc')]:
        record=actual_live[name]
        valid=[s for s in h['live'] if s['pid']==real['pid'] and s['kind']==kind and s['argv']==kernel[real['pid']]['argv'] and s['environment_keys']==kernel[real['pid']]['kernel_env_names']]
        row,=valid
        assert all(record[k]==v for k,v in row.items()) and record['kernel_exec_sha256']==kernel[real['pid']]['raw_event_sha256']
        assert record['flags']==(frontend.flags(real['argv']) if kind=='rustc' else None)
    return h['original_trace']
