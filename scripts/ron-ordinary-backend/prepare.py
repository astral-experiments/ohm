"""Bind the diagnostic to one genuine signed -24 registry Ron invocation."""
from pathlib import Path
import hashlib
import json
import os
import re
import struct
import subprocess as sp
import sys
import tarfile

HERE=Path(__file__).resolve().parent

def sha(path):
    with path.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()

def dump(path,data):
    path.write_text(json.dumps(data,sort_keys=True,indent=2)+"\n")

def execute(args):
    sp.run([str(x) for x in args],check=True)

def cargo_role(captured,sdk):
    raw=(captured/"cargo-argv.nul").read_bytes()
    file,*av,empty=raw.split(b"\0")
    assert not empty
    a=list(map(os.fsdecode,av))
    assert Path(os.fsdecode(file)).samefile(sdk/"bin/rustc") and Path(a[0]).samefile(sdk/"bin/rustc")
    assert a[a.index("--crate-name")+1]=="ron" and a[a.index("--crate-type")+1] in ("lib","rlib")
    src=next(Path(v) for v in a if v.endswith("/ron-0.12.0/src/lib.rs"))
    assert src.is_file() and "/registry/src/" in str(src)
    assert "--emit=dep-info,metadata,link" in a and "-Zohm-shared-stages" in a and "-Zpublic-api-hash" in a
    cg={a[i+1] for i,v in enumerate(a) if v=="-C"}
    assert {"opt-level=1","lto=off","embed-bitcode=no","debug-assertions=on","debuginfo=line-tables-only"}<=cg
    reject=("incremental=","codegen-backend","llvm-plugins","llvm-args","profile-generate","profile-use","sanitizer=","save-temps","verify-llvm-ir")
    assert not any(any(r in x for r in reject) for x in a)
    extern=[a[i+1].split("=",1) for i,x in enumerate(a) if x=="--extern"]
    assert {n for n,_ in extern}=={"bitflags","once_cell","serde","serde_derive","typeid","unicode_ident"}
    assert all(Path(v).is_file() for _,v in extern)
    assert a[a.index("--out-dir")+1].startswith("/")
    return {"argv_sha256":hashlib.sha256(b"\0".join(av[1:])+b"\0").hexdigest(),
            "crate":"ron@0.12.0","source":str(src),"source_sha256":sha(src),
            "externs":{n:[v,sha(Path(v))] for n,v in extern},"argv":a}

def prologues(sdk):
    driver=sdk/"lib/librustc_driver-b03bf00bec23bb9a.so"
    expected={0x6df2240:"f30f1efa41574156415541545553",0x6be43ce:"f30f1efa41574989ff415641554154"}
    with driver.open("rb")as f:
        header=f.read(64);assert header[:6]==b"\x7fELF\x02\x01"
        phoff=struct.unpack_from("<Q",header,32)[0];w,n=struct.unpack_from("<HH",header,54)
        assert w==56;f.seek(phoff);ph=[struct.unpack("<IIQQQQQQ",f.read(w))for _ in range(n)]
        for addr,hextext in expected.items():
            matches=[entry for entry in ph if entry[0]==1 and entry[1]&1 and entry[3]<=addr<entry[3]+entry[5]]
            entry,=matches;f.seek(entry[2]+addr-entry[3]);assert f.read(len(hextext)//2)==bytes.fromhex(hextext),(hex(addr),entry)
    z=sp.check_output(["nm","-an","--defined-only",str(driver)],text=True)
    found={n:int(a,16) for a,n in re.findall(r"^([0-9a-f]+) t (LLVMRustOptimize|LLVMRustWriteOutputFile)$",z,re.M)}
    assert found=={"LLVMRustOptimize":0x6df2240,"LLVMRustWriteOutputFile":0x6be43ce}
    return found

def build(root,sdk,captured):
    root.mkdir()
    release=json.loads((HERE/"release-compiler.json").read_bytes())
    assert len(release["members"])==79
    for name,item in release["members"].items():
        f=sdk/name
        assert f.is_file() and sha(f)==item["sha256"] and f.stat().st_size==item["bytes"]
    parts=json.loads((HERE/"components.json").read_bytes())
    assert sha(HERE/"headers-blake3.tar.xz")==parts["headers_sha256"]
    with tarfile.open(HERE/"headers-blake3.tar.xz")as t:
        assert {m.name for m in t}==set(parts["source_sha256"])
        for m in t:
            assert m.isfile() and not Path(m.name).is_absolute() and ".." not in Path(m.name).parts
            f=root/m.name;f.parent.mkdir(exist_ok=True,parents=True);f.write_bytes(t.extractfile(m).read())
            assert sha(f)==parts["source_sha256"][m.name]
    ra=cargo_role(captured,sdk);raw=ra["argv_sha256"];addrs=prologues(sdk)
    objects=[]
    for name in ("blake3.c","blake3_dispatch.c","blake3_portable.c","blake3_sse2_x86-64_unix.S","blake3_sse41_x86-64_unix.S",
                 "blake3_avx2_x86-64_unix.S","blake3_avx512_x86-64_unix.S"):
        out=root/(name+".o");execute(["cc","-O3","-fPIC","-c",root/"blake3"/name,"-o",out]);objects.append(out)
    execute(["cc","-O3","-I"+str(root/"blake3"),HERE/"src/hash-tools.c",*objects,"-o",root/"hash-tools"])
    files=[sdk/"bin/rustc",sdk/"lib/librustc_driver-b03bf00bec23bb9a.so",sdk/"lib/libLLVM.so.23.1-rust-1.99.0-beta"]
    authentic=sp.check_output([root/"hash-tools",*files],text=True).splitlines()
    assert len(authentic)==3
    for f,line in zip(files,authentic):
        rec=parts["software"][str(f.relative_to(sdk))];assert rec["blake3"] in line and sha(f)==rec["sha256"] and f.stat().st_nlink==1
    sup=(HERE/"src/supervisor-prefix.cpp").read_text()+'\n#define REGISTERED_CMD "'+raw+'"\n'+(HERE/"src/main.inc").read_text()
    (root/"supervisor.cpp").write_text(sup)
    execute(["c++","-std=c++17","-O2","-g","-I"+str(root/"blake3"),"-I"+str(HERE/"src"),root/"supervisor.cpp",*objects,"-lcrypto","-o",root/"supervise"])
    execute(["clang++","-std=c++17","-O2","-g","-fPIC","-shared","-fno-rtti","-I"+str(root/"llvm"),HERE/"src/actor.cpp",HERE/"src/mapping.cpp",
             HERE/"src/hook.S","-L"+str(sdk/"lib"),"-Wl,-rpath,"+str(sdk/"lib"),"-l:libLLVM.so.23.1-rust-1.99.0-beta","-ldl","-lcrypto","-pthread","-o",root/"contact.so"])
    bound={"role":ra,"release_software":parts["software"],"signed_addresses":addrs,"actor_sha256":sha(root/"contact.so"),"launcher_sha256":sha(root/"supervise")}
    dump(root/"bound.json",bound)
    return bound

if __name__=="__main__":
    build(*(Path(v).resolve()for v in sys.argv[1:]))
