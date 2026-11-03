"""Join actual noinline attributes in signed LLVM IR to the full native Ruff archive and prior phase costs."""
import collections
import ctypes as C
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from census import functions,need,sha,download
from old_archive import iter_archive

class Api:
    def __init__(self,path):
        lib=C.CDLL(str(path));self.lib=lib
        ptr=C.c_void_p;size=C.c_size_t;string=C.c_char_p;i=C.c_int;u=C.c_uint;pp=C.POINTER(ptr)
        def fn(name,result,*args):
            f=getattr(lib,"LLVM"+name);f.argtypes=args;f.restype=result;return f
        self.context=fn("ContextCreate",ptr);self.free_context=fn("ContextDispose",None,ptr)
        self.buffer=fn("CreateMemoryBufferWithMemoryRangeCopy",ptr,string,size,string);self.free_buffer=fn("DisposeMemoryBuffer",None,ptr)
        self.parse=fn("ParseBitcodeInContext2",i,ptr,ptr,pp);self.free_module=fn("DisposeModule",None,ptr)
        self.first=fn("GetFirstFunction",ptr,ptr);self.next=fn("GetNextFunction",ptr,ptr)
        self.name=fn("GetValueName2",ptr,ptr,C.POINTER(size))
        self.declaration=fn("IsDeclaration",i,ptr);self.link=fn("GetLinkage",i,ptr)
        kind=fn("GetEnumAttributeKindForName",u,string,size);self.noinline=kind(b"noinline",8);need(self.noinline>0,"unknown attribute")
        self.attr=fn("GetEnumAttributeAtIndex",ptr,ptr,u,u)
        for part in ("TargetInfo","Target","TargetMC","AsmPrinter","AsmParser"):fn("InitializeX86"+part,None)()
        target=ptr();error=ptr();triple=b"x86_64-unknown-linux-gnu"
        need(fn("GetTargetFromTriple",i,string,pp,pp)(triple,C.byref(target),C.byref(error))==0,"different target triple")
        self.tm=fn("CreateTargetMachine",ptr,ptr,string,string,string,i,i,i)(target,triple,b"x86-64",b"",1,2,0)
        self.tm_free=fn("DisposeTargetMachine",None,ptr);self.options=fn("CreatePassBuilderOptions",ptr)()
        self.options_free=fn("DisposePassBuilderOptions",None,ptr);self.run=fn("RunPasses",ptr,ptr,string,ptr,ptr)
        self.write=fn("WriteBitcodeToMemoryBuffer",ptr,ptr);self.start=fn("GetBufferStart",ptr,ptr);self.size=fn("GetBufferSize",size,ptr)
        # Bind the C enum and function-attribute index to a typed positive and negative.
        control = b"declare void @external()\ndefine internal void @p() noinline { call void @external() ret void }\ndefine void @q() { call void @p() ret void }\n"
        ctx=self.context();buf=self.buffer(control,len(control),b"inline-kind-control");m=ptr();error=ptr()
        parse_ir=fn("ParseIRInContext",i,ptr,ptr,pp,pp)
        need(parse_ir(ctx,buf,C.byref(m),C.byref(error))==0,"invalid typed LLVM control")
        try:need(self.definitions(m)=={"p":(8,True),"q":(0,False)},"wrong linkage or noinline ABI")
        finally:self.free_module(m);self.free_context(ctx)
    def definitions(self,module):
        f=self.first(module);records={}
        while f:
            n=C.c_size_t();body=self.name(f,C.byref(n));name=C.string_at(body,n.value).decode()
            if not self.declaration(f) and name:
                need(name not in records,"duplicate function")
                records[name]=(int(self.link(f)),bool(self.attr(f,0xffffffff,self.noinline)))
            f=self.next(f)
        return records
    def inspect(self,raw,expected):
        ctx=self.context();b=self.buffer(raw,len(raw),b"pinned-ruff-cgu");m=C.c_void_p()
        try:
            need(self.parse(ctx,b,C.byref(m))==0,"original bitcode parse")
            before=self.definitions(m)
            need(not self.run(m,b"default<O1>",self.tm,self.options),"standard O1 pipeline")
            out=self.write(m)
            try:need(sha(C.string_at(self.start(out),self.size(out)))==expected,"different genuine optimized bitcode")
            finally:self.free_buffer(out)
            return before,self.definitions(m)
        finally:
            if m:self.free_module(m)
            self.free_buffer(b);self.free_context(ctx)
    def close(self):
        self.options_free(self.options);self.tm_free(self.tm)

def sdk(directory):
    manifest=json.loads((HERE.parents[2]/"ruff-foreign-span-observer/sdk.json").read_bytes())
    info=manifest["asset"];entry=manifest["members"]["lib/libLLVM.so.23.1-rust-1.99.0-beta"]
    need(entry[3]=="43bac9749e539cd5988a4d5452b64582cf07ac9e7c059fde29c7bee76e106c51","different signed LLVM ABI")
    endpoint="repos/astral-experiments/ohm/releases/assets/"+str(info["id"])
    receipt=json.loads(subprocess.check_output(["gh","api",endpoint]))
    need(all(receipt[k]==v for k,v in info.items()),"different released SDK")
    package=directory/"sdk.tar.gz"
    with package.open("xb")as f:subprocess.run(["gh","api",endpoint,"-H","Accept: application/octet-stream"],stdout=f,check=True)
    with package.open("rb")as f:need(package.stat().st_size==info["size"] and "sha256:"+hashlib.file_digest(f,"sha256").hexdigest()==info["digest"],"different signed archive")
    target=directory/"libLLVM.so"
    with tarfile.open(package,"r|gz")as archive:
        for member in archive:
            if member.name==entry[0]:
                need(member.isfile()and member.size==entry[2],"different native LLVM file")
                with archive.extractfile(member)as stream,target.open("xb")as out:shutil.copyfileobj(stream,out,2**20)
    with target.open("rb")as f:need(hashlib.file_digest(f,"sha256").hexdigest()==entry[3],"different current LLVM library")
    return target

def main():
    register=json.loads((HERE/"heldout-28106.json").read_bytes())
    tmp=Path(os.environ["RUNNER_TEMP"])/"owner-ir-held";tmp.mkdir()
    need(int(next(x for x in Path("/proc/meminfo").read_text().splitlines()if x.startswith("MemAvailable:")).split()[1])*1024>8*2**30 and shutil.disk_usage(tmp).free>15*2**30,"held-out reserve")
    packet=tmp/"original.zip";download(register["ordinary"],packet)
    api=Api(sdk(tmp));z=zipfile.ZipFile(packet);source=json.loads(z.read("capture/new/cgus.json"))["ruff_workspace"];descriptor=source["archive"]
    query=register["modules"];need(set(query)==set(source["emitted"]) and len(query)==21,"different actual recompiled roster")
    raw=gzip.decompress(z.read("cgu-originals/"+descriptor["sha256"]+".gz"));need(sha(raw)==descriptor["sha256"] and len(raw)==descriptor["stat"][2],"different genuine entire native archive")
    native=collections.defaultdict(list);units=set()
    for cgu,piece in iter_archive(raw,"ruff_workspace"):
        need(cgu not in units,"repeated native object");units.add(cgu)
        for name,binding,vis,size,idx,at,body,rels in functions(bytes(piece)):
            native[name].append((cgu,binding,size,body,rels))
    need(len(units)==125 and set(query)<=units,"incomplete native scope")
    rows={};classes=("native_distinct_owner","native_exact_private_other","baseline_private_noinline",
        "baseline_noinline_private_elsewhere","baseline_noinline_same_body_private_elsewhere","baseline_noinline_with_owner")
    charged={k:[0,0,0]for k in classes}
    for cgu,(source_sha,o1,ir,machine)in sorted(query.items()):
        bc=gzip.decompress(z.read("cgu-originals/"+source_sha+".gz"));need(sha(bc)==source_sha,"different real machine input")
        before,after=api.inspect(bc,o1)
        found={k:[]for k in classes}
        for name,(link,noinline)in before.items():
            if link not in (8,9) or name not in after:continue
            same=[x for x in native[name]if x[0]==cgu and x[1]==0]
            if not same:continue
            owners=[x for x in native[name]if x[0]!=cgu and x[1]in (1,2)]
            private=[x for x in native[name]if x[0]!=cgu and x[1]==0]
            identical=any(o[2:]==x[2:] for o in private for x in same)
            if owners:found["native_distinct_owner"].append(name)
            if identical:found["native_exact_private_other"].append(name)
            if not noinline or not after[name][1]:continue
            found["baseline_private_noinline"].append(name)
            if owners:found["baseline_noinline_with_owner"].append(name)
            if private:found["baseline_noinline_private_elsewhere"].append(name)
            if identical:found["baseline_noinline_same_body_private_elsewhere"].append(name)
        for k,v in found.items():
            if v:
                charged[k][0]+=1;charged[k][1]+=ir;charged[k][2]+=machine
        rows[cgu]={"input":source_sha,"optimized":o1,"pre_definitions":len(before),"post_definitions":len(after),
                   "pre_internal":sum(link in (8,9)for link,_ in before.values()),
                   "pre_internal_noinline":sum(link in (8,9)and noinline for link,noinline in before.values()),
                   "phase_guest_Ir":[ir,machine],"counts":{k:len(v)for k,v in found.items()},
                   "noinline_repeated":found["baseline_noinline_same_body_private_elsewhere"][:20]}
    api.close()
    result={"archive":descriptor["sha256"],"native_units":len(units),"rows":rows,"upper_unit_bounds_units_ir_machine":charged,
            "full_ir":sum(v[2] for v in query.values()),"full_machine":sum(v[3]for v in query.values())}
    (tmp/"result.json").write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")

if __name__=="__main__":
    main()
