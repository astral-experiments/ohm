"""Create real colliding dep-info names using a genuine proc macro and check physical Cargo behavior."""
from pathlib import Path
import errno
import gzip
import json
import os
import shutil
import subprocess
import sys
import tarfile
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from native_kits import Selection
from outputs import execs,one_cargo,read_files
from safety import OLD,NEW,GNU,rt,edges
from version_kit import CHILD
from study import save,sha

MACRO='''#![feature(proc_macro_tracked_path)]
extern crate proc_macro;
use proc_macro::TokenStream;
#[proc_macro]
pub fn observed(arg: TokenStream) -> TokenStream {
    match arg.to_string().as_str() {
        "none" => {},
        "v1" => proc_macro::tracked::path("/dev/null/ohm-recheck-dependent-links"),
        "v2" => proc_macro::tracked::path("/dev/null/ohm-recheck-dependent-links-v2"),
        "both" => { proc_macro::tracked::path("/dev/null/ohm-recheck-dependent-links"); proc_macro::tracked::path("/dev/null/ohm-recheck-dependent-links-v2"); },
        _ => panic!(),
    }
    "17usize".parse().unwrap()
}
'''
def case(selector,mode):
    cwd=rt.ROOT/'real-collision';cwd.mkdir();work=rt.ROOT/'real-collision-work';work.mkdir()
    root=rt.LOG/('named-'+mode);root.mkdir()
    write=edges.write
    write(cwd/'Cargo.toml','[package]\nname="qa_collision_reader"\nversion="0.0.1"\nedition="2021"\n[dependencies]\nqa_collision={path="qa_collision"}\n')
    write(cwd/'qa_collision/Cargo.toml','[package]\nname="qa_collision"\nversion="0.0.1"\nedition="2021"\n[dependencies]\nwatch_marker={path="../watch_marker"}\n')
    write(cwd/'watch_marker/Cargo.toml','[package]\nname="watch_marker"\nversion="0.0.1"\nedition="2021"\n[lib]\nproc-macro=true\n')
    write(cwd/'watch_marker/src/lib.rs',MACRO)
    write(cwd/'src/main.rs','fn main(){println!("{}",qa_collision::value());}\n')
    write(cwd/'qa_collision/src/lib.rs',GNU+'\npub fn value()->usize {barrier(watch_marker::observed!('+mode+'))}\n')
    for name in (OLD,NEW):
        try:os.stat(name)
        except OSError as error:assert error.errno==errno.ENOTDIR
        else:raise AssertionError(name)
    env=rt.environment()
    env.update(CARGO_HOME=str(work/'registry'),CARGO_TARGET_DIR=str(work/'target'),CARGO_BUILD_BUILD_DIR=str(work/'shared'),CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=edges.q.CROSS)
    names={'none':[],'v1':[OLD],'v2':[NEW],'both':[OLD,NEW]}[mode]
    selector.choose('aware');rows={}
    for phase in ('cold','repeat','empty'):
        if phase=='empty':
            (work/'target').rename(work/'retained-target');(work/'shared').rename(work/'retained-shared')
        out=root/phase;out.mkdir();tr=out/'traces';tr.mkdir()
        cmd=['cargo','+ohm','build','--offline','--target',rt.TARGET,'-j4','--message-format=json']
        args=['strace','-ff','-q','-s','262144','-e','trace=execve,execveat','-o',str(tr/'proc'),*cmd]
        run=rt.record(args,out/'ordinary',cwd,env)
        typed=[json.loads(l) for l in run.stdout.splitlines()];assert typed[-1]=={'reason':'build-finished','success':True}
        artifact,=[r for r in typed if r.get('reason')=='compiler-artifact' and r['target']['name']=='qa_collision_reader']
        image=Path(artifact['executable']);data=image.read_bytes();assert rt.elf(data,(2,3))
        body=edges.q.custody(data,'.elf');answer=rt.record([*edges.q.QEMU,image],out/'qemu',cwd,env).stdout
        assert answer==b'17\n'
        with tarfile.open(out/'trace.tar.gz','x:gz') as t:t.add(tr,arcname='trace')
        with tarfile.open(out/'trace.tar.gz') as t:
            for p in tr.iterdir():assert t.extractfile('trace/'+p.name).read()==p.read_bytes()
        events=execs(out/'trace.tar.gz',rt.SDK);one_cargo(events,cmd)
        root_jobs=[a for a in events if a.get('crate')=='qa_collision']
        if phase!='repeat' or mode=='none':assert sum(a['kind']=='ld' for a in events)>=1
        files=read_files(out,[work/'target',work/'shared'],'qa_collision')
        for f in [f for f in files.values() if f['kind']=='depfile']:
            assert sorted(f['ordinary'])==sorted(names),(mode,f)
            assert sorted(f['first'])==sorted(names+[NEW]) and sorted(f['fake'])==sorted(names+[NEW]),(mode,f)
        if phase!='repeat' or mode!='none':
            assert len([a for a in root_jobs if a['kind']=='full_rustc'])>=1,(mode,phase,root_jobs)
        else:
            assert not root_jobs,(phase,root_jobs)
        disk=[f for f in files.values() if f['kind']=='encoded']
        assert disk and all(f['marker_v2'] and f['has_LNK1']==(not names) for f in disk),(mode,disk)
        rows[phase]={'body':body,'answer':answer.decode(),'physical_root_rustcs':root_jobs,'files':files,'kernel':sha(out/'trace.tar.gz'),'typed':artifact,'cargo':sha(rt.SDK/'bin/cargo')}
    assert len({r['body'] for r in rows.values()})==1
    save(root/'complete.json',{'compiler':CHILD,'mode':mode,'ordinary_names':names,'cases':rows})
    closed=rt.ROOT/('parked-named-'+mode);closed.mkdir();cwd.rename(closed/'src');work.rename(closed/'work')
if __name__=='__main__':
    s=Selection(Path(sys.argv[1]),'C')
    for arg in ('none','v1','v2','both'):case(s,arg)
    s.close()
    save(rt.LOG/'named-terminal.json',{mode:sha(rt.LOG/('named-'+mode)/'complete.json') for mode in ('none','v1','v2','both')})
