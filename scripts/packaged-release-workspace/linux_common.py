"""Portable identities and physical ELF readback for the 50 original Linux link destinations."""
from __future__ import annotations
import ast
import collections
import gzip
import hashlib
import json
import os
import re
import struct
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from packages import need

HERE=Path(__file__).resolve().parent
FIX=HERE/"linux-subject"
ENROLL=json.loads((FIX/"fifty.json").read_bytes())
ORACLE=json.loads((FIX/"source-oracles.json").read_bytes())
SUBJECTS=ENROLL["exact_50"]
RUFF="93526150df078af7dd8fc4226cdcc469539d2001"
TREE="62d3f106c5e41f6022847f26ff8c7dc00139f7b1"
HISTORY="83a3afc3156d73ae4296f3fa74ede28e4c72bfcd"
LOCK="c9e345325bec5ff08dbbe3916edd39ad0c3d1c7797a8c241ae32f62754e764bf"
CMD=["cargo","+ohm","test","--workspace","--no-run","--locked","--offline","-j8","--message-format=json"]
STEPS=(("cold","original"),("unchanged","original"),("edited","reversed"),
       ("restored","original"),("final-unchanged","original"))
E2E="crates/ty_server|e2e|test|true|crates/ty_server/tests/e2e/main.rs"
PARSER="crates/ruff_python_parser|ruff_python_parser|lib|true|crates/ruff_python_parser/src/lib.rs"
SENTINELS={k for k,q in SUBJECTS.items() if not(q["cold_unchanged_same"] and q["restore_unchanged_same"])}|{E2E}
REAL_RUST={"20":"7e71d3150938ff8ed82aca03416439d7e5b87ef3","21":"c79998a5cd143c445a4b2528f20953b176a65c5d"}
RUN_CASE="pull_diagnostics::on_did_open"
CHUNK=1<<20

def digest(b):return hashlib.sha256(b).hexdigest()

def part(p):
    need("/crates/" in p,"non-Ruff package")
    return "crates/"+p.split("/crates/",1)[1]

def unit_key(a):
    return "|".join([str(Path(part(a["manifest_path"])).parent),a["target"]["name"],",".join(a["target"]["kind"]),
                    str(a["profile"]["test"]).lower(),part(a["target"]["src_path"])])

def outputs(data):
    rows=[json.loads(v) for v in data.splitlines()]
    need(rows[-1]=={"reason":"build-finished","success":True} and
         not any(r.get("message",{}).get("level")=="error" for r in rows),"wrong Cargo verdict")
    arts=[r for r in rows if r["reason"]=="compiler-artifact"]
    returned=[a for a in arts if a["executable"]]
    out={unit_key(a):a for a in returned}
    need(len(arts)>=400 and len(out)==len(returned)==102 and sorted(out)==ENROLL["old_full_roster"] and
         sum(a["profile"]["test"] for a in returned)==84 and set(SUBJECTS)<=out.keys(),"different Cargo product inventory")
    return arts,out

EXEC=re.compile(rb'^execve\(("(?:[^"\\]|\\.)*"),\s*(\[.*\]),\s*(?:0x[\da-f]+|NULL).*?\)\s+= 0$')
LINKERS={"ld","ld.bfd","ld.gold","ld.lld","rust-lld","wild","wild-ld","mold"}
RELEVANT=LINKERS|{"cargo","rustc","collect2","rustdoc"}

def event(line):
    need(line.startswith(b"execve(") and line.endswith(b"= 0"),"not a successful kernel exec")
    m=EXEC.match(line);need(m is not None,"truncated or unrecognized execve")
    path=ast.literal_eval(m[1].decode());args=ast.literal_eval(m[2].decode())
    need(isinstance(path,str) and isinstance(args,list) and all(isinstance(v,str) for v in args),"incomplete native arguments")
    return path,args

def native(rows,tools,aliases):
    count=collections.Counter();rust=[];links=[];other=[]
    for pid,line in rows:
        literal,argv=event(line.encode())
        if Path(literal).name not in RELEVANT:continue
        alias=aliases.get(literal)
        need(alias,"unregistered real tool "+literal)
        physical=alias["physical"]
        real=next((k for k,v in tools.items() if v["physical"]==physical and
                   v["sha256"]==alias["sha256"] and v["dev_ino"]==alias["dev_ino"]),None)
        if real=="cargo":
            if argv[1:]==["--version"]:count["cargo_version"]+=1
            else:
                need(argv[1:]==CMD[2:],"different actual packaged Cargo argv")
                count["cargo"]+=1
        elif real=="rustc" and "--crate-name" in argv and not any(a.startswith("--print") for a in argv):
            n=argv[argv.index("--crate-name")+1]
            mode="link-only" if any(a=="-Zlink-only" or a=="link-only" or a.startswith("link-only=") for a in argv) else "full"
            rust.append({"pid":pid,"crate":n,"mode":mode,"argv_sha256":digest(line.encode())});count[mode]+=1
        elif Path(literal).name in LINKERS:
            if "-o" not in argv:
                need(not any(x.startswith("@") for x in argv),"unresolved native linker response")
                continue
            names=[v for k,v in zip(argv,argv[1:]) if k=="-o"];need(len(names)==1,"ambiguous native link output")
            out=names[0]
            if real=="wild":
                need(os.path.isabs(out) and not any(x.startswith("@") for x in argv),"unresolved packaged Wild output")
                links.append({"pid":pid,"output":out,"argv_sha256":digest(line.encode())});count["wild"]+=1
            else:
                need(real=="system_ld" and out=="conftest","unregistered native linker produced output: "+str((literal,out)))
                other.append([pid,physical,out]);count["configure_ld"]+=1
        elif Path(literal).name=="collect2":count["collect2"]+=1
    need(count["cargo"]==1,"missing physical release Cargo")
    return {"counts":dict(count),"compilers":rust,"wild":links,"configure":other}

def elf_bytes(data):
    n=len(data)
    need(n>=64 and data[:6]==b"\x7fELF\x02\x01" and struct.unpack_from("<H",data,18)[0]==62,
         "not an x86-64 ELF")
    kind=struct.unpack_from("<H",data,16)[0];need(kind in (2,3),"not a linked ELF")
    p0,s0=struct.unpack_from("<QQ",data,32)
    ph,pc,sh,sc,ni=struct.unpack_from("<5H",data,54)
    need(ph==56 and p0+ph*pc<=n and sh==64 and 0<ni<sc and s0+sh*sc<=n,"invalid ELF boundaries")
    note=struct.unpack_from("<IIQQQQIIQQ",data,s0+ni*sh);strtab=data[note[4]:note[4]+note[5]]
    sections={};segments=[]
    for j in range(sc):
        name,typ,flags,addr,offset,size,*_=struct.unpack_from("<IIQQQQIIQQ",data,s0+j*sh)
        if not(flags&2) or typ==8 or not size:continue
        key=strtab[name:strtab.index(0,name)].decode();need(key not in sections and offset+size<=n,"invalid allocated ELF section")
        sections[key]=[size,digest(memoryview(data)[offset:offset+size])]
    for j in range(pc):
        typ,flags,off,va,_,size,mem,align=struct.unpack_from("<IIQQQQQQ",data,p0+j*ph)
        if typ==1:
            need(off+size<=n and size<=mem,"bad PT_LOAD")
            segments.append([flags,off,va,size,mem,align,digest(memoryview(data)[off:off+size])])
    need(".text" in sections and ".rodata" in sections and segments,"unrecognized ELF")
    return {"size":n,"sha256":digest(memoryview(data)),"file_backed_allocated":sections,"load_segments":segments}
