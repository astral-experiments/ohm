"""Inventory real outlined definitions, exported owners, and function relocations in the parent artifacts."""
import collections
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
sys.path.insert(0,str(HERE.parent/"owner-lanes"))
sys.path.insert(0,str(HERE.parent/"owner-lanes/evidence-two-edits"))
from member_names import read_names
from partition_outcome import Archive,need
from reopen import materialize
from review_originals import download

def sha(data):
    return hashlib.sha256(data).hexdigest()

def functions(raw):
    h=struct.unpack_from("<16sHHIQQQIHHHHHH",raw)
    need(h[0][:7]==b"\x7fELF\x02\x01\x01" and h[1:3]==(1,62) and h[-3]==64 and 0<h[-1]<h[-2], "nonbaseline x86 ELF shape")
    sections=list(struct.iter_unpack("<IIQQQQIIQQ",raw[h[6]:h[6]+64*h[-2]]))
    def data(i):
        s=sections[i];return raw[s[4]:s[4]+s[5]] if s[1]!=8 else b""
    def string(buf,off):
        return buf[off:buf.index(0,off)].decode("utf-8")
    names_data=data(h[-1]);names=[string(names_data,s[0]) for s in sections]
    si,=(i for i,s in enumerate(sections) if s[1]==2)
    st=data(sections[si][6])
    syms=[(string(st,n),kind,other,idx,start,nbytes) for n,kind,other,idx,start,nbytes in struct.iter_unpack("<IBBHQQ",data(si))]
    rel=collections.defaultdict(list)
    for i,s in enumerate(sections):
        if s[1]!=4 or not sections[s[7]][2]&4:continue
        need(s[6]==si and s[9]==24, "unsupported text relocation form")
        for off,info,add in struct.iter_unpack("<QQq",data(i)):
            target,kind,other,idx,val,size=syms[info>>32]
            where=names[idx] if 0<idx<len(names) else idx
            rel[s[7]].append((off,info&0xffffffff,target,kind,other,where,val,size,add))
    out=[]
    for symbol,kind,visibility,idx,offset,length in syms:
        if kind&15!=2 or not length or not symbol or not idx:continue
        need(0<idx<len(names) and sections[idx][2]&4 and offset+length<=sections[idx][5], "invalid emitted function range")
        actual=raw[sections[idx][4]+offset:sections[idx][4]+offset+length]
        fixups=[(at-offset,*target) for at,*target in rel[idx] if offset<=at<offset+length]
        out.append((symbol,kind>>4,visibility,length,idx,offset,sha(actual),sha(json.dumps(fixups,separators=(",",":")).encode())))
    return out

def read_cgus(path,registered):
    names={r[0]:r for r in registered["members"]}
    units={}
    with path.open("rb")as f:
        need(f.read(8)==b"!<arch>\n","GNU archive")
        longnames=None
        while f.tell()<path.stat().st_size:
            hdr=f.read(60);need(len(hdr)==60 and hdr[-2:]==b"`\n","archive header")
            field=hdr[:16].rstrip();n=int(hdr[48:58]);payload=f.read(n)
            need(len(payload)==n and (not n&1 or f.read(1)==b"\n"),"archive extent")
            if field==b"//":longnames=payload;continue
            if field in (b"/",b"/SYM64/"):continue
            if field.startswith(b"/"):
                off=int(field[1:]);end=longnames.index(b"/\n",off);name=longnames[off:end].decode()
            else:name=field.removesuffix(b"/").decode()
            if name not in names:
                need(not name.endswith(".rcgu.o"),("unregistered object",name));continue
            _,_,cgu,digest,size=names[name]
            need(size==n and sha(payload)==digest and cgu not in units,"different physical work product")
            units[cgu]=functions(payload)
        need(len(units)==len(names),"missing original member")
    return units

def aggregate(units,edited):
    by_name=collections.defaultdict(list)
    for cgu,defs in units.items():
        for name,binding,vis,sz,section,begin,body,rel in defs:
            by_name[name].append((cgu,binding,vis,sz,section,begin,body,rel))
    group=collections.defaultdict(list);examples=[];population=collections.Counter()
    for name,defs in by_name.items():
        local=[d for d in defs if d[1]==0];export=[d for d in defs if d[1] in (1,2)]
        for d in defs:
            population[("local" if d[1]==0 else "external")]+=1
            if d[0] in edited:group["all_affected"].append(d)
        for d in local:
            if d[0] not in edited:continue
            group["all_affected_local"].append(d)
            private_elsewhere=[e for e in local if e[0]!=d[0]]
            same_body=[e for e in private_elsewhere if (e[3],e[6:])==(d[3],d[6:])]
            owners=[e for e in export if e[0]!=d[0]]
            if private_elsewhere:group["same_local_name_other_unit"].append(d)
            if same_body:group["same_local_name_bytes_and_relocations_other_unit"].append(d)
            if any(e[0] not in edited for e in same_body):group["same_local_name_bytes_and_relocations_in_retained_unit"].append(d)
            if owners:
                group["same_local_name_also_external_elsewhere"].append(d)
                if any((e[3],e[6:])==(d[3],d[6:])for e in owners):
                    group["same_name_identical_machine_link_and_external_elsewhere"].append(d)
                examples.append([d[3],name,d[0],[(e[0],e[1],e[2],e[3]) for e in owners]])
    def summarize(ds):
        intervals=collections.defaultdict(list)
        for cgu,_,_,size,section,begin,*_ in ds:intervals[cgu,section].append((begin,begin+size))
        size=0
        for spans in intervals.values():
            tail=-1
            for begin,end in sorted(spans):
                if end>tail:size+=end-max(begin,tail);tail=end
        return {"function_rows":len(ds),"unique_function_range_bytes":size}
    groups=["all_affected","all_affected_local","same_local_name_other_unit",
            "same_local_name_bytes_and_relocations_other_unit","same_local_name_bytes_and_relocations_in_retained_unit",
            "same_local_name_also_external_elsewhere","same_name_identical_machine_link_and_external_elsewhere"]
    return {"units":len(units),"affected":sorted(edited),"all_definition_rows":dict(population),"distinct_names":len(by_name),
            "ranges":{name:summarize(group[name])for name in groups},"matching_external_examples":sorted(examples,reverse=True)[:20]}

def run(packet,case,digest,tmp):
    archive=Archive(packet);terminal=archive.js("result.json");need(terminal["case"]==case,"wrong original case")
    with packet.open("rb")as f:need(hashlib.file_digest(f,"sha256").hexdigest()==digest,"different native study")
    role="P";change=archive.js("P/edit-retention.json")["ty_project"]
    edited={n.removesuffix(".o")for name,r in change.items()if name.startswith("regenerated_")for n in r["names"]}
    report={}
    for phase in ("old","edit"):
        ref=archive.js(role+"/"+phase+"/native.json")["ty_project"];rlib=tmp/(case+"-"+phase+".rlib")
        materialize(archive,ref["library"],rlib)
        mapped=read_names(rlib,"ty_project");need(mapped==ref["mapping"],"different native ar index or bodies")
        units=read_cgus(rlib,mapped);need(edited<=units.keys(),"missing known regenerated units")
        report[phase]=aggregate(units,edited)
        report[phase]["rlib_sha256"]=ref["library"]["sha256"]
    return report

def main():
    tmp=Path(os.environ["RUNNER_TEMP"])/"inline-baseline";tmp.mkdir()
    need(int(next(x for x in Path("/proc/meminfo").read_text().splitlines() if x.startswith("MemAvailable:")).split()[1])*1024>8*2**30
         and shutil.disk_usage(tmp).free>15*2**30,"full-native census reserve")
    binding=json.loads((HERE.parent/"owner-lanes/evidence-two-edits/physical-bindings.json").read_bytes())
    out=tmp/"results";out.mkdir()
    for case,row in binding.items():
        p=tmp/(case+".zip");digest=download(row["ordinary"],p)
        r=run(p,case,digest,tmp);(out/(case+".json")).write_text(json.dumps(r,sort_keys=True,indent=2)+"\n")

if __name__=="__main__":
    main()
