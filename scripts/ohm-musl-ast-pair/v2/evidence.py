"""Read the actual Cargo records and linker process tree for one isolated musl build."""
import ast
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

HARD = "/dev/null/ohm-untracked-relink-inputs"
V1 = "/dev/null/ohm-recheck-dependent-links"
V2 = V1 + "-v2"
MARKERS = {HARD, V1, V2}
TARGET = "x86_64-unknown-linux-musl"
APP = "ohm_v2_app"
PRODUCER = "ohm_v2_producer"
LIB = "libohm_musl_v2_choice.a"
EXEC = re.compile(r'^execve\(("(?:[^"\\]|\\.)*"), (\[.*\]), .*\)\s+= 0$')
EXECAT = re.compile(r'^execveat\([^,]+, ("(?:[^"\\]|\\.)*"), (\[.*\]), .*\)\s+= 0$')
CLONE = re.compile(r'^(?:clone3?|fork|vfork)\(.*\)\s+= ([1-9][0-9]*)$')
LD = re.compile(r'^(?:(?:x86_64[^/]*-)?ld(?:\.(?:bfd|lld|gold|mold))?|rust-lld|lld|wild(?:-ld)?|mold)$')

def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")

def blob(path, data):
    path.write_bytes(gzip.compress(data, mtime=0, compresslevel=3))

def fid(p):
    s = p.stat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns]

def lines(raw):
    pending = {}
    for original in raw.splitlines():
        stamp,sep,line=original.partition(" ")
        assert sep and re.fullmatch(r"[0-9]+\.[0-9]+", stamp),original
        if line.endswith("<unfinished ...>"):
            name = line.partition("(")[0]
            assert name not in pending
            pending[name] = line.removesuffix("<unfinished ...>")
        elif m := re.match(r"^<\.\.\. (\w+) resumed>(.*)$", line):
            yield stamp, pending.pop(m[1]) + m[2]
        else:
            yield stamp,line
    assert not pending, pending

def observe(trace, cwd, sdk, roots, native):
    events, parents, fd, eno, dep_read, dep_writes, driver_open, exits = [], {}, [], [], [], [], [], {}
    thread_parent={}; native_order=[]
    for f in sorted(trace.glob("pid.*")):
        pid = int(f.suffix[1:])
        for stamp,line in lines(f.read_text(errors="strict")):
            if m := CLONE.match(line):
                child = int(m[1])
                assert child not in parents or parents[child] == pid
                parents[child] = pid
                if "CLONE_THREAD" in line:thread_parent[child]=pid
            if m := re.fullmatch(r"\+\+\+ exited with (\d+) \+\+\+", line):
                exits[pid] = int(m[1])
            if line.startswith(("execve(", "execveat(")) and re.search(r'\)\s+= 0$', line):
                m = (EXEC if line.startswith("execve(") else EXECAT).fullmatch(line)
                assert m, line
                image, argv = ast.literal_eval(m[1]), ast.literal_eval(m[2])
                assert len(argv) >= 1 and all(type(x) is str for x in argv), line
                image = Path(image)
                if not image.is_absolute():
                    image = cwd / image
                image = image.absolute()
                assert image.is_file(), image
                events.append({"pid":pid, "image":str(image), "argv":argv, "identity":fid(image)})
            elif line.startswith(("open(", "openat(", "openat2(")):
                if m := re.search(r'\)\s+= \d+<([^>]+)>$', line):
                    name = m[1]
                    if name in native:
                        fd.append([pid, name, line]); native_order.append([stamp,pid,"opened",name])
                    elif Path(name).name == "dep-lib-"+PRODUCER:
                        if "O_WRONLY" in line or "O_RDWR" in line or "O_TRUNC" in line:
                            dep_writes.append([stamp,pid,name,line])
                        if "O_RDONLY" in line:
                            dep_read.append([stamp,pid,name,line])
                    elif Path(name).name.startswith("librustc_driver-"):
                        driver_open.append([pid,name,stamp])
                elif "ENOENT" in line and any(x in line for x in native):
                    eno.append([pid,line]);native_order.extend([stamp,pid,"absent",name] for name in native if name in line)
            elif line.startswith(("rename(","renameat(","renameat2(","unlink(","unlinkat(")) and "dep-lib-"+PRODUCER in line and re.search(r'\)\s+= 0$',line):
                dep_writes.append([stamp,pid,None,line])
    def ancestor(pid, candidates):
        seen = set()
        while pid is not None:
            assert pid not in seen
            if pid in candidates:
                return pid
            seen.add(pid)
            pid = parents.get(pid)
        return None
    cargo = [e for e in events if Path(e["image"]).samefile(sdk/"bin/cargo")]
    assert len(cargo)==1 and cargo[0]["pid"] in exits
    rootpid = cargo[0]["pid"]
    def is_cargo_thread(pid):
        seen=set()
        while pid in thread_parent:
            assert pid not in seen
            seen.add(pid);pid=thread_parent[pid]
        return pid==rootpid
    compilers, scripts, linkers, targets = [], [], [], []
    for e in events:
        a = e["argv"]
        image = Path(e["image"])
        if image.samefile(sdk/"bin/rustc") and "--crate-name" in a and any(x=="--emit" or x.startswith("--emit=") for x in a):
            crate = a[a.index("--crate-name")+1]
            link = "-Zlink-only" in a or "-Zlink-only=yes" in a or any(
                x=="-Z" and y in {"link-only","link-only=yes"} for x,y in zip(a,a[1:]))
            compilers.append(e | {"crate":crate,"kind":"link-only" if link else "full"})
        if re.fullmatch(r"build[-_]script[-_]build(?:-[0-9a-f]+)?",image.name) and any(image.is_relative_to(r) for r in roots):
            scripts.append(e)
        if LD.fullmatch(image.name) and "-o" in a:
            name = a[a.index("-o")+1]
            if re.fullmatch(re.escape(APP)+r'(-[0-9a-f]+)?',Path(name).name):
                linkers.append(e | {"output":name,"sha256":sha(image)})
    for e in compilers+scripts+linkers:
        assert ancestor(e["pid"],{rootpid})==rootpid, e
    for c in compilers:
        c["provider_opens"]=sorted({path for pid,path,_ in fd if ancestor(pid,{c["pid"]}) is not None})
    for e in linkers:
        ancestors={c["pid"] for c in compilers if c["crate"]==APP}
        assert ancestor(e["pid"],ancestors) in ancestors and ancestors, e
        e["selected"]=[path for pid,path,_ in fd if ancestor(pid,{e["pid"]}) is not None]
        e["negative"]=[line for pid,line in eno if ancestor(pid,{e["pid"]}) is not None]
        e["lookup_order"]=sorted(r for r in native_order if ancestor(r[1],{e["pid"]}) is not None)
        e["exit"]=exits.get(e["pid"])
        targets.extend(e["selected"])
    return {"cargo":cargo[0],"status":exits[rootpid],"compilers":compilers,"scripts":scripts,"linkers":linkers,
            "selected":sorted(set(targets)),"dep_read":[[t,pid,n] for t,pid,n,_ in dep_read if is_cargo_thread(pid)],
            "dep_writes":dep_writes,"driver_open":driver_open,
            "provider_fd":fd,"provider_enoent":eno,"parent_pids":parents,"all_exec":events}

def encoded(body):
    at = 0
    def take(n):
        nonlocal at
        assert 0 <= n <= len(body)-at
        part = body[at:at+n]; at += n
        return part
    def uint(): return int.from_bytes(take(4),"little")
    def string(): return os.fsdecode(take(uint()))
    assert take(5)==b"\x01\0\0\0\xff"
    version=take(1)[0]
    assert version in (2,4),version
    files=[]
    for _ in range(uint()):
        kind=take(1)[0]; assert kind in (0,1)
        path=string(); cs=take(1)[0]; assert cs in (0,1)
        if cs: take(8); string()
        files.append((kind,path,cs))
    for _ in range(uint()):
        string(); present=take(1)[0]; assert present in (0,1)
        if present:string()
    marker=None
    if at<len(body):
        assert take(4)==b"LNK1"
        idx=uint(); kind,marker,cs=files[idx]
        assert kind==1 and marker in {V1,V2} and not cs
        want=bytes.fromhex(subprocess.check_output(["b3sum"],input=body[:at]).decode().split()[0])
        assert take(32)==want
    assert at==len(body)
    return {"version":version,"LNK1":marker,"markers":[p for _,p,_ in files if p in MARKERS],"inputs":files}

def raw_rule(path,body):
    rules=[s.partition(": ") for s in body.decode().splitlines() if ": " in s]
    own=[rhs for lhs,_,rhs in rules if Path(lhs).name==path.name]
    if not own:  # Cargo's single-rule export is distinct from rustc's own .d
        assert len(rules)==1
        return None
    assert len(own)==1
    checks=lambda s:[x for x in s.split() if x in MARKERS]
    all_marks=checks(rules[0][2])
    assert not checks(own[0]) and len(all_marks)<=1
    fake=[x[:-1] for x in body.decode().splitlines() if x.endswith(":") and x[:-1] in MARKERS]
    assert all_marks==fake
    return all_marks

def dep_records(roots,folder):
    rows=[]
    for root in roots:
        if not root.exists(): continue
        for p in root.rglob("*"):
            name=p.name
            if not (name in {"dep-lib-"+PRODUCER,"dep-bin-"+APP} or
                    (name.endswith(".d") and name.startswith((PRODUCER+"-",APP+"-")))):continue
            data=p.read_bytes()
            key=hashlib.sha256(data).hexdigest()
            store=folder/key
            if not store.exists(): store.write_bytes(data)
            assert sha(store)==key
            if name.startswith("dep-"):
                kind="encoded"; payload=encoded(data)
            else:
                kind="raw"; payload=raw_rule(p,data)
                if payload is None:continue
            role=PRODUCER if PRODUCER in name else APP
            rows.append({"role":role,"kind":kind,"path":str(p),"raw_sha256":key,"identity":fid(p),"parsed":payload})
    return rows
