"""Count the two real build roots after an ordinary visit, including actual optional index bytes."""
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import stat
import struct

MAGIC=b"OHMSPL02"
END=b"rust-end-file"


def parse_footer(raw):
    if not raw.startswith(b"RSIC") or not raw.endswith(END):
        raise ValueError("unrecognized work-product index frame")
    end=len(raw)-len(END)
    pos=raw.find(MAGIC,0,end)
    if pos<0:
        return None
    cursor=pos+len(MAGIC)
    slots=[]
    prev=-1
    while cursor<end:
        if cursor+8>end:
            raise ValueError("partial optional entry header")
        slot,size=struct.unpack_from("<II",raw,cursor)
        cursor+=8
        if slot<=prev or size<4+32+17+32 or cursor+size>end or raw[cursor:cursor+4]!=b"OSP\x01" or raw[cursor+36:cursor+53]!=b"CGU-GLOBAL-LINES\x01":
            raise ValueError("incorrect optional slot framing")
        slots.append([slot,size,raw[cursor+4:cursor+36].hex(),raw[cursor+size-32:cursor+size].hex()])
        cursor+=size
        prev=slot
    if not slots or cursor!=end:
        raise ValueError("empty or incomplete optional index")
    return {"offset":pos,"bytes":end-pos,"prefix_sha256":hashlib.sha256(raw[:pos]).hexdigest(),"entries":slots,
            "sha256":hashlib.sha256(raw).hexdigest()}


def walk(root):
    pending=[root]
    while pending:
        p=pending.pop()
        s=p.lstat()
        yield p,s
        if stat.S_ISDIR(s.st_mode):
            pending.extend(sorted(p.iterdir(),reverse=True))


def census(work,where,index_store):
    seen=set()
    roots={}
    footers={}
    indices={}
    unique=Counter()
    raw=where/"actual-storage.jsonl.gz"
    with gzip.open(raw,"xt",encoding="utf-8") as out:
        for name in ("target","build"):
            top=work/name
            if not top.is_dir() or top.is_symlink():
                raise ValueError("absent real Cargo target or build root")
            counts=Counter()
            for p,s in walk(top):
                relative=str(p.relative_to(top))
                ref=(s.st_dev,s.st_ino)
                blocks=s.st_blocks*512
                data=[name,relative,s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,blocks]
                if stat.S_ISLNK(s.st_mode):
                    data.append(os.readlink(p))
                print(json.dumps(data,ensure_ascii=True,separators=(",",":")),file=out)
                counts["paths"]+=1;counts["logical_bytes_per_path"]+=s.st_size;counts["allocated_bytes_per_path"]+=blocks
                if ref in seen:
                    continue
                seen.add(ref)
                counts["unique_first_here"]+=1;counts["allocated_first_here"]+=blocks;unique["allocated"]+=blocks
                kind=("directory" if stat.S_ISDIR(s.st_mode) else "symlink" if stat.S_ISLNK(s.st_mode)
                      else "index" if p.name=="work-products.bin" else "object" if p.suffix==".o"
                      else "incremental_other" if "incremental" in p.parts else "other")
                unique[kind]+=blocks
                if kind=="index":
                    if s.st_size>256<<20:raise ValueError("oversized work-product index")
                    data=p.read_bytes()
                    digest=hashlib.sha256(data).hexdigest()
                    where_saved=index_store/(digest+".gz")
                    if not where_saved.exists():
                        with gzip.open(where_saved,"xb",compresslevel=4) as raw_index:raw_index.write(data)
                    indices[name+"/"+relative]=[digest,len(data)]
                    footer=parse_footer(data)
                    if footer:
                        footers[name+"/"+relative]=footer
            roots[name]=dict(counts)
    with raw.open("rb") as file: rows_sha=hashlib.file_digest(file,"sha256").hexdigest()
    return {"roots":roots,"union_unique":len(seen),"allocated":dict(unique),"rows_sha256":rows_sha,
            "optional_tail_bytes":sum(v["bytes"] for v in footers.values()),"optional_entries":sum(len(v["entries"]) for v in footers.values()),
            "indices":indices,"footers":footers}
