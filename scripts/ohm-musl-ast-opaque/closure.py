"""Authenticate ordinary Rust graph inputs and restore a physically independent native consumer closure."""
import ast
import collections
import contextlib
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import subprocess
import tarfile
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/"ohm-musl-ast-hardware"))
from clocked import require, save, file_sha, sha

FILE_END = re.compile(r"\s+=\s+\d+<(/[^<>]+)>$")
FORK = re.compile(r"^(?:clone3?|fork|vfork)\(.*\)\s+=\s+(\d+)$")
FORMATS = (".rmeta", ".rlib", ".so", ".a", ".o")
INPUT_EXT = (".rs", ".expr", ".rmeta", ".rlib", ".a", ".so", ".json", ".toml")


def dest(key, roots):
    for name, root in roots.items():
        if key.is_relative_to(root):
            return name + "/" + str(key.relative_to(root))
    return None


def stable(path):
    before = path.stat()
    require(stat.S_ISREG(before.st_mode), ("non-file input",path))
    h = file_sha(path)
    after = path.stat()
    require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns) ==
            (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns), ("changing input",path))
    return {"sha256":h,"bytes":before.st_size,"mode":stat.S_IMODE(before.st_mode),"dev":before.st_dev,"ino":before.st_ino}


def trace_lines(path):
    waiting = None
    lines=path.read_text(errors="backslashreplace").splitlines()
    tail=lines[-2:]==["???( <unfinished ...>","+++ exited with 0 +++"]
    if tail:
        # Linux strace can attach to a dying CLONE_THREAD after the task's last syscall.
        # No successful open is reported. The returned child TID and full original are checked below.
        lines=lines[:-2]
    for line in lines:
        if line.endswith("<unfinished ...>"):
            require(waiting is None,("nested unfinished",line));waiting=line.removesuffix("<unfinished ...>");continue
        if line.startswith("<... ") and " resumed>" in line:
            require(waiting is not None and waiting.startswith(line[5:line.index(" resumed>")]+"("),"wrong resumed system call")
            line=waiting+line.split(" resumed>",1)[1];waiting=None
        yield line
    require(waiting is None,("incomplete system call",path))
    if tail:yield "QA-UNKNOWN-EXITED-THREAD"


def positive_open(line):
    if not line.startswith(("openat(","openat2(")):return None
    m=FILE_END.search(line)
    if not m or "O_RDONLY" not in line or "O_DIRECTORY" in line or "O_PATH" in line:return None
    return Path(m[1])


def observe(r,label,work,out,env,cmd,stamps):
    place=out/label;place.mkdir();logs=work/(label+"-full-opens");logs.mkdir()
    call=["strace","-ff","-q","-yy","-s","262144","-e","trace=execve,execveat,clone,clone3,vfork,fork,openat,openat2","-o",str(logs/"proc"),*cmd]
    run=subprocess.run(call,cwd=r.R,env=env,capture_output=True,timeout=1500)
    r.census.blob(place/"stdout.gz",run.stdout);r.census.blob(place/"stderr.gz",run.stderr)
    save(place/"command.json",{"argv":call,"exit":run.returncode,"stdout":sha(run.stdout),"stderr":sha(run.stderr)})
    with tarfile.open(place/"execs-and-opens.tar.gz","w:gz",compresslevel=2) as z:
        for p in sorted(logs.iterdir()):z.add(p,arcname=p.name,recursive=False)
    require(run.returncode==0,("ordinary command failed",label,run.stderr[-1200:]))
    messages=[json.loads(l) for l in run.stdout.splitlines()]
    k=r.census.qualify.native(logs,r.R);save(place/"kernel.json",k)
    require(messages[-1]=={"reason":"build-finished","success":True} and k["cargo"][0]["terminal"]==[0] and all(x["terminal"]==[0] for x in k["rustcs"]),"native terminal")
    return place,messages,k,inputs(r,k,logs,place,stamps)


def inputs(r,k,logs,place,stamps):
    rustcs={int(x["pid"]):x for x in k["rustcs"]};parents={};seen={};raws={};threads=collections.defaultdict(set);thread_clones=set();exited_unknown=set();created_by={};writes=collections.defaultdict(set)
    for p in logs.iterdir():
        tid=int(p.suffix[1:]);paths=set();creates=set()
        for line in trace_lines(p):
            m=FORK.fullmatch(line)
            if m:
                child=int(m[1]);require(parents.setdefault(child,tid)==tid,"ambiguous native child")
                if "CLONE_THREAD" in line:thread_clones.add(child)
            if line=="QA-UNKNOWN-EXITED-THREAD":exited_unknown.add(tid)
            created=FILE_END.search(line) if (line.startswith(("openat(","openat2(")) and "O_CREAT" in line) else None
            if created:creates.add(Path(created[1]))
            f=positive_open(line)
            if f:paths.add(f)
        raws[tid]=paths;created_by[tid]=creates
    for tid,paths in raws.items():
        owner=tid;trail=set()
        while owner not in rustcs and owner in parents:
            require(owner not in trail,"cyclic process tree");trail.add(owner);owner=parents[owner]
        if owner in rustcs:seen.setdefault(owner,set()).update(paths);threads[owner].add(tid);writes[owner].update(created_by[tid])
    require(set(seen)==set(rustcs) and exited_unknown<=thread_clones,("lost rustc or unowned exiting thread",exited_unknown-thread_clones))
    live={};units={};other=collections.Counter()
    for pid,row in rustcs.items():
        argv=row["argv"];accepted=[];ambient=[];temporary=[]
        for p in sorted(seen[pid]):
            if str(p).startswith(("/proc/","/dev/","/sys/")):ambient.append(str(p));continue
            if not p.is_file():
                out=Path(argv[argv.index("--out-dir")+1])
                tmp_name=((re.fullmatch(r"rustc[a-zA-Z0-9]{6}",p.parent.name) and p.name in ("lib.rmeta","lib.rmeta-link")) or
                          (re.fullmatch(r"rmeta[a-zA-Z0-9]{6}",p.parent.name) and p.name in ("full.rmeta","stub.rmeta")))
                own_tmp=(p in writes[pid] and p.parent.parent==out and tmp_name)
                require(p.is_dir() or own_tmp or (p.suffix not in (".rs",".expr",".rlib",".rmeta") and (str(p).endswith(" (deleted)") or str(p).startswith(("/tmp/",str(r.W)+"/",str(place.parents[2])+"/")))),
                        ("unexpected missing compiler input",row["crate"],p))
                temporary.append({"path":str(p),"same_compiler_created":bool(own_tmp)});continue
            before=p.stat();key=(str(p),before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)
            st=stamps.get(key)
            if st is None:st=stamps[key]=stable(p)
            live[str(p)]=st;accepted.append(str(p))
        declared={}
        for flag in r.census.flags(argv,"--extern"):
            if "=" in flag:
                n,v=flag.split("=",1);f=Path(v)
                require(f.is_absolute() and f.is_file(),("declared upstream missing",row["crate"],f))
                declared[n]={"path":str(f),"actual_input":stable(f),"seen_as":sorted(str(u) for u in seen[pid] if u==f or (u.parent==f.parent and u.stem==f.stem and u.suffix in FORMATS))}
        require(any(n.endswith(".rs") for n in accepted),("full rustc without physical Rust source",row["crate"],pid,len(accepted)))
        units[str(pid)]={"name":row["crate"],"command":argv,"thread_and_child_pids":sorted(threads[pid]),"opened_regular":accepted,"declared_externs":declared,"ephemeral":temporary,"kernel_objects":ambient}
        other.update(p.suffix for p in seen[pid])
    report={"unknown_entry_then_zero_exit":sorted(exited_unknown),"units":units,"regular_files":live,"format_counts":dict(other),"parent_of":{str(n):p for n,p in parents.items()},"sha256_full_kernel":file_sha(place/"execs-and-opens.tar.gz")}
    save(place/"actual-inputs.json",report)
    return report


def snapshot(r,cold,actual,messages,training,store,report,consumer_dir):
    roots={n:r.W/n for n in ("target","shared")};files=set();owner,search=training
    require(all(p.is_dir() and not p.is_symlink() for p in roots.values()),"private active roots")
    files.update([owner,owner.with_suffix(".rmeta")])
    dirs=[]
    for a in search:
        d=Path(a.split("=",1)[1] if "=" in a else a)
        require(d.is_absolute() and any(d.is_relative_to(root) for root in roots.values()),("unexpected native search scope",d))
        if d.is_dir():
            dirs.append(str(d))
            files.update(f for f in d.iterdir() if f.is_file() and f.name.endswith(FORMATS))
    for m in messages:
        if m.get("reason")=="compiler-artifact":
            for name in m["filenames"]:
                p=Path(name);require(p.is_file() and dest(p,roots),("typed artifact",p));files.add(p)
    for src in (cold,actual):
        for x in src["units"].values():
            for v in x["declared_externs"].values():files.add(Path(v["path"]))
        for n in src["regular_files"]:
            f=Path(n)
            if dest(f,roots) and f.is_file() and f.name.endswith(INPUT_EXT):files.add(f)
    # Also include every actual successful native Cargo-store read of the valid and three invalid independent clients.
    for raw in sorted(consumer_dir.glob("*.opens.gz")):
        for b in gzip.decompress(raw.read_bytes()).splitlines():
            l=re.sub(r"^\s*\d+\s+","",b.decode(errors="backslashreplace"));f=positive_open(l)
            if f is not None and dest(f,roots) and f.is_file():files.add(f)
    store.mkdir(exist_ok=True,parents=True);items={}
    for f in sorted(files):
        key=dest(f,roots);require(key and f.is_file() and not f.is_symlink(),("unowned source",f))
        m=stable(f);copy=store/m["sha256"]
        if not copy.exists():shutil.copyfile(f,copy);copy.chmod(0o400)
        require(not copy.samefile(f) and file_sha(copy)==m["sha256"],"independent escrow")
        items[key]=m
    result={"roots":{k:str(v) for k,v in roots.items()},"owner":dest(owner,roots),"search":search,"seen_search_dirs":dirs,"files":items,"independent_content_objects":len({m["sha256"] for m in items.values()}),"unit_ids":sorted(cold["units"])}
    require(len(cold["units"])==39 and result["owner"] in items,"matching complete graph")
    save(report/"matching-closure.json",result)
    return result


@contextlib.contextmanager
def restore(frame,store):
    roots={n:Path(v) for n,v in frame["roots"].items()};created=[]
    try:
        for p in roots.values():
            require(not p.exists() and not p.is_symlink(),"original output roots must be parked");p.mkdir();created.append(p)
        for p in frame["seen_search_dirs"]:Path(p).mkdir(parents=True,exist_ok=True)
        evidence={}
        for name,m in frame["files"].items():
            a,rel=name.split("/",1);p=roots[a]/rel
            require(not Path(rel).is_absolute() and ".." not in Path(rel).parts and not p.exists() and p.parent.resolve().is_relative_to(roots[a]),"fresh independent path")
            p.parent.mkdir(parents=True,exist_ok=True);original=store/m["sha256"]
            shutil.copyfile(original,p);p.chmod(m["mode"]);new=stable(p)
            require(new["sha256"]==m["sha256"] and new["bytes"]==m["bytes"] and (new["dev"],new["ino"])!=(m["dev"],m["ino"]) and not p.samefile(original),"restored graph aliases original or escrow")
            evidence[name]=new
        a,rel=frame["owner"].split("/",1)
        yield roots[a]/rel,frame["search"],evidence
    finally:
        for p in created:
            require(p.is_dir() and not p.is_symlink(),"disposable private restore");shutil.rmtree(p)


def provider(frame):
    matches={}
    for key,m in frame["files"].items():
        p=Path(key)
        if re.fullmatch(r"libchar_str-[0-9a-f]{16}\.(rmeta|rlib)",p.name):
            group=p.suffix;v=matches.setdefault(group,{"paths":[],"sha256":m["sha256"]})
            require(v["sha256"]==m["sha256"],"conflicting providers in one actual search closure")
            v["paths"].append(key)
    require(set(matches)=={".rmeta",".rlib"},"one complete logical char_str")
    return matches


def swap(index, alternate, pool, consumer, owner, search, scratch, directory, env, frame):
    """Substitute both filename representations of just one logical, genuinely good foreign crate."""
    local=provider(index);foreign=provider(alternate)
    for ext in local:require(local[ext]["sha256"]!=foreign[ext]["sha256"],("same char_str provider across real graphs",ext))
    changed={}
    for ext,entry in local.items():
        for key in entry["paths"]:
            n,tail=key.split("/",1);p=Path(index["roots"][n])/tail
            require(p.is_file() and not p.is_symlink() and file_sha(p)==entry["sha256"],"owned restored provider")
            shutil.copyfile(pool/foreign[ext]["sha256"],p);require(file_sha(p)==foreign[ext]["sha256"],"foreign substitution")
            changed[str(p)]=[entry["sha256"],foreign[ext]["sha256"]]
    try:
        rejected=consumer.wrong_provider(owner,search,scratch,directory,env,frame)
        raw=gzip.decompress((directory/"kernel.gz").read_bytes()).splitlines()
        opened=[p for p in changed if consumer.trace_open(raw,Path(p))]
        require(opened and rejected["code"]=="E0463","foreign provider was not physically opened and rejected")
    finally:
        for p,(old,_) in changed.items():
            shutil.copyfile(pool/old,p);require(file_sha(Path(p))==old,"restored original provider")
    receipt={"rejected":rejected,"actually_opened_foreign":opened,"changed_native_files":changed,"logical_dependency_count":1,"restored":True}
    save(directory/"one-substitution.json",receipt)
    return receipt
