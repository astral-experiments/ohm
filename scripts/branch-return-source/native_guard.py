"""Observe strict Cargo's real native resolver after an undeclared archive replacement."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from registration import ELF, WILD, WILD_SHA, need, sha, write

MARKER=b"/dev/null/ohm-recheck-dependent-links"
ASMS='unsafe {core::arch::asm!("/* {0} */",inout(reg) n,options(pure,nomem,nostack));core::arch::asm!("nop");}'

def evidence(logs, out, expected, sdk):
    from native_trace import owner_reads
    raw={}
    with gzip.GzipFile(out,"xb",mtime=0) as archive:
        for path in sorted(logs.glob("pid.*")):
            pid=int(path.suffix[1:]);data=path.read_bytes();archive.write(("== "+str(pid)+" ==\n").encode()+data)
            raw[pid]=data.decode("utf-8").splitlines()
    def live_image(path):
        exe=Path(path)
        if exe.is_absolute() and exe.is_file():
            if exe.samefile(sdk/WILD):return "wild"
            if exe.samefile(sdk/"bin/cargo"):return "cargo"
        return "other"
    observed=owner_reads(raw,str(expected),live_image)
    return dict(**observed,resolved=str(expected),sha256=sha(expected))


def write_fixture(work):
    (work/"leaf/src").mkdir(parents=True);(work/"app/src").mkdir(parents=True)
    (work/"Cargo.toml").write_text('[workspace]\nmembers=["leaf","app"]\nresolver="3"\n')
    (work/"leaf/Cargo.toml").write_text('[package]\nname="qa_branch_leaf"\nversion="0.0.0"\nedition="2024"\n')
    (work/"app/Cargo.toml").write_text('[package]\nname="qa_branch_app"\nversion="0.0.0"\nedition="2024"\n[dependencies]\nqa_branch_leaf={path="../leaf"}\n')
    (work/"Cargo.lock").write_text('version = 4\n\n[[package]]\nname = "qa_branch_app"\nversion = "0.0.0"\ndependencies = [\n "qa_branch_leaf",\n]\n\n[[package]]\nname = "qa_branch_leaf"\nversion = "0.0.0"\n')
    (work/"leaf/build.rs").write_text('fn main(){println!("cargo::rerun-if-changed=build.rs"); for p in ["early","late"]{println!("cargo::rustc-link-search=native={}/../{}",env!("CARGO_MANIFEST_DIR"),p);} }\n')
    (work/"leaf/src/lib.rs").write_text('#[link(name="branch_guard",kind="static",modifiers="-bundle")] unsafe extern "C"{fn branch_value()->usize;}\n#[inline(never)] pub fn answer()->usize {let mut n=unsafe{branch_value()};'+ASMS+' n}\n')
    (work/"app/src/main.rs").write_text('fn main(){println!("{}",qa_branch_leaf::answer());}\n')
    subprocess.run(["git","-c","commit.gpgsign=false","-C",work,"init","-q","--template=","-b","native-qa"],check=True)
    (work/".gitignore").write_text("/target*/\n/shared*/\n/early/\n/late/\n/scratch/\n")
    subprocess.run(["git","-C",work,"add","."],check=True)
    subprocess.run(["git","-C",work,"-c","user.name=QA","-c","user.email=qa@invalid.example","-c","commit.gpgsign=false","commit","-qm","Checked native provider"],check=True)


def guard(root,sdk,env,receipt):
    work=root/"shadow";work.mkdir();write_fixture(work)
    late=work/"late/libbranch_guard.a";early=work/"early/libbranch_guard.a"
    for p in (late,early):p.parent.mkdir()
    scratch=work/"scratch";scratch.mkdir()
    copies={}
    for value in [17,29,47]:
        (scratch/"provider.c").write_text(f'unsigned long branch_value(void){{return {value};}}\n')
        subprocess.run(["cc","-c","provider.c","-o","provider.o"],cwd=scratch,check=True)
        ar=scratch/f"native-{value}.a";subprocess.run(["ar","crsD",ar,"provider.o"],cwd=scratch,check=True)
        copies[value]=ar.read_bytes()
    need(len({len(b) for b in copies.values()})==1 and len(set(copies.values()))==3,"noncomparable native payload")
    late.write_bytes(copies[17]);target=work/"target";shared=work/"shared";snap=None
    for label,value in [("cold",17),("repeat",17),("higher",29),("same-stat",47),("malformed",None),("repeat-malformed",None),("repair",29),("removed",17)]:
        if label=="higher":
            early.write_bytes(copies[29]);st=early.stat();snap=(st.st_dev,st.st_ino,st.st_size,st.st_atime_ns,st.st_mtime_ns)
        if label in ("same-stat","malformed","repair"):
            early.write_bytes(copies[value] if value else b"!"*snap[2]);os.utime(early,ns=snap[3:])
            st=early.stat();need((st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)==(snap[0],snap[1],snap[2],snap[4]),"native identity changed")
        if label=="removed":early.unlink()
        expected=early if early.exists() else late
        rows={}
        for kind in ("warm","empty"):
            dst=receipt/(label+"-"+kind);dst.mkdir();logs=dst/"trace";logs.mkdir()
            if kind=="empty":
                for p in (target,shared):p.rename(p.with_suffix(".held"))
            invocation=["cargo","+ohm","build","--offline","--locked","-p","qa_branch_app","-j2","--message-format=json"]
            proc=subprocess.run(["strace","-ff","-qq","-yy","-s","16384","-e","trace=execve,execveat,openat,clone,clone3,fork,vfork",
                "-o",str(logs/"pid"),*invocation],cwd=work,env=env|{"CARGO_TARGET_DIR":str(target),"CARGO_BUILD_BUILD_DIR":str(shared)},capture_output=True)
            for stream,data in [("stdout",proc.stdout),("stderr",proc.stderr)]:(dst/(stream+".gz")).write_bytes(gzip.compress(data,mtime=0))
            need(proc.returncode==(101 if value is None else 0),"unexpected real provider build: "+str(dst)+" "+proc.stderr.decode()[-1000:])
            msgs=[json.loads(r) for r in proc.stdout.splitlines()]
            need(msgs[-1]=={"reason":"build-finished","success":value is not None},"incorrect provider Cargo terminal")
            observed=evidence(logs,dst/"trace.gz",expected,sdk);shutil.rmtree(logs)
            ds=[p for base in (target,shared) for p in base.rglob("qa_branch_leaf-*.d") if MARKER in p.read_bytes()]
            need(ds,"ordinary leaf did not issue the checked native-link marker")
            for i,p in enumerate(ds):(dst/f"leaf-{i}.d").write_bytes(p.read_bytes())
            if value is None:
                need(any(m.get("reason")=="compiler-message" and "linking with" in m["message"]["message"] for m in msgs),"expected native linker rejection")
                binary=None
            else:
                exe,=[Path(m["executable"]) for m in msgs if m.get("executable")];binary=sha(exe)
                need(subprocess.check_output([exe],env=env)==f"{value}\n".encode(),"stale native program")
                elfdir=receipt/"elf";elfdir.mkdir(exist_ok=True);saved=elfdir/(binary+".gz")
                if not saved.exists():saved.write_bytes(gzip.compress(exe.read_bytes(),compresslevel=3,mtime=0))
            rows[kind]=dict(elf=binary,exit=proc.returncode,value=value,native=observed,marker_sha256=sorted(sha(p) for p in ds))
            write(dst/"terminal.json",rows[kind])
            if kind=="empty":
                for p in (target,shared):
                    need(not p.is_symlink() and p.parent==work,"unowned control target")
                    shutil.rmtree(p);p.with_suffix(".held").rename(p)
        need(rows["warm"]["elf"]==rows["empty"]["elf"],"independently empty native ELF differs: "+label)
    write(receipt/"complete.json",{"visits":16,"physical_cargo":ELF,"physical_wild":WILD_SHA,"same_stat":snap,"branches":list(copies)})
