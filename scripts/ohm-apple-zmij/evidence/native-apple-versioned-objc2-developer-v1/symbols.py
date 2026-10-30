"""Independently recover both real registry marker/freshness results and genuine tracked-path collisions."""
from argparse import ArgumentParser
from io import BytesIO
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
import gzip
import json
import re
import shutil
import struct
import subprocess
import sys
import tomllib

sys.path.insert(0,str(Path(__file__).resolve().parent))
from native import P,pretty,sha,write
from protocol import CASES,HARD,V1,V2,LocalImages,Receiver,sources,standalone
from matrix import verify_binding

REGISTRY={"zmij":("zmij","1.0.10","30e0d8dffbae3d840f64bda38e28391faef673a7b5a6017840f2a106c8145868","98cf9b5dfdd97b5fa57d9efa2041119fb8c844a6a31764f7cd3e8ac270f969d2",[]),
    "zlib_rs":("zlib-rs","0.5.5","40990edd51aae2c2b6907af74ffb635029d5788228222c4bb811e9351c0caad3","58c4cfb06089f6e9e867afb7a6c05339df891dfe0afa107efb4c336f9266f049",["rust-allocator","std"])}
class Decoder:
    def __init__(self,b):
        self.s=BytesIO(b);self.body=b
    def take(self,n):
        assert 0<=n<=len(self.body)-self.s.tell()
        data=self.s.read(n);assert len(data)==n
        return data
    def integer(self,n):return int.from_bytes(self.take(n),"little")
    def field(self):return self.take(self.integer(4)).decode()
    def digest(self,tool):
        raw=self.body[:self.s.tell()];expected=bytes.fromhex(subprocess.check_output([tool],input=raw).decode().split()[0])
        assert self.take(32)==expected

def encoded(b,tool):
    doc=Decoder(b);doc.integer(4);assert doc.integer(1)==255;version=doc.integer(1);assert version in (2,4)
    files=[]
    for _ in range(doc.integer(4)):
        location=doc.integer(1);assert location in (0,1)
        name=doc.field();checksummed=doc.integer(1);assert checksummed in (0,1)
        if checksummed:doc.integer(8);doc.field()
        files.append((name,location,checksummed))
    for _ in range(doc.integer(4)):
        doc.field();present=doc.integer(1);assert present in (0,1)
        if present:doc.field()
    target=None
    if doc.s.tell()<len(b):
        tag=doc.take(4)
        if tag==b"LNK1":
            idx=doc.integer(4);assert idx<len(files);target=files[idx]
            assert target in ((V1,1,0),(V2,1,0));doc.digest(tool)
            tag=doc.take(4) if doc.s.tell()<len(b) else None
        if tag is not None:
            assert tag==b"OBS1" and doc.integer(4)<len(files) and doc.integer(1)==0;doc.digest(tool)
    assert doc.s.tell()==len(b)
    return {"has_LNK1":target is not None,"linked_marker":target[0] if target else None,"marker_v2":any(k[0]==V2 for k in files),
        "ordinary_or_synthetic_markers":[k[0] for k in files if "/dev/null/ohm-" in k[0]],"version":version}

def signs(b,path):
    lines=b.decode().splitlines()
    main=[l.split(": ",1) for l in lines if ": " in l]
    ordinary=[values for name,values in main if name==path]
    if not ordinary:ordinary=[vs for nm,vs in main if nm.endswith("/"+PurePosixPath(path).name)]
    only=lambda l:[w for w in l.split() if w.startswith("/dev/null/ohm-")]
    first=only(main[0][1])
    if not ordinary:
        assert len(main)==1 and not any(l.endswith(":") for l in lines);return {"kind":"cargo-exported-depfile","first":first}
    v,=ordinary
    return {"kind":"depfile","first":first,"ordinary":only(v),"fake":[l[:-1] for l in lines if l.startswith("/dev/null/ohm-") and l.endswith(":")]}

def registry(v,subjects):
    top="versioned/registry";study=v.js(top+"/sources.json");lock=tomllib.loads(study["lock"])
    p=study["program"];assert "zmij::Buffer::new().format" in p and "zlib_rs::crc32::crc32" in p and 'b"123456789"' in p
    for _,(pkg,version,package,source,features) in REGISTRY.items():
        entry,=[q for q in lock["package"] if q["name"]==pkg];assert entry["version"]==version and entry["checksum"]==package
    store=LocalImages(v);all_rows={}
    for name in CASES:
        prior={};rows={}
        for phase in ("cold","first-repeat","second-repeat","empty"):
            path=top+"/"+name+"/"+phase;q=v.js(path+"/verified.json");verify_binding(q["cargo"],name,subjects)
            assert q["rust"]==P and q["observation"]=="1.234 cbf43926\n" and q["native"]["scope"]=="kernel-exec"
            proj,typed=standalone(v,path,q,store,prior,"qa_registry_reader",subjects["stock_ld"])
            proof={}
            for crate,(pkg,ver,archive,source,features) in REGISTRY.items():
                rec=q["crates"][crate];record,=[u for u in typed if u["reason"]=="compiler-artifact" and u["target"]["kind"]==["lib"] and u["target"]["name"]==crate]
                assert rec["package"]==record and record["package_id"].endswith("#"+pkg+"@"+ver) and record["features"]==features and rec["source_sha"]==source
                assert record["target"]["src_path"]==rec["source"] and rec["source"].endswith("/"+pkg+"-"+ver+"/src/lib.rs")
                dep=v.gz(path+"/"+crate+".dep.gz");assert sha(dep)==rec["dep_sha"] and "/dev/null/ohm-recheck-dependent-links-v2:" in dep.decode().splitlines()
                a=[l for l in dep.decode().splitlines() if l.startswith("/dev/null/ohm-") and l.endswith(":")];assert a==[V2+":"]
                number=proj["actual_full"].count(crate);assert number==int(not record["fresh"])==rec["physical_full"]==int(phase in ("cold","empty") or name!="aware")
                assert rec["marker"]==V2 and re.fullmatch("[a-f0-9]{64}",rec["archive"])
                proof[crate]={"physical":number,"fresh":record["fresh"],"emitted_dep":sha(dep),"archive":rec["archive"],"registry_source":source}
            proj["producer"]=proof;rows[phase]=proj
        ref=rows["empty"]
        assert all((t["norm"],t["module_sha"],t["output"])==(ref["norm"],ref["module_sha"],ref["output"]) for t in rows.values())
        assert len({t["cargo_cdhash"] for t in rows.values()})==1
        published=v.js(top+"/"+name+"/terminal.json");assert published["counts"]=={phase:{k:row["producer"][k]["physical"] for k in REGISTRY} for phase,row in rows.items()}
        all_rows[name]=rows
    return all_rows

def named(v,subjects,tool):
    assert subprocess.check_output([tool],input=b"").decode().split()[0]=="af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262"
    top="versioned/named";all_rows={};store=LocalImages(v)
    path_cases={"none":[],"v1":[V1],"v2":[V2],"both":[V1,V2]}
    for name in CASES:
        cases={}
        for test,names in path_cases.items():
            case=top+"/"+name+"/"+test;prior={};rows={}
            src=v.js(case+"/source.json");assert any("proc_macro::tracked::path" in file for k,file in src.items() if k.endswith(".rs"))
            for endpoint in ("cold","repeat","empty"):
                phase=case+"/"+endpoint;obs=v.js(phase+"/verified.json");verify_binding(obs["selected"],name,subjects)
                assert obs["ordinary"]==names and obs["stdout"]=="17\n" and obs["exit"]==0
                proj,typed=standalone(v,phase,obs,store,prior,"qa_collision_reader",subjects["stock_ld"])
                u,=[r for r in typed if r["reason"]=="compiler-artifact" and r["target"]["name"]=="qa_collision"]
                expect=name=="aware" and not names
                full=proj["actual_full"].count("qa_collision")
                assert u["fresh"]==obs["fresh"] and full==int(not u["fresh"])==int(endpoint!="repeat" or not expect)
                files=obs["files"];kinds=set();captured={}
                for key,f in files.items():
                    assert key==f["name"] and f["ino"]>0 and f["dev"]>0
                    b=v.raw(phase+"/actual-files/"+f["sha256"]);assert sha(b)==f["sha256"] and len(b)==f["len"]
                    kind=f["kind"];kinds.add(kind)
                    if kind=="encoded":
                        verified=encoded(b,tool);assert all(f[k]==val for k,val in verified.items())
                        assert verified["has_LNK1"]==expect and verified["marker_v2"] and verified["linked_marker"]==(V2 if expect else None)
                    else:
                        verified=signs(b,key);assert all(f[k]==val for k,val in verified.items())
                        if kind=="depfile":
                            assert sorted(verified["ordinary"])==sorted(names) and sorted(verified["first"])==sorted(names+[V2])==sorted(verified["fake"])
                    captured[sha(key.encode())]={"basename":PurePosixPath(key).name,"sha":sha(b),"kind":kind,"decoded":verified}
                assert kinds >= {"depfile","encoded"};proj["files"]=captured;proj["fresh"]=u["fresh"];rows[endpoint]=proj
            assert all((a["norm"],a["module_sha"],a["output"])==(rows["empty"]["norm"],rows["empty"]["module_sha"],rows["empty"]["output"]) for a in rows.values())
            assert v.js(case+"/terminal.json")=={k:sha(v.raw(case+"/"+k+"/verified.json")) for k in rows}
            cases[test]=rows
        all_rows[name]=cases
    return all_rows

if __name__=="__main__":
    ap=ArgumentParser(description=__doc__);ap.add_argument("zip",type=Path);ap.add_argument("dest",type=Path);ap.add_argument("--b3sum",default=shutil.which("b3sum"));args=ap.parse_args()
    assert args.b3sum
    with ZipFile(args.zip) as z:
        v=Receiver(z);subject=sources(v);reg=registry(v,subject);sym=named(v,subject,args.b3sum)
        term=v.js("versioned/terminal.json")
        assert term["registry_marker_readback"]==sha(v.raw("versioned/registry/terminal.json")) and term["passed"]
    args.dest.mkdir(parents=True,exist_ok=True)
    write(args.dest/"registry.json",pretty(reg));write(args.dest/"named.json",pretty(sym))
    print("Independent verifications",sum(len(row) for row in reg.values()),sum(len(row) for name in sym.values() for row in name.values()))
