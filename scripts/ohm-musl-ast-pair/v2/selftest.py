#!/usr/bin/env python3
"""Check positive evidence and deliberately corrupt diagnostic stand-ins, without running Cargo."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from evidence import APP,PRODUCER,HARD,V2,LIB,encoded,lines,observe,raw_rule,save,sha

def rejected(f):
    try:f()
    except (AssertionError,IndexError,ValueError):return True
    raise AssertionError("a negative evidence mutation was accepted")

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--real-hard-depfile',type=Path);p.add_argument('--out',type=Path)
    a=p.parse_args()
    u=lambda n:struct.pack('<I',n)
    def st(v):b=v.encode();return u(len(b))+b
    body=b'\x01\0\0\0\xff\x04'+u(2)+b'\0'+st('src/lib.rs')+b'\0\1'+st(V2)+b'\0'+u(0)
    with_link=body+b'LNK1'+u(1)
    correct=bytes.fromhex(subprocess.check_output(['b3sum'],input=with_link).decode().split()[0])
    assert encoded(with_link+correct)['LNK1']==V2
    assert encoded(body)['LNK1'] is None and encoded(body)['markers']==[V2]
    assert rejected(lambda:encoded(with_link+correct[:-1]+bytes([correct[-1]^1])))
    assert rejected(lambda:encoded(body+b'LNK1'+u(0)+correct))
    assert rejected(lambda:encoded(with_link+correct+b'trailing'))
    assert rejected(lambda:encoded(body[:-1]))
    d=Path('/aaa/role.d')
    raw=('/aaa/librole.rlib: source.rs '+V2+'\n\n/aaa/role.d: source.rs\n\nsource.rs:\n'+V2+':\n').encode()
    assert raw_rule(d,raw)==[V2]
    assert rejected(lambda:raw_rule(d,raw.replace(b'role.d: source.rs',b'role.d: source.rs '+V2.encode())))
    assert rejected(lambda:raw_rule(d,raw.replace(V2.encode()+b':\n',HARD.encode()+b':\n')))
    out={"authenticated_encoded_v2":hashlib.sha256(with_link+correct).hexdigest(),
         "mutations":["BLAKE3","trailer-index","extra-byte","truncation","marker-in-real-input-rule","substituted-fake-target"]}
    if a.real_hard_depfile:
        path=a.real_hard_depfile.resolve(strict=True);assert raw_rule(path,path.read_bytes())==[HARD]
        out["actual_prior_musl_hard_source"]=[path.name,sha(path)]
    # The main linker and an unrelated process in the same tree both access the archive.
    # Only the actual -o app linker's worker may determine the selected provider.
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);sdk=root/'sdk';(sdk/'bin').mkdir(parents=True)
        for n in ('cargo','rustc','ld'):(sdk/'bin'/n).write_bytes(n.encode())
        driver=sdk/'librustc_driver-abc.so';driver.write_bytes(b'D')
        target=root/'target';target.mkdir()
        early=str(root/'early'/LIB);late=str(root/'late'/LIB)
        trace=root/'trace';trace.mkdir()
        def execrow(name,argv):
            return 'execve('+json.dumps(str(sdk/'bin'/name))+', '+json.dumps(argv)+', 0xaaa /* 10 vars */) = 0'
        def opened(path,fd=3):return f'openat(AT_FDCWD</work>, "{path}", O_RDONLY|O_CLOEXEC) = {fd}<{path}>'
        def rows(pid,*ls): (trace/f'pid.{pid}').write_text(''.join(f'1123456789.{i:06d} {l}\n' for i,l in enumerate(ls,1)))
        enc=str(target/('dep-lib-'+PRODUCER))
        rows(10,execrow('cargo',['cargo','build']),'clone(flags=CLONE_THREAD) = 11','clone(flags=SIGCHLD) = 12','+++ exited with 0 +++')
        rows(11,opened(enc),'+++ exited with 0 +++')
        rows(12,execrow('rustc',['rustc','--crate-name',APP,'--emit=link','--target','x86_64-unknown-linux-musl']),
             opened(str(driver)),opened(enc),'clone(flags=SIGCHLD) = 13',opened(early),'+++ exited with 0 +++')
        rows(13,execrow('ld',['ld','-o',str(target/(APP+'-abcdef'))]),'clone(flags=CLONE_THREAD) = 14','+++ exited with 0 +++')
        rows(14,f'openat(AT_FDCWD</work>, "{early}", O_RDONLY) = -1 ENOENT (No such file or directory)',
             opened(late),'+++ exited with 0 +++')
        records=observe(trace,root,sdk,[target],{early,late})
        assert records['selected']==[late] and len(records['provider_fd'])==2 and len(records['linkers'])==1
        assert len(records['linkers'][0]['negative'])==1 and [x[1] for x in records['dep_read']]==[11]
        assert records['compilers'][0]['crate']==APP and records['driver_open'][0][0]==12
        assert list(lines('0123.01 clone( <unfinished ...>\n0123.02 <... clone resumed>) = 23'))==[('0123.02','clone( ) = 23')]
        broken=(trace/'pid.12').read_text().replace(' = 13',' = 16')
        (trace/'pid.12').write_text(broken)
        assert rejected(lambda:observe(trace,root,sdk,[target],{early,late}))
        out["parsed_trace"]={"archive_opens":2,"opens_attributable_to_linker":1,"cargo_thread_reads":1,
                             "rustc_spurious_dep_read_ignored":1,"disconnected_linker_rejected":True}
    if a.out: save(a.out,out)
    print(json.dumps(out,sort_keys=True))
if __name__=='__main__':main()
