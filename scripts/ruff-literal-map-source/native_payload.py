"""Read every full object payload in a GNU rlib, including long-name members."""
import hashlib
from pathlib import Path
import re
import subprocess

def need(value,why):
    if not value:
        raise ValueError(why)

def store_member(stream,start,size,key,store):
    dst=store/(key+".zst")
    if dst.exists():return
    stream.seek(start);left=size
    with subprocess.Popen(["zstd","-q","-3","-o",str(dst)],stdin=subprocess.PIPE) as child:
        while left:
            block=stream.read(min(left,1<<20));need(block,"truncated original archive bytes")
            child.stdin.write(block);left-=len(block)
        child.stdin.close();need(child.wait()==0,"failed to preserve native payload")

def manifest(path,store=None):
    names=None; members={}; symbols=[]; meta={}; recipe=[]
    with path.open("rb") as stream:
        need(stream.read(8)==b"!<arch>\n","not an ordinary archive")
        while header:=stream.read(60):
            need(len(header)==60 and header[58:]==b"`\n","invalid archive header")
            key=header[:16].decode("ascii").strip();size=int(header[48:58]);remaining=size
            start=stream.tell()
            if key=="//":
                need(names is None and size<4<<20,"invalid GNU long-name table");names=stream.read(size)
                need(len(names)==size,"partial archive name table")
                record=[hashlib.sha256(names).hexdigest(),size]
            else:
                if key.startswith("/") and key[1:].isdecimal():
                    need(names is not None,"missing archive name table")
                    off=int(key[1:]);end=names.find(b"/\n",off)
                    need(0<=off<end,"invalid long archive member")
                    key=names[off:end].decode("utf8")
                special=key in ("/","/SYM64/")
                if not special:key=key.removesuffix("/")
                head=stream.read(min(remaining,16));remaining-=len(head);h=hashlib.sha256(head)
                while remaining:
                    part=stream.read(min(1<<20,remaining));need(part,"truncated archive payload")
                    h.update(part);remaining-=len(part)
                record=[h.hexdigest(),size]
                if special:symbols.append(record)
                else:
                    need(Path(key).name==key and key not in members and key not in meta,"duplicate or escaped archive member")
                    if key.endswith(".o"):
                        need(head.startswith(b"\x7fELF\x02\x01"),("not a native ELF64 LE CGU",key))
                        members[key]=record
                    else:meta[key]=record
            if store is not None:
                store_member(stream,start,size,record[0],store)
                recipe.append([header.hex(),record[0]])
            if size%2:need(stream.read(1)==b"\n","invalid archive padding")
    need(members and "lib.rmeta" in meta and set(meta)<={"lib.rmeta","lib.rmeta-link"} and symbols,
         "missing native, Rust metadata or symbol index")
    parsed={"objects":members,"metadata":meta,"symbol_indices":symbols}
    return (parsed,recipe) if store is not None else parsed

def stable(archive):
    result={}
    for full,row in archive["objects"].items():
        match=re.fullmatch(r"[A-Za-z0-9_]+-[0-9a-f]{16}\.([a-z0-9]+)\.[a-z0-9]+\.rcgu\.o",full)
        need(match,("unregistered archive member format",full))
        key=match[1]+".o";need(key not in result,("duplicate native CGU",key));result[key]=row
    return result

def compare_objects(reference,current):
    old,new=stable(reference),stable(current)
    return {"missing":sorted(old.keys()-new.keys()),"added":sorted(new.keys()-old.keys()),
            "changed":sorted(k for k in old.keys()&new.keys() if old[k]!=new[k])}

def current_session(state,owner,prior=None):
    choices={p.parent for p in state.rglob("dep-graph.bin") if p.parent.parent.name.startswith(owner+"-")
             and p.parent.name.startswith("s-") and not p.parent.name.endswith("-working")}
    if prior and choices-{prior}:choices.discard(prior)
    need(len(choices)==1,("ambiguous completed incremental session",owner,sorted(str(p) for p in choices)))
    return choices.pop()

def inode(file):
    s=file.stat()
    return [s.st_dev,s.st_ino,s.st_size]

def old_files(stack,session):
    rows={}
    for path in sorted(session.glob("*.o")):
        f=stack.enter_context(path.open("rb"));s=inode(path);h=hashlib.file_digest(f,"sha256").hexdigest();f.seek(0)
        rows[path.name]=(f,s,h)
    need(rows,"no native incremental objects");return rows

def observe_objects(session,old,rlib):
    paths={p.name:p for p in session.glob("*.o")};matches={}
    records={}
    for name in sorted(set(paths)|set(old)):
        prior=old.get(name);path=paths.get(name)
        a=prior[1] if prior else None;h0=prior[2] if prior else None
        if prior:
            f=prior[0];f.seek(0)
            need(hashlib.file_digest(f,"sha256").hexdigest()==h0,"held OLD file was mutated")
        b=inode(path) if path else None
        if path:
            with path.open("rb") as f:h1=hashlib.file_digest(f,"sha256").hexdigest()
            matches[name]=[h1,b[2]]
        else:h1=None
        kept=bool(a and b and a[:2]==b[:2])
        need(not kept or (a[2]==b[2] and h0==h1),"reused inode with different native bytes")
        records[name]=dict(before=a,after=b,before_sha256=h0,after_sha256=h1,retained=kept)
    need(matches==stable(rlib),
         ("incremental session does not match all archived CGU bytes",len(matches),len(rlib["objects"])))
    return records
