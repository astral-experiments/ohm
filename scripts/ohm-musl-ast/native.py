"""Check the ordinary musl linker and assembler against independent empty target trees."""
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess

import ruff_loop as st

SOURCE = r'''
use std::arch::global_asm;
global_asm!(".pushsection .rodata", ".global qa_payload", "qa_payload:",
    concat!(".incbin \"", env!("CARGO_MANIFEST_DIR"), "/native/value.bin\""), ".popsection");
#[link(name="qapick", kind="static", modifiers="-bundle")]
unsafe extern "C" { fn pick() -> i32; static qa_payload: u8; }
fn main() { println!("{} {}", unsafe { pick() }, unsafe { qa_payload }); }
'''


def screen(base_env):
    root=st.W/"native";root.mkdir()
    out=st.LOG/"native";out.mkdir()
    (root/"src").mkdir()
    native=root/"native";native.mkdir()
    early=native/"early";late=native/"late"
    for d in (early,late):d.mkdir()
    (root/"Cargo.toml").write_text('[package]\nname="qa-musc-provider"\nversion="0.1.0"\nedition="2024"\n[workspace]\n')
    (root/"src/main.rs").write_text(SOURCE)
    (root/"build.rs").write_text('fn main() { let r = std::env::var("CARGO_MANIFEST_DIR").unwrap(); for d in ["early","late"] { println!("cargo::rustc-link-search=native={r}/native/{d}"); println!("cargo::rerun-if-changed=native/{d}"); } }\n')
    src=native/"pick.c";obj=native/"pick.o"
    def archive(i):
        src.write_text(f"int pick(void) {{ return {i}; }}\n")
        st.call(["/usr/bin/musl-gcc","-c","-O2",src,"-o",obj],base_env,root)
        output=native/f"provider-{i}.a"
        st.call(["ar","crsD",output,obj],base_env,root)
        return output.read_bytes()
    p17,p29,p47=map(archive,(17,29,47))
    assert len(p17)==len(p29)==len(p47) and len(set((p17,p29,p47)))==3
    low=late/"libqapick.a";high=early/"libqapick.a"
    low.write_bytes(p17)
    value=native/"value.bin";value.write_bytes(b"\x07")
    def rewrite(file,data):
        old=file.stat()
        assert len(data)==old.st_size
        with file.open("r+b") as f:f.write(data)
        os.utime(file,ns=(old.st_atime_ns,old.st_mtime_ns))
        new=file.stat()
        assert (new.st_dev,new.st_ino,new.st_size,new.st_mtime_ns)==(old.st_dev,old.st_ino,old.st_size,old.st_mtime_ns)
    env=base_env | {"CARGO_TARGET_DIR":str(root/"target"),"CARGO_BUILD_BUILD_DIR":str(root/"shared")}
    st.call(["cargo","+ohm","generate-lockfile","--offline"],env,root)
    cmd=["cargo","+ohm","build","--locked","--offline","--target",st.T,"--message-format=json"]
    result={}
    def run(label):
        loc=out/label;loc.mkdir(parents=True)
        trace=loc/"observe"
        p=subprocess.run(["strace","-ff","-q","-s","131072","-e","trace=execve,execveat","-o",str(trace),*cmd],
                         cwd=root,env=env,capture_output=True)
        st.census.blob(loc/"stdout.gz",p.stdout);st.census.blob(loc/"stderr.gz",p.stderr)
        # Use the same proven native reader for Cargo, compiler and the actual driver's linker child.
        records=loc/"processes";records.mkdir()
        for f in loc.glob("observe.*"):f.rename(records/("proc."+f.suffix[1:]))
        events=st.census.qualify.native(records,root);st.s.save(loc/"kernel.json",events)
        for f in records.iterdir():
            raw=f.read_bytes()
            if raw: st.census.blob(loc/"execs"/(f.name+".gz"),raw)
            f.unlink()
        records.rmdir()
        typed=[json.loads(x) for x in p.stdout.splitlines()]
        assert p.returncode in (0,101) and typed[-1]=={"reason":"build-finished","success":p.returncode==0}
        case={"status":p.returncode,"rendered":[m["message"]["rendered"] for m in typed if m["reason"]=="compiler-message" and m["message"]["level"]=="error"],
              "links":[[r["path"],r["argv"]] for r in events["link_tools"]]}
        if not p.returncode:
            executable,=[Path(m["executable"]) for m in typed if m["reason"]=="compiler-artifact" and m.get("executable") and m["target"]["kind"]==["bin"]]
            case.update(stdout=st.call([executable],env,root).decode().strip(),elf=st.elf(executable))
        st.s.save(loc/"result.json",case)
        return case
    def move(source,dest):
        dest.mkdir(parents=True,exist_ok=True)
        for name in ("target","shared"):
            p=source/name
            assert p.is_dir() and not p.is_symlink() and not (dest/name).exists()
            p.rename(dest/name)
    def check(label,want):
        warm=run(label+"/warm");park=root/"retained"/label;move(root,park/"warm")
        clean=run(label+"/empty");move(root,park/"empty");move(park/"warm",root)
        def verdict(c):
            if want is not None:return c["status"]==0 and c["stdout"]==want
            msg="\n".join(c["rendered"]).lower()
            if label=="bad-provider":return c["status"]==101 and any(s in msg for s in ("file format","unknown file","unknown directive","unknown input","unknown argument","malformed","archive","linking with","file type","unexpected eof"))
            return c["status"]==101 and "value.bin" in msg
        result[label]={"expected":want,"warm":warm,"empty":clean,"valid":verdict(warm) and verdict(clean),
                       "native":[[str(p),st.s.sha(p),p.stat().st_ino,p.stat().st_mtime_ns] for p in (low,high,value) if p.is_file()]}
    check("low","17 7");high.write_bytes(p29);check("shadow","29 7")
    rewrite(high,p47);check("same-inode","47 7")
    rewrite(high,b"!"*len(p47));check("bad-provider",None)
    high.unlink();check("fallback","17 7")
    rewrite(value,b"\x09");check("same-inode-incbin","17 9")
    value.unlink();check("removed-incbin",None)
    value.write_bytes(b"\x07");check("repair","17 7")
    st.s.save(out/"terminal.json",result)
    return all(x["valid"] for x in result.values())
