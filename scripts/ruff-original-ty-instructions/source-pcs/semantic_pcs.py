"""Bind sampled PCs to kernel MMAP2 ranges, real executable LOAD segments and covered symbols."""
from bisect import bisect_left
from collections import Counter,defaultdict
import gzip
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from pc_raw import check,raw_records,symbol_rows

def sha(path):
    with path.open("rb")as f:return hashlib.file_digest(f,"sha256").hexdigest()

def output(path,body):
    path.write_text(json.dumps(body,sort_keys=True,indent=1)+"\n")

def mappings(buf,pid):
    header=struct.unpack_from("<9Q",buf);at,total=header[5:7];end=at+total;rs=[]
    while at<end:
        kind,misc,n=struct.unpack_from("<IHH",buf,at)
        check(n>=8 and at+n<=end,"invalid map record")
        if kind==10:
            proc,tid,base,length,off,major,minor,ino,generation,prot,flags=struct.unpack_from("<IIQQQIIQQII",buf,at+8)
            if proc==pid and prot&4:
                name=buf[at+72:at+n].split(b"\0",1)[0].decode(errors="surrogateescape")
                row=dict(base=base,length=length,off=off,name=name,prot=prot,flags=flags)
                if misc&16384:
                    size=buf[at+40];check(0<size<=20,"unexpected map build ID");row["buildid"]=buf[at+44:at+44+size].hex()
                else:row.update(major=major,minor=minor,inode=ino)
                if row not in rs:rs.append(row)
        at+=n
    check(at==end and rs,"missing selected executable maps");return rs

def file_info(path):
    st=path.stat()
    with path.open("rb")as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)as elf:
        check(elf[:6]==b"\x7fELF\x02\x01","unsupported mapped executable")
        phoff=struct.unpack_from("<Q",elf,32)[0];entry,number=struct.unpack_from("<HH",elf,54)
        segments=[]
        for i in range(number):
            typ,flags,off,va,_,size,mem,_=struct.unpack_from("<IIQQQQQQ",elf,phoff+i*entry)
            if typ==1 and flags&1:segments.append([off,va,size,mem])
        check(segments,"no executable program segment")
    sections=subprocess.check_output(["readelf","-SW",path],text=True)
    notes=subprocess.check_output(["readelf","-nW",path],text=True,errors="replace")
    ids=re.findall(r"Build ID: ([0-9a-f]+)",notes);check(len(ids)<=1,"ambiguous GNU build ID")
    return dict(sha256=sha(path),device=st.st_dev,inode=st.st_ino,bytes=st.st_size,gnu_build_id=ids[0] if ids else None,
                segments=segments,debug_sections=sorted(set(re.findall(r"\s(\.(?:z?debug_\w+|gnu_debug\w+|dynsym|symtab))\s",sections))))

def symbol_ranges(path,values):
    addresses=sorted(values);out=defaultdict(set)
    for args in ([],["-D"]):
        with subprocess.Popen(["nm",*args,"-S","--defined-only",path],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL) as proc:
            for line in proc.stdout:
                cols=line.split(None,3)
                if len(cols)!=4 or cols[2] not in (b"t",b"T",b"w",b"W",b"i",b"I"):continue
                start=int(cols[0],16);size=int(cols[1],16)
                idx=bisect_left(addresses,start);finish=start+size
                while idx<len(addresses) and addresses[idx]<finish:
                    out[addresses[idx]].add((start,size,cols[3].strip().decode(errors="replace")));idx+=1
            proc.wait()
        if all(out.get(x) for x in addresses):break
    return out

def analyze(raw,root,kit,minimum,*,owner="ty_ide"):
    buf=raw.read_bytes();period,ips,records,depth,modes,skid=raw_records(buf)
    counted=json.loads((root/"record-counts.json").read_bytes())
    check(not any(records.get(k,0) for k in (2,5,6,13)) and records[9]==counted["PERF_RECORD_SAMPLE"],"lost or displaced kernel samples")
    with (root/"samples.ndjson.gz").open("rb")as f:frames,rows=symbol_rows(f)
    check(Counter(v[0]for v in rows)==ips,"perf Python source rows differ from original kernel PC/PID/TID/time/period")
    target=json.loads((root/"owner-epochs.json").read_bytes())[owner];pid=target["pid"];start=target["start_ns"]
    later=[int(s[4]) for l in (root/"exec/epochs.tsv").read_text().splitlines() if (s:=l.split())[0]=="I" and int(s[2])==pid and int(s[4])>start]
    check(not later,"later image in selected PID")
    maps=mappings(buf,pid);del buf
    represented={};buildids={}
    for line in (root/"buildids.txt").read_text().splitlines():
        fields=line.strip().split(maxsplit=1)
        if len(fields)==2 and re.fullmatch("[a-f0-9]+",fields[0]):buildids[fields[1]]=fields[0]
    for row in maps:
        name=row["name"];p=Path(name)
        if not p.is_absolute() or not p.is_file():continue
        if name not in represented:represented[name]=file_info(p)
        f=represented[name];bid=f["gnu_build_id"]
        row["inode_match"]=row.get("inode")==f["inode"] and (row.get("major"),row.get("minor"))==(os.major(f["device"]),os.minor(f["device"]))
        row["recorded_buildid_match"]=bool(bid and (bid==row.get("buildid") or bid==buildids.get(name)))
        row["authenticated"]=row["inode_match"] or row["recorded_buildid_match"]
    driver=kit["driver"]["path"]
    check(driver in represented and represented[driver]["sha256"]==kit["driver"]["sha256"] and any(r["name"]==driver and r.get("authenticated") for r in maps),"signed driver/mapping mismatch")
    literal=Counter();leaves={};pc_weights=Counter();reasons=Counter();pending=defaultdict(set);chain_depth=Counter();before=0
    for datum,leaf,stack in rows:
        proc,tid,ts,h,ip=datum
        if proc!=pid:continue
        if ts<start:before+=1;continue
        check(tid in target["threads"],"unknown selected kernel thread")
        pc_weights[ip]+=1;chain_depth[len(stack)]+=1
        ds,sym=frames[leaf[0]];literal[ds,sym]+=1
        if datum in skid:reasons["kernel skid"]+=1;continue
        candidates=[r for r in maps if r["base"]<=ip<r["base"]+r["length"]]
        fits={(r["name"],r["off"]+ip-r["base"]) for r in candidates if r.get("authenticated")}
        if len(fits)!=1:
            reasons["unbound or ambiguous executable mapping"]+=1;continue
        name,off=fits.pop();segs=represented[name]["segments"]
        vas={va+off-so for so,va,fs,ms in segs if so<=off<so+fs}
        if len(vas)!=1:reasons["outside executable file bytes"]+=1;continue
        va=vas.pop();pending[name].add(va)
        key=(name,va,ip,ds,sym);leaves[key]=leaves.get(key,0)+1
    n=sum(pc_weights.values());check(n>=minimum and abs(n*period/target["instructions"]-1)<.03,"insufficient owner coverage versus disjoint native counter")
    tool=Path("/usr/bin/llvm-symbolizer-18").resolve(strict=True)
    rows_out=[];coverage=Counter();dso_totals=Counter()
    for name,vas in sorted(pending.items()):
        order=sorted(vas);native=symbol_ranges(Path(name),order)
        pro=subprocess.run([tool,"--obj="+name,"--inlining","--demangle","--output-style=JSON"],
                           input="".join(f"0x{x:x}\n" for x in order),text=True,capture_output=True,check=True,timeout=240,
                           env={"PATH":"/usr/bin:/bin","LC_ALL":"C","DEBUGINFOD_URLS":""})
        decoded=[json.loads(s) for s in pro.stdout.splitlines()];check(len(decoded)==len(order),"symbolizer omitted PCs")
        records_by_va={}
        for va,val in zip(order,decoded):
            check(int(val["Address"],16)==va and val["ModuleName"]==name,"symbolizer read other executable/PC")
            records_by_va[va]=val["Symbol"]
        for (other,va,ip,perf_dso,perf_name),samples in leaves.items():
            if other!=name:continue
            frames_at=records_by_va[va];nearest=sorted(native[va]);category=("inline source" if len(frames_at)>1 and any(x["FileName"] and x["Line"] for x in frames_at) else
                "source line" if any(x["FileName"] and x["Line"] for x in frames_at) else "bounded ELF symbol" if nearest else "unresolved symbol")
            coverage[category]+=samples;dso_totals[name]+=samples
            rows_out.append(dict(ip=ip,va=va,samples=samples,dso=name,reported_dso=perf_dso,reported_symbol=perf_name,
                                 symbol_ranges=nearest,source_frames=frames_at,resolution=category))
    check(sum(reasons.values())+sum(coverage.values())==n,"nonpartitioned samples")
    with gzip.open(root/"leaf-placements.ndjson.gz","wt",compresslevel=5)as out:
        for row in sorted(rows_out,key=lambda x:(x["dso"],x["va"],x["reported_symbol"])):
            print(json.dumps(row,separators=(",",":")),file=out)
    output(root/"semantic.json",dict(owner=target,exact_instructions=target["instructions"],period=period,samples=n,represented_instructions=n*period,
           all_process_samples=records[9],pre_owner_same_pid=before,coverage=coverage,unplaced=reasons,source_dsos=dso_totals,callchain_depth=chain_depth,
           symbolizer=dict(path=str(tool),sha256=sha(tool)),binaries=represented,executable_maps=maps,leaf_placements_sha256=sha(root/"leaf-placements.ndjson.gz")))
    print("Selected genuine signed compiler",pid,target["instructions"],"instructions",n,"native samples",dict(coverage),flush=True)
