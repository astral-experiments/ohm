"""Capture and describe each entire regular SysV/GNU rlib from one ordinary Ruff edit."""
import gzip
import hashlib
import json
import mmap
import os
from pathlib import Path
import shutil
import struct

ARMS = ("ordinary", "ordinary-repeat", "observed")
H = lambda data: hashlib.sha256(data).hexdigest()


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def save(path, value):
    path.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n")


def metadata_elf(data):
    """Bind every ELF64 little-endian section of a metadata wrapper, along with its original offsets."""
    need(len(data) >= 64 and bytes(data[:6]) == b"\x7fELF\x02\x01" and
         struct.unpack_from("<HH", data, 16) == (1,62), "expected an x86-64 relocatable metadata wrapper")
    section_at, = struct.unpack_from("<Q", data, 40)
    stride, count, names_index = struct.unpack_from("<HHH", data, 58)
    need(stride == 64 and 0 < names_index < count <= 4096 and section_at + stride * count <= len(data), "metadata section table")
    entries = list(struct.iter_unpack("<IIQQQQIIQQ", data[section_at:section_at + stride*count]))
    _, kind, _, _, string_at, string_size, *_ = entries[names_index]
    need(kind == 3 and string_at + string_size <= len(data), "metadata section names")
    strings = bytes(data[string_at:string_at+string_size])
    sections = []
    for i,(name, t, _, _, offset, size, *_) in enumerate(entries):
        stop = strings.find(b"\0", name)
        need(0 <= name <= stop and (t == 8 or offset+size <= len(data)), "metadata section bounds")
        sections.append({"i":i,"name":strings[name:stop].decode("ascii"),"type":t,"offset":offset,"bytes":size,
                         "header_sha256":H(data[section_at+i*stride:section_at+(i+1)*stride]),
                         "payload_sha256":None if t==8 else H(data[offset:offset+size])})
    return sections


def index_layout(data, width, member_at):
    need(len(data) >= width, "truncated GNU symbol index")
    n = int.from_bytes(data[:width],"big")
    end = width * (n+1)
    need(n <= 2000000 and end <= len(data), "invalid GNU symbol index")
    names = bytes(data[end:])
    pos, ordered, multiset, targets = 0, hashlib.sha256(), [], set()
    for i in range(n):
        off=int.from_bytes(data[width*(i+1):width*(i+2)],"big")
        terminator=names.find(b"\0",pos)
        need(off in member_at and terminator>pos,"GNU symbol or target outside the archive")
        symbol=names[pos:terminator]; pos=terminator+1
        member=member_at[off].encode("ascii"); targets.add(off)
        pair=hashlib.sha256(len(symbol).to_bytes(8,"big")+symbol+len(member).to_bytes(8,"big")+member).digest()
        ordered.update(pair); multiset.append(pair)
    # LLVM ar permits the aligned symbol string area to end in additional NUL bytes.
    need(not any(names[pos:]),"unaccounted GNU index bytes")
    return {"count":n,"distinct_member_targets":len(targets),"offsets_sha256":H(data[width:end]),"names_sha256":H(names),
            "ordered_symbol_member_sha256":ordered.hexdigest(),"symbol_member_multiset_sha256":H(b"".join(sorted(multiset)))}


def ar_layout(data):
    """Account for every original header, payload, GNU special member, and alignment byte without rewriting the archive."""
    need(bytes(data[:8]) == b"!<arch>\n", "expected a regular archive")
    offset, pending, names = 8, [], None
    while offset < len(data):
        header=bytes(data[offset:offset+60]); need(len(header)==60 and header[58:]==b"`\n","incomplete ar header")
        need(header[48:58].strip().isdigit(), "ar size")
        size=int(header[48:58]); start=offset+60; end=start+size
        need(end + (size&1) <= len(data) and len(pending)<200000, "ar member bounds")
        raw_name=header[:16].rstrip()
        pending.append((offset,header,raw_name,start,end))
        if raw_name==b"//":
            need(names is None,"two GNU filename tables")
            names=bytes(data[start:end])
        need(size % 2 == 0 or bytes(data[end:end+1])==b"\n", "ar alignment")
        offset=end+(size&1)
    members, symbols, member_at = [], [], {}
    for off, head, raw_name, start, end in pending:
        body=start
        if raw_name in (b"/",b"//",b"/SYM64/"):
            name=raw_name
        elif raw_name.startswith(b"/") and raw_name[1:].isdigit():
            p=int(raw_name[1:]); need(names is not None and p<len(names) and (p==0 or names[p-1:p]==b"\n"),"GNU long-name reference")
            e=names.find(b"/\n",p); need(e>p,"unterminated GNU member name"); name=names[p:e]
        elif raw_name.startswith(b"#1/") and raw_name[3:].isdigit():
            count=int(raw_name[3:]);body+=count;need(start<body<=end,"BSD name bounds");name=bytes(data[start:body]).rstrip(b"\0")
        else:
            need(not raw_name.startswith(b"/") and raw_name.endswith(b"/"),"unknown ar name encoding")
            name=raw_name[:-1]
        label=name.decode("ascii")
        row={"name":label,"offset":off,"raw_header_hex":head.hex(),"body_offset":body,"body_bytes":end-body,
             "stored_sha256":H(data[start:end]),"payload_sha256":H(data[body:end]),"pad_hex":bytes(data[end:end+((end-start)&1)]).hex()}
        if name in (b"lib.rmeta",b"lib.rmeta-link"):
            row["elf_sections"]=metadata_elf(data[body:end])
        if name in (b"/",b"/SYM64/"): symbols.append((row,start,end,8 if name==b"/SYM64/" else 4))
        elif name!=b"//": member_at[off]=label
        members.append(row)
    for row,start,end,width in symbols: row["gnu_index"]=index_layout(data[start:end],width,member_at)
    return {"sha256":H(data),"bytes":len(data),"ordered_members":members}


def capture(out, arm, path):
    """Preserve the complete artifact before decoding. Never write to the original Cargo output."""
    need(arm in ARMS, "unknown archive arm")
    path=Path(path)
    with path.open("rb") as f:
        state=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        old=state(os.fstat(f.fileno()))
        need(0<old[2]<=512<<20 and shutil.disk_usage(out).free-old[2]>15<<30,"archive capture bound")
        compressed=out/f"archive-{arm}.rlib.gz"
        with compressed.open("xb") as dst, gzip.GzipFile(filename="",fileobj=dst,mode="wb",mtime=0,compresslevel=2) as gz:
            shutil.copyfileobj(f,gz,1<<20)
        with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
            result=ar_layout(memoryview(data))
        need(state(os.fstat(f.fileno()))==old and state(path.stat())==old,"archive changed during capture")
    with gzip.open(compressed, "rb") as f: need(hashlib.file_digest(f,"sha256").hexdigest()==result["sha256"], "saved rlib differs from the source")
    with compressed.open("rb") as f: result["gzip_sha256"]=hashlib.file_digest(f,"sha256").hexdigest()
    # The captured metadata wrappers need no second copy: the full archive and the exact section extents are retained.
    result["gzip_bytes"]=compressed.stat().st_size
    result["actual_kit_path"]=str(path)
    save(out/f"archive-{arm}.json",result)
    return result


def compare(out):
    arms={k:json.loads((out/f"archive-{k}.json").read_bytes()) for k in ARMS}
    pairs={}
    for i,a in enumerate(ARMS):
        for b in ARMS[i+1:]:
            left,right=arms[a],arms[b]
            L,R=left["ordered_members"],right["ordered_members"]
            ln,rn=[u["name"] for u in L],[u["name"] for u in R]
            need(len(set(ln))==len(ln) and len(set(rn))==len(rn),"ambiguous named members in actual Ruff rlib")
            lm,rm={u["name"]:u for u in L},{u["name"]:u for u in R}
            common=sorted(set(lm)&set(rm)); meta={}
            for k in ("lib.rmeta","lib.rmeta-link"):
                if k not in common: continue
                ls,rs=lm[k]["elf_sections"],rm[k]["elf_sections"]
                meta[k]={"ordered_sections_agree":[(v["name"],v["type"])for v in ls]==[(v["name"],v["type"])for v in rs],
                         "differing_sections":[[x["name"],y["name"]] for x,y in zip(ls,rs) if x!=y],
                         "differing_payloads":[[x["name"],y["name"]] for x,y in zip(ls,rs) if x["payload_sha256"]!=y["payload_sha256"]]}
            pairs[a+" vs "+b]={"whole_bytes_equal":(left["sha256"],left["bytes"])==(right["sha256"],right["bytes"]),
                "member_order_equal":ln==rn,"removed":sorted(set(ln)-set(rn)),"added":sorted(set(rn)-set(ln)),
                "different_payloads":[k for k in common if lm[k]["payload_sha256"]!=rm[k]["payload_sha256"]],
                "different_headers":[k for k in common if lm[k]["raw_header_hex"]!=rm[k]["raw_header_hex"] or lm[k]["pad_hex"]!=rm[k]["pad_hex"]],
                "gnu_index_equal":{k:lm[k].get("gnu_index")==rm[k].get("gnu_index") for k in ("/","/SYM64/") if k in common},
                "metadata":meta}
    result={"archives":{k:{f:v[f] for f in ("bytes","sha256","gzip_bytes","gzip_sha256")}for k,v in arms.items()},"pairs":pairs}
    save(out/"archive-comparison.json",result)
    return result


class DiscoveryComplete(Exception):
    """The archive diagnostic obtained three complete equal programs; no real unit prices were opened."""
