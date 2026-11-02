"""Independently reopen the held-out registry operands, their metadata, archive members and producers."""
from collections import Counter
from difflib import unified_diff
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct

from shards import map_path
from transport import need

H=lambda b:hashlib.sha256(b).hexdigest()


def ar(data):
    need(data.startswith(b"!<arch>\n"),"not a normal static archive")
    pos=8;result=[];strings=b""
    while pos<len(data):
        header=data[pos:pos+60];need(len(header)==60 and header[58:]==b"`\n","malformed archive header")
        raw=header[:16].decode().rstrip();n=int(header[48:58]);lo=pos+60;end=lo+n
        need(n>=0 and end<=len(data),"truncated archive")
        body=data[lo:end];name=raw
        if raw=="//":strings=body
        elif re.fullmatch(r"/[0-9]+",raw):
            offset=int(raw[1:]);stop=strings.find(b"/\n",offset)
            need(0<=offset<stop,"bad extended GNU archive name")
            name=strings[offset:stop].decode()
        elif raw.startswith("#1/"):
            width=int(raw[3:]);name=body[:width].rstrip(b"\0").decode();body=body[width:]
        elif raw not in ("/","/SYM64/"):
            name=raw.rstrip("/")
        result.append((name,header,body))
        pos=end+(n&1)
    need(pos==len(data),"trailing archive data")
    return result


def sections(data):
    need(data[:6]==b"\x7fELF\x02\x01","unexpected object encoding")
    e=struct.unpack_from("<16sHHIQQQIHHHHHH",data)
    need(e[-3]==64 and 0<e[-2]<65535 and 0<=e[-1]<e[-2],"unknown ELF indexing")
    table=[struct.unpack_from("<IIQQQQIIQQ",data,e[6]+64*n) for n in range(e[-2])]
    names=table[e[-1]];ss=data[names[4]:names[4]+names[5]];rows=[]
    for r in table:
        n=ss[r[0]:ss.index(0,r[0])].decode()
        payload=b"" if r[1]==8 else data[r[4]:r[4]+r[5]]
        rows.append((n,r,H(payload)))
    return rows


def delta(a,b,old,new):
    if a==b:return {"equal":True,"bytes":len(a)}
    if len(a)!=len(b):
        return {"equal":False,"sizes":[len(a),len(b)],"sha":[H(a),H(b)]}
    n=a.replace(old.encode(),new.encode()) if old!=new else a
    out={"equal":False,"bytes":len(a),"sha":[H(a),H(b)],"observed_v2_replacements":a.count(old.encode()) if old!=new else 0,
         "all_bytes_equal_after_exact_v2":n==b}
    if n==b:return out
    spans=[]
    start=None
    for i,(x,y) in enumerate(zip(n,b,strict=True)):
        if x!=y and start is None:start=i
        if x==y and start is not None:
            spans.append((start,i));start=None
    if start is not None:spans.append((start,len(a)))
    out.update(residual_byte_count=sum(v-u for u,v in spans),residual_run_count=len(spans),
               first_residual_spans=[[u,v,n[u:min(v,u+32)].hex(),b[u:min(v,u+32)].hex()] for u,v in spans[:24]])
    return out


def archive_delta(a,b,sa,sb):
    left,right=ar(a),ar(b)
    value={"entries":[len(left),len(right)],"ordered_names_match":[r[0] for r in left]==[r[0] for r in right],
           "headers_match":[r[1] for r in left]==[r[1] for r in right],"different_members":[]}
    if not value["ordered_names_match"]:return value
    for index,((name,_,x),(_,_,y)) in enumerate(zip(left,right,strict=True)):
        if x==y:continue
        m={"member":name,"index":index,"bytes":delta(x,y,sa,sb)}
        if x.startswith(b"\x7fELF") and y.startswith(b"\x7fELF"):
            ls,rs=sections(x),sections(y)
            m["ordered_sections_match"]=[s[0] for s in ls]==[s[0] for s in rs]
            if m["ordered_sections_match"]:
                m["different_section_fields"]=[{"index":k,"name":p[0],"flags":[p[1][2],q[1][2]],
                    "sizes":[p[1][5],q[1][5]],"sha":[p[2],q[2]],"header_equal":p[1]==q[1]}
                    for k,(p,q) in enumerate(zip(ls,rs,strict=True)) if p!=q]
        value["different_members"].append(m)
    return value


def scan(z,suite,dirs,shards):
    pre="physical/"+suite+"/"
    def read(name):return json.loads(z.read(name))
    seen=set()
    @lru_cache(maxsize=10)
    def body(key):
        with z.open("physical/extern-inputs/"+key) as f,gzip.GzipFile(fileobj=f) as source:
            b=source.read((128<<20)+1)
        need(0<len(b)<=128<<20 and H(b)==key,"invalid original input body")
        seen.add(key);return b
    def rec(row):
        b=body(row["sha"]);need(len(b)==row["size"],"wrong input size");return b
    sets={};where={}
    for role in ("P","C"):
        sets[role]={}
        for phase in ("old","new","clean-new"):
            prefix=pre+role+("-clean/" if phase=="clean-new" else "-edit/")+phase
            where[role,phase]=prefix
            a=read(prefix+"/extern-audit.json");k=read(prefix+"/kernel.json");task=read(prefix+"/command.json")
            need((a["role"],a["phase"])==(role,phase) and dirs=={n:task["environment"][n] for n in dirs},"wrong physical source phase")
            for name,row in a["named"].items():
                need(name==map_path(row["path"],dirs,set()),"foreign shared artifact path");rec(row["body"])
                if phase=="new":
                    physical=read(prefix+"/shared-extern-files.json")[row["path"]]
                    need(physical["sha256"]==row["body"]["sha"] and physical["identity"]==row["body"]["stat"],"different actual warm input")
                    continue
                prod=a["producers"][str(row["producer"])]
                rust,=[r for r in k["compilers"] if r["pid"]==row["producer"]]
                need(rust["kind"]=="full" and rust["name"]==prod["name"] and rust["argv"]==prod["argv"] and rust["exec"]==prod["actual_exec"] and
                     prod["argv"][prod["argv"].index("--out-dir")+1]==str(Path(row["path"]).parent),"different original producing compiler")
                need(set(prod["extern"])=={v for i,v in enumerate(prod["argv"]) if i and prod["argv"][i-1]=="--extern" and "=" in v},
                     "incomplete immediate producer inputs")
                for v in prod["extern"].values():rec(v)
                for v in prod["generated"].values():
                    if v["size"]:rec(v)
                for v in prod["dep_info"].values():rec(v)
                rec(prod["source"][1])
                if row.get("decoded"):
                    d=row["decoded"];payload=z.read(prefix+"/"+d["member"])
                    need(H(payload)==d["sha"] and len(payload)==d["bytes"] and b"Crate info:" in payload,"different metadata listing")
            sets[role][phase]=a
    result={"same_arm":{},"same_arm_producers":{},"cross":{}}
    for r,ph in sets.items():
        keys=set(ph["old"]["named"])
        need(keys==set(ph["new"]["named"])==set(ph["clean-new"]["named"]),"different independent native input sets")
        result["same_arm"][r]={k:[ph[phase]["named"][k]["body"]["sha"] for phase in ("old","new","clean-new")] for k in sorted(keys)}
        same={}
        for k in sorted(keys):
            producers=[ph[n]["producers"][str(ph[n]["named"][k]["producer"])] for n in ("old","clean-new")]
            a,b=producers
            same[k]={"source":a["source"][0]==b["source"][0] and a["source"][1]["sha"]==b["source"][1]["sha"],
                     "manifest":a["manifest"]==b["manifest"],"out_dir":a["out_dir"]==b["out_dir"],
                     "actual_argv":a["argv"]==b["argv"],
                     "generated":{n:v["sha"] for n,v in a["generated"].items()}=={n:v["sha"] for n,v in b["generated"].items()},
                     "immediate_deps":{n:v["sha"] for n,v in a["extern"].items()}=={n:v["sha"] for n,v in b["extern"].items()}}
        result["same_arm_producers"][r]=same
    need(set(sets["P"]["old"]["named"])==set(sets["C"]["old"]["named"]),"different parent and candidate filenames")
    def norm(s,r):return s.replace(shards[r],"<observed-compiler-identity>")
    for name in sorted(sets["P"]["old"]["named"]):
        row=[sets[r]["clean-new"]["named"][name] for r in ("P","C")]
        w=[rec(f["body"]) for f in row];pa,pb=shards["P"],shards["C"]
        desc=delta(*w,pa,pb)
        if name.endswith(".rlib") and w[0]!=w[1]:
            desc["archive"]=archive_delta(*w,pa,pb)
        if name.endswith(".rmeta"):
            texts=[z.read(where[r,"clean-new"]+"/"+f["decoded"]["member"]).decode() for r,f in zip(("P","C"),row,strict=True)]
            line=list(unified_diff(texts[0].splitlines(),texts[1].splitlines(),n=1))
            desc["decoder"]={"identical_all_lines":texts[0]==texts[1],"bytes":[len(t.encode()) for t in texts],
                             "lines":[len(t.splitlines()) for t in texts],"differences":line[:80],"truncated":len(line)>80}
        prods=[sets[r]["clean-new"]["producers"][str(f["producer"])] for r,f in zip(("P","C"),row,strict=True)]
        inputs=[{norm(n,r):v["sha"] for n,v in p["extern"].items()} for r,p in zip(("P","C"),prods,strict=True)]
        g=[{n:v["sha"] for n,v in p["generated"].items()} for p in prods]
        desc["producer"]={"name":prods[0]["name"],"same_source":prods[0]["source"][1]["sha"]==prods[1]["source"][1]["sha"],
             "same_argv_after_exact_shard":[norm(s,"P") for s in prods[0]["argv"]]==[norm(s,"C") for s in prods[1]["argv"]],
             "same_generated_relative_files_and_bytes":g[0]==g[1],"out_dirs":[p["out_dir"] for p in prods],
             "immediate_inputs":len(inputs[0]),"same_immediate_names":set(inputs[0])==set(inputs[1]),
             "different_immediate_bodies":{p:[inputs[0].get(p),inputs[1].get(p)] for p in sorted(set(inputs[0])|set(inputs[1])) if inputs[0].get(p)!=inputs[1].get(p)}}
        result["cross"][name]=desc
    return result|{"unique_input_bodies_reopened":len(seen)}
