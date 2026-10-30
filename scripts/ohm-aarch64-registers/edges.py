"""Separate real Rust dependency edits from changes to a native provider Cargo was never told to watch."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import subject
from subject import rt
from tree_ir import q
from study import MISSING,RECHECK,need,save,sha

BARRIER='''#[inline(never)] pub fn barrier(mut x:usize)->usize {
    let mut v:core::arch::aarch64::int32x4_t=unsafe{core::mem::zeroed()};
    unsafe {core::arch::asm!("/*{0}*/",inout(reg)x); core::arch::asm!("/*{:v}*/",inout(vreg)v);}
    core::hint::black_box(v);x
}
'''
MAIN='''#[link(name="qa_owned_external",kind="static")] unsafe extern "C" {fn qa_value()->i32;}
fn main(){println!("{} {}", barrier(unsafe{qa_value()} as usize),trigger::value());}
'''
BUILD='''fn main(){
 let dir=std::path::PathBuf::from(std::env::var_os("CARGO_MANIFEST_DIR").unwrap());
 println!("cargo:rerun-if-changed=build.rs");
 for n in ["early","late"]{println!("cargo:rustc-link-search=native={}",dir.join(n).display());}
}
'''
def write(p,s):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(s)
def run(root, role, placement, defaults, stock_source=None):
    cwd=rt.ROOT/'edges';cwd.mkdir(); env=rt.environment();work=rt.ROOT/'edges-work';work.mkdir()
    env.update(CARGO_HOME=str(work/'cargo-home'),CARGO_TARGET_DIR=str(work/'target'),CARGO_BUILD_BUILD_DIR=str(work/'shared'),
               CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=q.CROSS)
    if stock_source:
        for name in ("target","shared"):(work/name).mkdir()
    manifest='[package]\nname="qa_owned_test"\nversion="0.0.1"\nedition="2021"\n[dependencies]\ntrigger={path="trigger"}\n'
    if placement=='library':manifest+='barrier={path="barrier"}\n'
    write(cwd/'Cargo.toml',manifest);write(cwd/'build.rs',BUILD)
    write(cwd/'trigger/Cargo.toml','[package]\nname="trigger"\nversion="0.0.1"\nedition="2021"\n')
    if placement=='library':
        write(cwd/'barrier/Cargo.toml','[package]\nname="barrier"\nversion="0.0.1"\nedition="2021"\n')
        write(cwd/'barrier/src/lib.rs',BARRIER);write(cwd/'src/main.rs','use barrier::barrier;\n'+MAIN)
    else:write(cwd/'src/main.rs',BARRIER+MAIN)
    (cwd/'early').mkdir();(cwd/'late').mkdir()
    early=cwd/'early/libqa_owned_external.a';late=cwd/'late/libqa_owned_external.a';src=cwd/'trigger/src/lib.rs'
    def version(number):write(src,f'#[inline(never)] pub fn value()->i32{{{number}}}\n')
    def ar(val,dest):
        write(cwd/'provider.c','int qa_value(void){return '+str(val)+';}\n')
        rt.record([q.CROSS,'-c','-o','implicit.o','provider.c'],root/('make-'+str(val))/'cc',cwd,env)
        rt.record(['/usr/bin/aarch64-linux-gnu-ar','rcs',dest,'implicit.o'],root/('make-'+str(val))/'ar',cwd,env)
        return dest.read_bytes()
    version(7);initial=ar(17,late)
    arms=[]
    def visit(name,clean=False):
        path=root/name;path.mkdir(parents=True);trace=path/'trace';trace.mkdir();saved=work/('pre-'+name)
        homes=[work/'target',work/'shared']
        if clean:
            saved.mkdir()
            for p in homes:p.rename(saved/p.name)
        args=['cargo','+ohm']+([] if defaults else ['-Zohm-defaults=no'])+['build','--offline','--target',rt.TARGET,'-j4','--message-format=json']
        import subprocess
        cmd=['strace','-ff','-q','-s','262144','-e','trace=execve,execveat,openat','-o',str(trace/'proc'),*args]
        ps=subprocess.run(cmd,cwd=cwd,env=env,capture_output=True,timeout=180)
        need(ps.returncode in (0,101),'non-Cargo termination')
        for n,b in [('stdout',ps.stdout),('stderr',ps.stderr)]:(path/(n+'.gz')).write_bytes(gzip.compress(b,2,mtime=0))
        rows,_,dirty,events=q.typed(ps.stdout,ps.returncode==0)
        opened=[];compilers=[];drivers=[];providers=[]
        for f in sorted(trace.glob('proc.*')):
            body=f.read_bytes();lines=body.decode(errors='replace').splitlines()
            ex=[l for l in lines if l.startswith('execve(') and l.endswith('= 0')]
            rust=[l for l in ex if '"'+str(rt.SDK/'bin/rustc')+'"' in l and '"--crate-name"' in l]
            for l in rust:
                m=re.search(r'"--crate-name", "([^"]+)"',l);need(m,'unparsed compiler');compilers.append(m[1])
            is_ld=any(re.search(r'^execve\("[^"]*/(?:aarch64-linux-gnu-)?(?:ld|ld.bfd|ld.lld)",',l) for l in ex)
            if is_ld:
                drivers.append(f.name)
                for l in lines:
                    if 'openat(' in l and 'libqa_owned_external.a' in l:
                        providers.append(l)
                        if re.search(r'= \d+$',l):opened.append(l)
        with tarfile.open(path/'trace.tar.gz','x:gz',compresslevel=2) as tar:tar.add(trace,arcname='trace')
        with tarfile.open(path/'trace.tar.gz') as tar:
            for f in trace.iterdir():need(tar.extractfile('trace/'+f.name).read()==f.read_bytes(),'trace copy')
        shutil.rmtree(trace)
        exe=homes[0]/rt.TARGET/'debug/qa_owned_test';answer=None;elf=None
        if ps.returncode==0:
            b=exe.read_bytes();need(rt.elf(b,(2,3)),'wrong ISA');elf=q.custody(b,'.elf')
            answer=rt.record([*q.QEMU,exe],path/'qemu',cwd,env).stdout.decode().strip();need(re.fullmatch(r'(17|29) (7|11|13|15|19)',answer),'bad routine output')
        else:need(b'qa_owned_external' in ps.stdout+ps.stderr,'not a native provider error')
        seen=set();markers={}
        crate='barrier' if placement=='library' else 'qa_owned_test'
        for directory in homes:
            for f in directory.rglob(crate+'-*.d'):
                body=f.read_bytes();st=f.stat()
                if (st.st_dev,st.st_ino) in seen:continue
                seen.add((st.st_dev,st.st_ino))
                if b'/src/lib.rs' in body or b'/src/main.rs' in body or b'src/main.rs' in body:
                    markers[f.name]=[MISSING in body,RECHECK in body,hashlib.sha256(body).hexdigest()]
        result=dict(name=name,exit=ps.returncode,answer=answer,elf=elf,dirty=dirty,rustcs=sorted(compilers),actual_GNU_linkers=drivers,
                    selected=opened,native_lookup=providers,markers=markers,trigger=sha(src),argv=args,trace=sha(path/'trace.tar.gz'))
        save(path/'result.json',result);arms.append(result)
        if clean:
            for p in homes:
                p.rename(saved/('empty-'+p.name));(saved/p.name).rename(p)
        return result
    visit('cold-lower')
    ar(29,early);visit('higher-no-Rust-edit');visit('empty-higher',True)
    version(11);visit('higher-real-Rust-edit');visit('empty-edited-higher',True)
    early.write_bytes(b'!<arch>\n'+b'\0'*60);late.unlink();version(13)
    visit('malformed-real-Rust-edit');visit('empty-malformed',True)
    early.unlink();version(15);visit('missing-real-Rust-edit');visit('empty-missing',True)
    late.write_bytes(initial);version(19);visit('restored-real-Rust-edit');visit('empty-restored',True);visit('restored-unchanged')
    save(root/'completed.json',{'source':stock_source or {'P':subject.BASE,'C':subject.TREATMENT}[role],'placement':placement,'defaults':defaults,'cases':arms,'source_shape':sha(cwd/'src/main.rs'),'build_rs':sha(cwd/'build.rs')})
    parked=rt.ROOT/('closed-'+root.name);parked.mkdir()
    cwd.rename(parked/'source');work.rename(parked/'work')

def main():
    archive,key=sys.argv[1:];archive=Path(archive);need(sha(archive)==key,'wrong complete SDK')
    import capsule
    results={}
    for role in 'PC':
        rt.SDK.parent.mkdir(parents=True,exist_ok=True);capsule.verify(archive,role,rt.SDK)
        for mode in ('default','off'):
            for placement in ('direct','library'):
                label=role+'-'+mode+'-'+placement;root=rt.LOG/label;root.mkdir();run(root,role,placement,mode=='default')
                results[label]=sha(root/'completed.json')
        rt.SDK.rename(rt.ROOT/('finished-SDK-'+role))
    save(rt.LOG/'terminal.json',{'registered_no_edit_is_classification_only':True,'complete':results})
if __name__=='__main__':main()
