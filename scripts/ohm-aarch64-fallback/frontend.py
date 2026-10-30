"""Check the real Ruff AST process and the Cargo environment at the incremental first edit."""
from hashlib import sha256
import json, os, threading
from pathlib import Path

def flags(argv):
    assert argv[argv.index('--crate-name')+1]=='ruff_python_ast' and argv[argv.index('--target')+1]=='aarch64-unknown-linux-gnu'
    cc=[v for i,v in enumerate(argv) if i and argv[i-1]=='-C']
    for v in argv:
        if v.startswith('-C') and len(v)>2:cc.append(v[2:])
    increments=[x.partition('=')[2] for x in cc if x.startswith('incremental=')]
    lto=[x for x in cc if x.startswith('lto=')]
    assert len(increments)==1 and Path(increments[0]).is_absolute() and lto==['lto=off'], (increments,lto)
    assert not any(v.startswith(('linker-plugin-lto','llvm-args=','passes=')) for v in cc)
    return {'incremental_directory':increments[0],'lto':'off','argv_sha256':sha256(json.dumps(argv,separators=(',',':')).encode()).hexdigest()}

def children(pid):
    out=set()
    for task in Path('/proc',str(pid),'task').glob('[0-9]*'):
        try:out.update(map(int,(task/'children').read_bytes().split()))
        except (FileNotFoundError,ProcessLookupError):pass
    return out

def with_live_environment(call, native, sdk):
    # This off-clock companion samples descendants of only this private acquisition process.
    stop=threading.Event(); found={};errors=[]
    bins={name:(sdk/'bin'/name).stat() for name in ('cargo','rustc')}
    def scan():
        try:
            while not stop.is_set():
                pending=[os.getpid()];seen=set()
                while pending:
                    pid=pending.pop()
                    if pid in seen:continue
                    seen.add(pid)
                    try:
                        pending.extend(children(pid))
                        if pid in found:continue
                        proc=Path('/proc',str(pid));st=(proc/'exe').stat()
                        name=next((n for n,b in bins.items() if (st.st_dev,st.st_ino)==(b.st_dev,b.st_ino)),None)
                        if name is None:continue
                        argv=(proc/'cmdline').read_bytes().split(b'\0');argv.pop();argv=list(map(os.fsdecode,argv))
                        if name=='rustc' and ('--crate-name' not in argv or argv[argv.index('--crate-name')+1]!='ruff_python_ast'):continue
                        # The later consumer link may run independently of Cargo after the measured rlib is complete.
                        if name=='cargo' and 'build' not in argv:continue
                        env=dict(v.split(b'=',1) for v in (proc/'environ').read_bytes().split(b'\0') if b'=' in v)
                        assert not {b'CI',b'RUSTFLAGS',b'CARGO_ENCODED_RUSTFLAGS',b'CARGO_INCREMENTAL',b'RUSTC_WRAPPER'}.intersection(env)
                        found[pid]={'kind':name,'argv':argv,'environment_keys':sorted(map(os.fsdecode,env)),
                            'flags':flags(argv) if name=='rustc' else None,'physical':{'dev':st.st_dev,'ino':st.st_ino}}
                    except (PermissionError,ProcessLookupError,FileNotFoundError):continue
                stop.wait(.02)
        except BaseException as e:errors.append(e)
    thread=threading.Thread(target=scan);thread.start()
    try:result=call()
    finally:stop.set();thread.join()
    assert not errors,errors
    rows=json.loads(native.read_bytes())
    cargo,=rows['cargo'];ast,=[x for x in rows['rustcs'] if x['crate']=='ruff_python_ast']
    for role,r in [('cargo',cargo),('rustc',ast)]:
        v=found[r['pid']];assert v['kind']==role and v['argv']==r['argv'] and r['terminal']==[0]
    return result,{n:found[r['pid']]|{'pid':r['pid']} for n,r in [('cargo',cargo),('ast',ast)]}
