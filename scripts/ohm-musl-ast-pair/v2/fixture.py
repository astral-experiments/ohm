"""The watched source and two unobserved native search directories are disjoint."""
from pathlib import Path
import os
import stat
import subprocess
from evidence import APP, PRODUCER, LIB, fid, sha

COMMENT='''unsafe {
        core::arch::asm!("/* {value} */", value = in(reg) witness, options(nomem, nostack));
        core::arch::asm!("/*{0}*/", inout(reg) witness);
    }'''
CONTROL="unsafe { core::arch::asm!(\"nop\"); }"
WS='[workspace]\nmembers = ["producer","consumer"]\nresolver = "2"\n'
BUILD='''fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    let base = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap().parent().unwrap().join("native");
    for dir in ["early", "late"] {
        println!("cargo:rustc-link-search=native={}", base.join(dir).display());
    }
}
'''
class Fixture:
    def __init__(self,root,env,flavor):
        self.root=root
        self.project=root/"project"; self.project.mkdir()
        self.native=root/"native"; self.native.mkdir()
        self.paths=[self.native/n/LIB for n in ("early","late")]
        for p in self.paths:p.parent.mkdir()
        source=COMMENT if flavor in ("comment","bundled") else CONTROL if flavor=="unknown" else ""
        ext='' if flavor=="bundled" else ', modifiers = "-bundle"'
        files={"Cargo.toml":WS,
            "producer/Cargo.toml":f'[package]\nname="{PRODUCER}"\nversion="0.1.0"\nedition="2021"\n',
            "producer/build.rs":BUILD,
            "producer/src/lib.rs":f'''#[link(name="ohm_musl_v2_choice", kind="static"{ext})]
extern "C" {{ fn ohm_musl_v2_choice() -> i32; }}
#[inline(never)]
#[allow(unused_mut)]
pub fn chosen() -> i32 {{
    let mut witness = unsafe {{ ohm_musl_v2_choice() }} as usize;
    {source}
    witness as i32
}}
''',
            "consumer/Cargo.toml":f'[package]\nname="{APP}"\nversion="0.1.0"\nedition="2021"\n[dependencies]\n{PRODUCER}={{path="../producer"}}\n',
            "consumer/src/main.rs":f'fn main() {{ std::process::exit({PRODUCER}::chosen()); }}\n'}
        self.files=[]
        for name,body in files.items():
            p=self.project/name;p.parent.mkdir(exist_ok=True,parents=True);p.write_text(body);self.files.append(p)
        toolwork=root/"inputs";toolwork.mkdir()
        self.archives={}
        for n in (17,29,47):
            subprocess.run(["musl-gcc","-x","c","-O2","-c","-","-o","choice.o"],cwd=toolwork,env=env,
                           input=f"int ohm_musl_v2_choice(void){{return {n};}}".encode(),check=True)
            ar=toolwork/f"{n}.a"
            subprocess.run(["ar","crsD",str(ar),"choice.o"],cwd=toolwork,env=env,check=True)
            self.archives[n]=ar.read_bytes()
        assert len(set(self.archives.values()))==3 and len({len(x) for x in self.archives.values()})==1
        self.archives["bad"]=b"!"*len(self.archives[17])
        self.paths[1].write_bytes(self.archives[17])
        self.original=self.sources()
    def sources(self):
        return {str(p.relative_to(self.project)):[fid(p),sha(p)] for p in self.files}
    def state(self):
        return [None if not p.exists() else [str(p),fid(p),sha(p)] for p in self.paths]
    def mutate(self,n):
        p=self.paths[0];data=self.archives.get(n)
        if data is None:
            assert n is None;p.unlink(missing_ok=True);return
        if not p.exists():p.write_bytes(data);return
        if p.read_bytes()==data:return
        a=p.stat()
        assert stat.S_ISREG(a.st_mode) and a.st_nlink==1 and a.st_size==len(data)
        prior=fid(p)
        with p.open("r+b") as f:f.write(data)
        os.utime(p,ns=(a.st_atime_ns,a.st_mtime_ns))
        assert fid(p)==prior and p.read_bytes()==data
