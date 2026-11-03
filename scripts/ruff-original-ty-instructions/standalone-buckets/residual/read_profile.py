"""Read the original perf file and resolve bounded PCs from the matching native program."""
import argparse
import bisect
import collections
import gzip
import hashlib
import json
import mmap
import os
import re
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent.parent/"source-pcs"))
from pc_raw import raw_records
from semantic_pcs import mappings

def need(x,text):
    if not x:raise ValueError(text)

def sha(path):
    with path.open("rb")as f:return hashlib.file_digest(f,"sha256").hexdigest()

def kernel(buf):
    h=struct.unpack_from("<9Q",buf);i,end=h[5],h[5]+h[6]
    _,_,_,period,bits,_=struct.unpack_from("<IIQQQQ",buf,h[3]);comm=collections.defaultdict(set);samples=[]
    while i<end:
        kind,mode,size=struct.unpack_from("<IHH",buf,i)
        if kind==3:
            pid,tid=struct.unpack_from("<II",buf,i+8)
            comm[pid,tid].add(buf[i+16:i+size].split(b"\0",1)[0].decode(errors="replace"))
        if kind==9:
            off=i+8+8*bool(bits&(1<<16));ip,pair,at=struct.unpack_from("<3Q",buf,off);off+=24
            off+=sum(8 for b in (8,64,512,128)if bits&b)
            if bits&256:need(struct.unpack_from("<Q",buf,off)[0]==period,"period");off+=8
            count,=struct.unpack_from("<Q",buf,off);off+=8;need(count<=64 and off+8*count<=i+size,"call chain")
            stack=struct.unpack_from("<"+"Q"*count,buf,off);samples.append(((pair&0xffffffff,pair>>32,at,period,ip),stack))
        i+=size
    return samples,comm

def demangle(values):
    answer={n:n for n in values}
    for rust,tool in ((True,["c++filt","-s","rust"]),(False,["c++filt","-s","gnu-v3"])):
        ids=sorted(n for n in values if bool(n.startswith("_R") or (n.startswith("_ZN")and re.search(r"17h[0-9a-f]{16}E",n)))==rust)
        if not ids:continue
        lines=subprocess.run(tool,input="\n".join(ids)+"\n",text=True,capture_output=True,check=True).stdout.splitlines()
        need(len(ids)==len(lines),"demangler did not consume original symbols")
        answer.update(zip(ids,[re.sub(r"\[[0-9a-f]{16}\]","",s)for s in lines],strict=True))
    return answer

def native_symbols(file,offsets,debug=None):
    """Bounded RSS elf decoding. Read only atom names covering an actually sampled address."""
    need(len(offsets)<100000,"unbounded address set")
    with file.open("rb")as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)as b:
        h=struct.unpack_from("<16sHHIQQQIHHHHHH",b)
        need(h[0][:7]==b"\x7fELF\x02\x01\x01" and h[2]==62,"x86 ELF")
        ph=[struct.unpack_from("<IIQQQQQQ",b,h[5]+h[9]*i)for i in range(h[10])]
        va_by_off={}
        for o in offsets:
            vas={x[3]+o-x[2]for x in ph if x[0]==1 and x[1]&1 and x[2]<=o<x[2]+x[5]}
            if len(vas)==1:va_by_off[o]=vas.pop()
        addresses=sorted(set(va_by_off.values()));found=collections.defaultdict(set)
        if debug:
            need(debug.stat().st_size<16*1024*1024,"unbounded supplementary symbol table")
            b=debug.read_bytes()
            h=struct.unpack_from("<16sHHIQQQIHHHHHH",b)
            need(h[0][:7]==b"\x7fELF\x02\x01\x01" and h[2]==62,"non-native separate symbols")
        sections=[struct.unpack_from("<IIQQQQIIQQ",b,h[6]+h[11]*i)for i in range(h[12])]
        for si in sections:
            if si[1]not in(2,11):continue
            strings=sections[si[6]];need(si[9]==24 and si[5]%24==0,"symbol table")
            for pos in range(si[4],si[4]+si[5],24):
                nm,ty,vis,ndx,lo,size=struct.unpack_from("<IBBHQQ",b,pos)
                if ty&15 not in (2,10) or ndx==0 or not size:continue
                l=bisect.bisect_left(addresses,lo);r=bisect.bisect_left(addresses,lo+size,l)
                if l==r:continue
                start=strings[4]+nm;stop=b.find(b"\0",start,strings[4]+strings[5]);need(stop>=start,"symbol name")
                name=b[start:stop].decode(errors="replace")
                if name:
                    for va in addresses[l:r]:found[va].add((name,lo,size))
    names=demangle({n for rows in found.values()for n,_,_ in rows})
    return {off:{"va":va,"symbols":sorted((names[n],lo,size,n)for n,lo,size in found[va])}for off,va in va_by_off.items()}

def groups(library,symbols):
    n=Path(library).name
    if library.startswith("@"):return library
    if n.startswith("libLLVM"):return "LLVM backend"
    if n.startswith("ld-linux"):return "dynamic loader"
    if n.startswith("libc.so"):return "libc"
    if n.endswith(".so")and "librustc_driver"not in n:return "proc-macro or other mapped shared library"
    if not n.startswith("librustc_driver"):return "other mapped executable"
    def classify(n):
        if "public_api_hasher" in n:return "public API metadata graph"
        if any(k in n for k in ("rustc_query_system::dep_graph","rustc_middle::dep_graph","rustc_incremental::","rustc_query_impl::plumbing::try_load_from_disk","rustc_query_impl::on_disk_cache")):return "incremental graph / on-disk queries"
        if n.startswith(("rustc_metadata::","<rustc_metadata::")):return "other rustc metadata"
        if n.startswith(("rustc_codegen_","<rustc_codegen_","rustc_llvm::")) or n.startswith(("LLVMRust","llvm::")):return "rustc backend/LLVM bridge"
        if n.startswith(("rustc_expand::","<rustc_expand::","rustc_parse::","<rustc_parse::","rustc_ast","rustc_resolve::","<rustc_resolve::","proc_macro::","<proc_macro::")):return "parse, expand, resolve, proc-macro bridge"
        if re.match(r"<?rustc_(?:hir_|trait_|next_trait_solver|borrowck|infer|mir_|const_eval|type_ir)",n):return "HIR, type, trait, MIR, const analysis"
        if n.startswith(("rustc_monomorphize::","<rustc_monomorphize::","rustc_symbol_mangling::")):return "monomorphization / naming"
        if n.startswith(("rustc_serialize::","<rustc_serialize::")):return "serialization, caller unassigned"
        if any(s in n for s in ("StableHasher","HashStable","hash_stable","rustc_stable_hash")):return "stable hashing, caller unassigned"
        if n.startswith(("rustc_query_","<rustc_query_")):return "other query machinery"
        if re.search(r"(?:^|::)_?mi(?:malloc|_)",n):return "allocator"
        return "other resolved driver"
    categories={classify(x) for x in symbols}
    if len(categories)==1:return categories.pop()
    return "unresolved or ambiguous driver"

def analyse(directory,archive,out):
    z=zipfile.ZipFile(archive);get=lambda n:json.loads(z.read(n));reg=get("registered.json")
    ids=get("pc-readback/raw-identity.json");raw=subprocess.check_output(["zstd","-qdc"],input=z.read("pc-readback/perf.data.zst"))
    need(len(raw)==ids["bytes"] and hashlib.sha256(raw).hexdigest()==ids["sha256"],"wrong raw kernel input")
    period,ips,records,depth,modes,skid=raw_records(raw);events,comm=kernel(raw)
    need(collections.Counter(x for x,y in events)==ips and not any(records.get(m,0)for m in(2,5,6,13)),"duplicate, displaced or lost instructions")
    owner=get("sampled/edit/actual-processes.json")
    files=json.loads((directory/"capsule-C.json").read_bytes())["files"]
    prefix="/home/runner/work/_temp/ohm-foreign-join/sdk/"
    buildids={x[1]:x[0]for line in(directory/"buildids.txt").read_text().splitlines()if len(x:=line.strip().split(maxsplit=1))==2 and re.fullmatch(r"[0-9a-f]+",x[0])}
    per={};offsets=collections.defaultdict(set);allmap={};local={}
    for k,o in owner.items():
        maps=mappings(raw,o["pid"])
        parents={};first={};allmap[k]=maps
        for r in maps:
            lib=r["name"]
            if lib.startswith(prefix):
                rel=lib.removeprefix(prefix);record=files.get(rel)
                if record:
                    f=directory/("image-"+record[0]);need(f.is_file()and f.stat().st_size==record[1],"missing attested SDK image")
                    local[lib]=[f,record[0],"exact registered factory ELF"]
            elif lib.startswith("/usr/lib/") and Path(lib).is_file() and (r.get("buildid")or buildids.get(lib)):
                if lib not in local:
                    note=subprocess.check_output(["readelf","-nW",lib],text=True,errors="replace")
                    bid,=re.findall(r"Build ID: ([0-9a-f]+)",note)
                    if bid in (r.get("buildid"),buildids.get(lib)):local[lib]=[Path(lib),sha(Path(lib)),"matching recorded GNU build ID"]
        cache={}
        def place(pc):
            if pc not in cache:
                unique={(r["name"],r["off"]+pc-r["base"]) for r in maps if r["base"]<=pc<r["base"]+r["length"]}
                cache[pc]=unique.pop()if len(unique)==1 else ("@unbound map",0)
            lib,off=cache[pc]
            if lib in local:offsets[lib].add(off)
            return lib,off
        kept=[];pre=0
        for d,chain in events:
            pid,tid,at,weight,ip=d
            if pid!=o["pid"]:continue
            if at<o["start_ns"]:pre+=1;continue
            need(tid in o["threads"],"sample outside observed native thread")
            if d in skid:
                kept.append((tid,("@kernel skid",0),[]));continue
            leaf=place(ip);stack=[]
            for x in chain:
                if x>=2**63:continue
                if not stack or x!=ip:stack.append(place(x))
            kept.append((tid,leaf,stack))
        per[k]=(kept,pre)
    resolved={};custody={}
    for lib,addrs in offsets.items():
        f,s,proof=local[lib];need(sha(f)==s,"wrong binary digest")
        actual=subprocess.check_output(["readelf","-nW",f],text=True,errors="replace")
        bid=re.findall(r"Build ID: ([0-9a-f]+)",actual);need(len(bid)<=1,"ambiguous ELF build ID")
        kernel_ids={r["buildid"]for m in allmap.values()for r in m if r["name"]==lib and r.get("buildid")}
        declared=kernel_ids|{buildids[lib]}if lib in buildids else kernel_ids
        if declared and bid:need(bid[0] in declared or bid[0][:40] in declared,"mismatched named image")
        if "librustc_driver"in lib:
            d=reg["tools"]["driver"]
            need(d["path"]==lib and d["sha256"]==s and all(any(r["name"]==lib and ((r.get("inode")==d["ino"] and (r.get("major"),r.get("minor"))==(os.major(d["dev"]),os.minor(d["dev"])))or (bid and (r.get("buildid")in (bid[0],bid[0][:40]) or (r.get("inode")==d["ino"] and buildids.get(lib)==bid[0]))))for r in m)for m in allmap.values()),"unbound actual driver PID/map")
        custody[lib]={"sha256":s,"proof":proof,"build_id":bid,"recorded_ids":sorted(declared)}
        debug=None
        if lib.startswith("/usr/lib/") and len(bid)==1 and bid[0] in declared:
            candidate=Path("/usr/lib/debug/.build-id")/bid[0][:2]/(bid[0][2:]+".debug")
            if candidate.is_file() and candidate.stat().st_size<16*1024*1024:
                notes=subprocess.check_output(["readelf","-nW",candidate],stderr=subprocess.DEVNULL,text=True)
                need(re.findall(r"Build ID: ([0-9a-f]+)",notes)==bid,"wrong separate debug ELF")
                debug=candidate;custody[lib]["debug_sha256"]=sha(debug)
        resolved[lib]=native_symbols(f,addrs,debug)
    result={};allrows={}
    for k,(selected,pre)in per.items():
        counts=collections.Counter();fun=collections.Counter();inc=collections.Counter();ds=collections.Counter();threads=collections.defaultdict(collections.Counter);details=collections.Counter()
        for tid,leaf,stack in selected:
            lib,off=leaf;syms=[a[0] for a in resolved.get(lib,{}).get(off,{}).get("symbols",[])];sc=groups(lib,syms)
            desc=syms[0]if len(set(syms))==1 else "@unresolved/aliased"
            if "libc.so" in lib and syms and len(set(syms))<=5:
                desc=" | ".join(sorted(set(syms)))
            counts[sc]+=1;ds[Path(lib).name]+=1
            threads[tid][sc]+=1;fun[(Path(lib).name,desc)]+=1;details[lib,off,sc,desc]+=1
            seen=set()
            for sl,so in stack:
                sn=[v[0]for v in resolved.get(sl,{}).get(so,{}).get("symbols",[])]
                if sn:seen.add(groups(sl,sn))
            inc.update(seen)
        o=owner[k];signed=reg["approximate_process_instruction_baselines"][k]
        result[k]={"pid":o["pid"],"period":period,"samples":len(selected),"before":pre,"sampled_process_instructions":o["instructions"],"unclocked":o["unclocked"],"whole_source_median_component":signed,"dso":ds,"exclusive":counts,"on_bound_call_chains":inc,"top_leaves":[[a,b,c]for (a,b),c in fun.most_common(100)],"threads":[{"tid":tid,"name":sorted(comm[o["pid"],tid]),"samples":sum(cs.values()),"exclusive":cs} for tid,cs in sorted(threads.items(),key=lambda v:-sum(v[1].values()))]}
        allrows[k]=[[l,off,cat,name,n]for(l,off,cat,name),n in sorted(details.items())]
    output={"kernel_source":ids,"kernel_records":records,"kernel_modes":modes,"kernel_chain_depth":depth,"binaries":custody,"owners":result}
    out.write_text(json.dumps(output,sort_keys=True,indent=2)+"\n")
    with gzip.open(out.with_suffix(".ndjson.gz"),"wt")as f:
        for k,rows in allrows.items():
            for row in rows:f.write(json.dumps([k,*row],separators=(",",":"))+"\n")
    return output

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("directory",type=Path);p.add_argument("archive",type=Path);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();v=analyse(a.directory,a.archive,a.output)
    for k,r in v["owners"].items():
        print(k,r["samples"],r["exclusive"],[(x["name"],x["samples"])for x in r["threads"][:7]])
