"""Probe the two new target classifications with an authenticated -23 GNU toolchain."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from admission import HOST, admit, file_sha, need

F = HERE / "fixtures"
V2="/dev/null/ohm-recheck-dependent-links-v2:"
V1="/dev/null/ohm-recheck-dependent-links:"
BAD="/dev/null/ohm-untracked-relink-inputs:"
TARGETS={"gnu":"aarch64-unknown-linux-gnu","musl":"x86_64-unknown-linux-musl"}
PINS={"gnu_aarch64.rs":"ae60d28ad2ddb57049a42a3c16ef6829b417522c9ab7b2c93a23a9572a6e1b0a",
      "musl_x86_64.rs":"3914b6eb41ce0125b248b75585aa6ac8af5a14c3c9dd85cc144de80453592847",
      "minicore.rs":"04618ae369845bb3e567cd4a83e1d3f09ef985fcf390b201b3223f03685d3f8b",
      "rmake.rs":"a5a29f3c6c3df143bbd8d40e44d4e7302ab74bf6716824af9af9bb298d3edc5d"}


def markers(data, safe):
    rows = data.decode().splitlines()
    need([rows.count(x) for x in (V1,V2,BAD)] == [0,int(safe),int(not safe)], "dep-info rule mismatch")


def cases(kind):
    s=(F/"rmake.rs").read_text()
    if kind=="gnu":
        s=s.split('if target() == "aarch64-unknown-linux-gnu" {',1)[1]
        all_cases=re.findall(r'"(\w+)"',s.split("for cfg in [",1)[1].split("] {",1)[0])
        safe=set(re.findall(r'"(\w+)"',s.split("let accepted = matches!(",1)[1].split(");",1)[0]))
        need(len(all_cases)==31 and len(safe)==8 and safe<=set(all_cases),"GNU fixture roster")
    else:
        safe={"spaced","compact","both"}
        all_cases=list(sorted(safe))+re.findall(r'"(\w+)"',s.split("for case in [",2)[2].split("] {",1)[0])
        need(len(all_cases)==13 and len(set(all_cases))==13,"musl fixture roster")
    return all_cases,safe


def run(log,tag,argv,cwd,env,rc=0):
    res=subprocess.run(list(map(str,argv)), cwd=cwd, env=env, capture_output=True, timeout=120)
    (log/(tag+".stdout")).write_bytes(res.stdout)
    (log/(tag+".stderr")).write_bytes(res.stderr)
    (log/(tag+".json")).write_text(json.dumps(dict(argv=list(map(str,argv)),cwd=str(cwd),actual=res.returncode,expected=rc),indent=2)+"\n")
    need(res.returncode==rc, f"{tag} exited {res.returncode}, expected {rc}; original retained at {log}")
    return res


def fixture(kind,out,compiler,env):
    target=TARGETS[kind];work=out/"direct-work";work.mkdir();log=out/"direct";log.mkdir()
    base=[compiler,"+ohm","--target",target]
    def cmd(tag,args,rc=0): return run(log,tag,base+args,work,env,rc)
    mc=work/"libminicore.rlib"
    cmd("minicore",["--crate-name","minicore","--crate-type","rlib",F/"minicore.rs","-o",mc])
    (work/"payload.bin").write_bytes(bytes(4));(work/"payload.s").write_text(".byte 7\n")
    src=F/("gnu_aarch64.rs" if kind=="gnu" else "musl_x86_64.rs")
    flags=["-Zunstable-options","--extern","minicore="+str(mc)]
    if kind=="gnu":
        # Only crate scaffolding changes. Keep every original asm/cfg/body byte.
        src=work/"gnu_nocore.rs";original=(F/"gnu_aarch64.rs").read_text()
        first,sep,body=original.partition("\n");need(first=='#![crate_type = "rlib"]' and bool(sep),"GNU input layout")
        header='''#![feature(no_core)]
#![no_core]
extern crate minicore;
mod core {
    pub use minicore::hint;
    pub mod arch {
        pub use minicore::{asm, global_asm};
        pub mod aarch64 {
            #[allow(non_camel_case_types)]
            pub type int32x4_t = minicore::simd::Simd<i32,4>;
        }
    }
}
'''
        src.write_text(first+"\n"+header+body)
    result={}
    def visit(tag, cfg, wanted, extra=(), rc=0, needle=None):
        argv=["--crate-name","probe","--cfg",cfg,"-Zohm-check-relink-inputs","--emit=link,dep-info=-",*flags,src,*extra]
        p=cmd(tag,argv,rc)
        markers(p.stdout,wanted)
        if needle is not None: need(needle in p.stderr,tag+" native error evidence")
        result[tag]=[rc,wanted]
    roster,safe=cases(kind)
    for c in roster: visit(c,c,c in safe)
    original=src
    lhs,rhs=(('asm!("svc 0", in("x8") x','asm!("svc #0", in("x8") x') if kind=="gnu" else
             ('"/* {value} */", value = in(reg) value','"/*  {value}  */", value = in(reg) value'))
    original_text=original.read_text();need(original_text.count(lhs)==1,"single alternate-spelling site")
    src=work/"alternate.rs";src.write_text(original_text.replace(lhs,rhs))
    shutil.copyfile(src,log/"alternate.rs")
    visit("other-accepted-assembler-spelling","syscall" if kind=="gnu" else "spaced",False)
    src=original
    regular="ordinary" if kind=="gnu" else "both"
    visit("unbundled",regular,True,["-lstatic:-bundle=ohm_missing_archive"])
    visit("bundled-missing",regular,False,["-lstatic=ohm_missing_archive"],1,b"ohm_missing_archive")
    if kind=="musl":
        (work/"payload.s").write_text(".ohm_invalid_directive\n")
        visit("malformed-include","include",False,rc=1,needle=b".ohm_invalid_directive")
        # Print and compile against the identically spelled custom JSON target; the
        # compiler must reject v2 even when architecture, ABI and target stem match.
        spec=cmd("target-spec",["-Zunstable-options","--print","target-spec-json"]).stdout
        custom=work/(target+".json");custom.write_bytes(spec)
        custombase=[compiler,"+ohm","-Zunstable-options","--target",custom]
        run(log,"custom-minicore",custombase+["--crate-name","minicore","--crate-type","rlib",F/"minicore.rs","-o",mc],work,env)
        p=run(log,"same-stem-custom",custombase+["--crate-name","probe","--cfg","both","-Zohm-check-relink-inputs","--emit=link,dep-info=-",*flags,src],work,env)
        markers(p.stdout,False);result["same-stem-custom"]=[0,False]
    return dict(target=target,target_std_used=False,source_sha256=file_sha(src),cases=result)

def elf_image(exe,kind):
    b=exe.read_bytes()
    need(b[:7]==b"\x7fELF\x02\x01\x01" and struct.unpack_from("<HH",b,16)==(2,183 if kind=="gnu" else 62),"wrong native executable")
    off=struct.unpack_from("<Q",b,32)[0];stride,n=struct.unpack_from("<HH",b,54)
    need(stride==56 and n>0 and off+n*stride<=len(b),"truncated ELF")
    need(all(struct.unpack_from("<I",b,off+i*stride)[0]!=3 for i in range(n)),"unexpected ELF interpreter")
    return hashlib.sha256(b).hexdigest()


def native(kind,out,proxy,sdk,env,cc,qemu):
    target=TARGETS[kind]; w=out/"native-work";w.mkdir();log=out/"native";log.mkdir()
    for k in ("minicore","probe"): (w/k/"src").mkdir(parents=True)
    (w/"Cargo.toml").write_text('[workspace]\nmembers=["minicore","probe"]\nresolver="2"\n')
    for name in ("minicore","probe"):
        (w/name/"Cargo.toml").write_text(f'[package]\nname="{name}"\nversion="0.1.0"\nedition="2021"\n'+
            ('[dependencies]\nminicore={path="../minicore"}\n' if name=="probe" else ''))
    (w/"Cargo.lock").write_text('version = 4\n\n[[package]]\nname = "minicore"\nversion = "0.1.0"\n\n[[package]]\nname = "probe"\nversion = "0.1.0"\ndependencies = ["minicore"]\n')
    shutil.copyfile(F/"minicore.rs",w/"minicore/src/lib.rs")
    p=w/"probe/src/lib.rs";payload=w/"probe/literal.s"
    entry=w/"start.s"
    entry.write_text(('.text\n.globl _start\n_start:\nmov x0, #17\nbl qual_probe\nmov x8, #93\nsvc #0\n' if kind=="gnu" else
                      '.intel_syntax noprefix\n.text\n.globl _start\n_start:\nmov edi,17\ncall qual_probe\nmov edi,eax\nmov eax,60\nsyscall\n'))
    run(log,"assemble-native-start",[cc,"--target="+target,"-c",entry,"-o","start.o"],w,env)
    prefix='#![feature(no_core)]\n#![no_core]\nextern crate minicore;\nuse minicore::asm;\n'
    pos=prefix+'''#[no_mangle]
pub extern "C" fn qual_probe(mut input: usize) -> usize {
    unsafe { asm!("/*{0}*/", inout(reg) input); }
    input
}
'''
    edited=pos.replace('    input\n','    unsafe { asm!("/* {value} */", value = in(reg) input, options(nomem, nostack)); }\n    29\n')
    need(pos!=edited,"genuine Rust edit")
    file_asm=', '.join(map(json.dumps,['.pushsection .rodata.ohm_qa,"a"',f'.include "{payload}"','.popsection']))
    asm_data=".globl ohm_qa_payload\nohm_qa_payload:\n.byte {}\n" 
    weak=prefix+'extern "C" { static ohm_qa_payload: u8; }\n#[no_mangle]\npub unsafe extern "C" fn qual_probe(_: usize) -> usize {\nasm!('+file_asm+', options(nostack));\nohm_qa_payload as usize\n}\n'
    cargo=[proxy,"+ohm","build","--locked","--offline","--lib","-p","probe","--target",target,"--message-format=json"]
    ld=sdk/"lib/rustlib"/HOST/"bin/rust-lld"
    elfs={}; ledger={}
    def build(phase,expected=None,diagnostic=None,want_e0308=False):
        rc=0 if expected is not None else 101
        cmd=run(log,phase+"-cargo",cargo,w,env,rc)
        messages=[json.loads(s) for s in cmd.stdout.splitlines()]
        need(messages[-1]=={"reason":"build-finished","success":rc==0},"terminal Cargo message")
        ro=[m for m in messages if m.get("reason")=="compiler-artifact" and m["target"]["name"]=="probe"]
        data=dict(cargo_exit=rc,source=file_sha(p),payload=file_sha(payload) if payload.is_file() else None)
        if rc:
            errors=[m["message"] for m in messages if m.get("reason")=="compiler-message" and m["message"]["level"]=="error"]
            actual=cmd.stderr+b"\n"+b"\n".join((e.get("rendered") or e["message"]).encode() for e in errors)
            need(diagnostic in actual,"wrong error evidence: "+phase)
            if want_e0308:
                need(any(e.get("code") and e["code"]["code"]=="E0308" and any(s["is_primary"] and Path(s["file_name"]).name=="lib.rs" for s in e["spans"]) for e in errors),"wrong Rust error")
            elif phase=="missing-asm":
                need(any(e["message"].lower().startswith("could not find include file") and "literal.s" in e["message"] for e in errors),"missing assembler input diagnostic")
            elif phase=="malformed-asm":
                need(any(e["message"].lower()=="unknown directive" for e in errors),"malformed assembler input diagnostic")
        else:
            need(len(ro)==1,"single returned Cargo library")
            candidates=[Path(x) for x in ro[0]["filenames"] if x.endswith(".rlib")];need(len(candidates)==1,"Cargo native library")
            lib=candidates[0];need(lib.resolve().is_relative_to(w/"cargo-target") or lib.resolve().is_relative_to(w/"cargo-build"),"unexpected Cargo output")
            exe=w/"consumer";run(log,phase+"-ld",[ld,"-flavor","gnu","-m",("aarch64elf" if kind=="gnu" else "elf_x86_64"),"-static","-s","--build-id=none","-e","_start",w/"start.o",lib,"-o",exe],w,env)
            h=elf_image(exe,kind)
            run(log,phase+"-execute",([qemu,exe] if kind=="gnu" else [exe]),w,env,expected)
            shutil.copyfile(exe,log/(phase+".elf"))
            data.update(fresh=ro[0]["fresh"],rlib_sha256=file_sha(lib),elf_sha256=h,exit=expected)
            elfs[phase]=h
        ledger[phase]=data
    def empty():
        for k in ("cargo-build","cargo-target"):
            (w/k).rename(w/(k+".held"))
    p.write_text(pos);build("cold-rust",17);build("unchanged-rust",17)
    p.write_text(edited);build("edited-rust",29);build("unchanged-edited",29)
    p.write_text(edited+'pub fn typed_error() { let _: usize = "OHM_rc23_typed_error"; }\n')
    build("invalid-rust",diagnostic=b"OHM_rc23_typed_error",want_e0308=True)
    p.write_text(edited);build("repaired-rust",29)
    empty();build("empty-edited-rust",29)
    need(elfs["cold-rust"]==elfs["unchanged-rust"] and elfs["cold-rust"]!=elfs["edited-rust"] and
         len({elfs[k] for k in ("edited-rust","unchanged-edited","repaired-rust","empty-edited-rust")})==1,"Rust outputs differ from independent empty")
    p.write_text(weak);payload.write_text(asm_data.format(17)); build("cold-asm",17);build("unchanged-asm",17)
    st=payload.stat();payload.write_text(asm_data.format(29));os.utime(payload,ns=(st.st_atime_ns,st.st_mtime_ns))
    new=payload.stat();need((st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)==(new.st_dev,new.st_ino,new.st_size,new.st_mtime_ns),"native replacement lost inode/size/mtime")
    before_sha=ledger["cold-asm"]["payload"];after_sha=file_sha(payload);need(before_sha!=after_sha,"unchanged assembler body")
    (log/"same-stamp-provider.json").write_text(json.dumps({"path":str(payload),"before":[st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns,before_sha],"after":[new.st_dev,new.st_ino,new.st_size,new.st_mtime_ns,new.st_ctime_ns,after_sha]},indent=2)+"\n")
    build("same-stamp-asm",29);build("unchanged-replaced-asm",29)
    payload.unlink();build("missing-asm",diagnostic=b"literal.s")
    payload.write_text(".ohm_invalid_rc23_directive\n");build("malformed-asm",diagnostic=b".ohm_invalid_rc23_directive")
    payload.write_text(asm_data.format(37));build("repaired-asm",37)
    for k in ("cargo-build","cargo-target"): (w/k).rename(w/(k+".held2"))
    build("empty-repaired-asm",37)
    need(elfs["cold-asm"]==elfs["unchanged-asm"]!=elfs["same-stamp-asm"]==elfs["unchanged-replaced-asm"] and
         elfs["repaired-asm"]==elfs["empty-repaired-asm"] and elfs["same-stamp-asm"]!=elfs["repaired-asm"],"native bodies differ from controls")
    return ledger


def sources():
    for f,h in PINS.items(): need(file_sha(F/f)==h,f+" exact input")
    return {kind:[len(cases(kind)[0]),len(cases(kind)[1])] for kind in TARGETS}


def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest="action",required=True);sub.add_parser("preflight")
    q=sub.add_parser("run")
    for n in ("catalog","official","sdk","rustup","rustup-home","work"):q.add_argument("--"+n,type=Path,required=True)
    q.add_argument("--target",choices=[*TARGETS,"both"],required=True)
    args=ap.parse_args();s=sources()
    if args.action=="preflight":print(json.dumps(s,sort_keys=True));return
    w=args.work.absolute(); parent=w.parent.resolve(strict=True);need(not w.exists(),"work must be fresh")
    fs=subprocess.check_output(["findmnt","-n","-o","FSTYPE","--target",parent],text=True).strip()
    sf=os.statvfs(parent);need(fs=="tmpfs" and sf.f_blocks*sf.f_frsize<=1024**3 and sf.f_bavail*sf.f_frsize>=128*1024**2,"new work needs a bounded tmpfs and 128 MiB available")
    need(shutil.disk_usage(Path.home()).free>=512*1024**2,"HOME reserve refused")
    sdk=args.sdk.resolve(strict=True);rustup=args.rustup.absolute();proxy=rustup.parent
    cc=shutil.which("clang");qemu=shutil.which("qemu-aarch64") or shutil.which("qemu-aarch64-static")
    selected=list(TARGETS) if args.target=="both" else [args.target]
    need(cc is not None and ("gnu" not in selected or qemu),"missing clang or native AArch64 execution provider")
    opts=subprocess.check_output(["findmnt","-n","-o","OPTIONS","--target",parent],text=True).strip().split(",")
    need("noexec" not in opts and "ro" not in opts,"need writable + executable private tmpfs")
    w.mkdir(mode=0o700);(w/"cargo-home").mkdir();(w/"scratch-home").mkdir()
    env=dict(PATH=str(proxy)+":/usr/bin:/bin",HOME=str(w/"scratch-home"),RUSTUP_HOME=str(args.rustup_home.resolve(strict=True)),
             CARGO_HOME=str(w/"cargo-home"),CARGO_NET_OFFLINE="true",LC_ALL="C",CARGO_TERM_COLOR="never")
    admitted=admit(args.catalog,args.official,sdk,rustup,env);(w/"admission.json").write_text(json.dumps(admitted,indent=2)+"\n")
    receipt={}
    for kind in selected:
        out=w if len(selected)==1 else w/kind
        if out!=w:out.mkdir()
        (out/"tmp").mkdir();(out/"cargo-case-home").mkdir()
        env_role=env|dict(TMPDIR=str(out/"tmp"),CARGO_HOME=str(out/"cargo-case-home"),CARGO_TARGET_DIR=str(out/"native-work/cargo-target"),CARGO_BUILD_BUILD_DIR=str(out/"native-work/cargo-build"))
        # The checked-in compiler's direct no_core fixture uses unstable minicore.
        # Cargo's only opted-in crates are the two private fixture crates.
        d=fixture(kind,out,str(proxy/"rustc"),env_role|{"RUSTC_BOOTSTRAP":"1"})
        n=native(kind,out,str(proxy/"cargo"),sdk,env_role|{"RUSTC_BOOTSTRAP":"minicore,probe"},cc,qemu)
        (out/"result.json").write_text(json.dumps(dict(source=admitted,target=TARGETS[kind],direct=d,native=n),indent=2)+"\n")
        receipt[kind]=file_sha(out/"result.json")
    if len(selected)>1:
        (w/"result.json").write_text(json.dumps({"official_source":admitted,"targets":receipt},indent=2)+"\n")
    print(file_sha(w/"result.json"),w/"result.json")
if __name__=="__main__": main()
