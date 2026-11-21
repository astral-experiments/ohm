import re
import json
import subprocess
import shutil
import sys
import platform
from pathlib import Path

fixtures=json.loads((Path(__file__).parent/"fixture5.json").read_text())
package='[package]\nname="probe"\nversion="0.0.0"\nedition="2024"\n'
library="pub fn answer() -> u32 { 42 }\n"

def verify(root,log,cargo,settings):
    log.mkdir(exist_ok=True)
    parent=root/'probes5'
    parent.mkdir(exist_ok=True)
    rustc=cargo.parent/'rustc'
    tests=['C609-check','C609-build','C609-relink','C609-test','Y88','Y90','R569','R558','R552','R546','C582','C601','C597','L50','L53','L56']
    tests+=['Y'+str(n)+'-'+x for n in [88,90] for x in ['many','one-thread','four-threads','replay']]
    results={}
    for key in tests:
        path=parent/key
        if path.exists():shutil.rmtree(path)
        path.mkdir()
        env=dict(settings, CARGO_TARGET_DIR=str(path/'target'),CARGO_NET_OFFLINE='true')
        events=[]
        def write(file,source):
            p=path/file
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(source)
        def run(*args):
            cmd=list(map(str,args))
            proc=subprocess.run(cmd,env=env,cwd=path,text=True,capture_output=True,timeout=90)
            events.append(dict(args=cmd,code=proc.returncode,stdout=proc.stdout[:1200],stderr=proc.stderr[-2500:]))
            return proc
        def ok(*args):
            proc=run(*args)
            assert proc.returncode==0,(args,proc.stderr[-300:])
            return proc
        write('Cargo.toml',package)
        write('src/lib.rs',library)
        try:
            if key=='R569':
                write('Cargo.toml',package+'[profile.dev]\nopt-level=1\n')
                ok(cargo,'build')
                write('src/lib.rs',library+'\n')
                ok(cargo,'check');ok(cargo,'build');ok(cargo,'build')
            elif key=='R558':
                write('src/lib.rs',fixtures[key]);ok(cargo,'check')
            elif key=='R552':
                write('src/fragment.rs','#[cfg(any())] fn unused(){0'+'.foo()'*24576+';}')
                for n in range(2):
                    write('src/lib.rs',f'pub const N:i32={n};pub mod fragment;')
                    ok(cargo,'check')
            elif key=='R546':
                stem=[rustc,'src/lib.rs','--crate-type=lib','-Cincremental=cache','-Zohm-shared-stages']
                ok(*stem,'--emit=link')
                ok(*stem,'--emit=metadata','-Zdump-mir=all')
                n=len(list((path/'mir_dump').glob('*.mir')))
                events[-1]['mir']=n
                assert n>0
            elif key.startswith('Y'):
                env['CARGO_INCREMENTAL']='1'
                src=fixtures[key[:3]]
                if key.endswith('many'):
                    extra=''.join(f"pub fn aux{n}(a:bool,b:bool,c:bool,d:bool)->bool{{(a&&b)||(c&&d)}}\n" for n in range(40))
                    src=src.replace('fn main()',extra+'fn main()')
                if key.endswith('one-thread'): env['RUSTFLAGS']='-Zthreads=1'
                if key.endswith('four-threads'): env['RUSTFLAGS']='-Zthreads=4'
                write('src/main.rs',src)
                assert ok(cargo,'run','--quiet').stdout.strip()=='true'
                if key.endswith('replay'):ok(cargo,'clippy')
                code=run(cargo,'fixit','--clippy','--Zdangerous-parallel-fixes','--allow-no-vcs').returncode
                actual=(path/'src/main.rs').read_text()
                events[-1]['replacement']=[s for s in actual.splitlines() if 'let result'in s]
                out=ok(cargo,'run','--quiet').stdout.strip()
                assert code==0 and out=='true'
                assert ('!!word' if key[:3]=='Y88' else 'stored == key') in actual
            elif key=='C582':
                write('build.rs',fixtures[key]);ok(cargo,'check','--config','build.rustflags=["--cfg=special"]')
            elif key=='C601':
                lines=[chr(96)*3,'macro_rules! discard { ($x:tt) => {()}; }','discard!('+'('*8192+'0'+')'*8192+');',chr(96)*3]
                write('src/lib.rs',''.join('/// '+v+'\n'for v in lines)+'pub struct Item;\n')
                ok(cargo,'test','--doc')
            elif key=='C597':
                env['RUSTFLAGS']='-gZtime-passes'
                a=ok(cargo,'build');b=ok(cargo,'check')
                assert 'LLVM_passes' in a.stderr and 'LLVM_passes' not in b.stderr
            elif key.startswith('C609'):
                write('Cargo.toml',package+'[dependencies]\ndep={path="dep"}\n')
                write('dep/Cargo.toml',package.replace('probe','dep'))
                write('dep/src/lib.rs',library)
                write('dep/build.rs',fixtures['C609'])
                def change(n):write('dep/injected.rs',f'pub const VALUE: u32 = {n};\n')
                if key.endswith('check'):
                    write('src/lib.rs','extern crate injected; const _: () = assert!(injected::VALUE == 1);')
                    change(1);ok(cargo,'check');change(2)
                    warm=run(cargo,'check');fresh=run(cargo,'check','--target-dir','fresh')
                    assert 'E0080' in warm.stderr and 'E0080' in fresh.stderr
                    change(1);ok(cargo,'check')
                elif key.endswith('test'):
                    write('src/lib.rs','extern crate injected; #[test] fn valid(){assert_eq!(injected::VALUE,1);}')
                    for n in [1,2,3,1]:
                        change(n)
                        p=run(cargo,'-Zrelink-only','test','--lib')
                        assert (p.returncode==0)==(n==1) and (n==1 or f'left: {n}' in p.stdout)
                else:
                    if key.endswith('build'):
                        write('src/lib.rs','extern crate injected; pub fn value()->u32 {injected::VALUE}')
                        write('src/main.rs','fn main(){println!("{}",probe::value());}')
                        flags=[]
                    else:
                        write('src/main.rs','extern crate injected; fn main(){println!("{}",injected::VALUE);}')
                        flags=['-Zrelink-only']
                    values=[]
                    for n in [1,2,3]:
                        change(n)
                        values.append(int(ok(cargo,*flags,'run','--quiet').stdout))
                    assert values==[1,2,3]
            elif key.startswith('L'):
                flags=[rustc,'--crate-type=lib','-Ccodegen-units=1','-Copt-level=1']
                if key=='L50':
                    s=''.join(f'pub fn f{i:02}(x:u64)->u64 {{f{i+1:02}(f{i+1:02}(x))}}\n' for i in range(14))
                    s+='#[inline(never)] pub fn f14(x:u64)->u64{std::hint::black_box(x)}'
                    write('safe.rs',s)
                    ok(*flags,'--emit=llvm-ir,obj','safe.rs')
                    ir=(path/'safe.ll').read_text()
                    block=re.search(r'^define [^\n]*f00[^\n]*\n.*?^\}',ir,re.S|re.M)
                    n=block[0].count(' call ')
                    events[-1].update(calls=n,object_bytes=(path/'safe.o').stat().st_size)
                    assert n<=32
                else:
                    write('libpair.rs',fixtures[key])
                    ok(*flags,'--crate-name','pair','-Clto=off','-Cembed-bitcode=no','--emit=link,llvm-ir,obj','libpair.rs')
                    expr='assert_eq!(pair::round_trip(i),i);' if key=='L56' else 'assert_eq!(pair::a(i),pair::b(i));'
                    write('client.rs','fn main(){for i in 0..=255{'+expr+'}}')
                    ok(rustc,'client.rs','--extern','pair=libpair.rlib')
                    ok('./client')
            else:raise ValueError(key)
        except AssertionError as exc:
            events.append(dict(error=str(exc)))
            results[key]=False
        else:results[key]=True
        (log/(key+'.json')).write_text(json.dumps(events,indent=2))
        shutil.rmtree(path)
    return results

