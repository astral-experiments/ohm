"""Run one isolated ordinary Ruff history on the currently authenticated compiler."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/"rmeta-reader"))
import decode
from seed import PIN, FILE, git
from subjects import need, sha, put
CMD=["cargo","+ohm","check","-p","ruff_db","--lib","--locked","--offline","-j4","--message-format=json"]
PHASES=[("A0","A"),("A0r","A"),("B","B"),("Br","B"),("A1","A"),("A1r","A"),("Bempty","B"),("Bemptyr","B")]
CRATES=("ruff_notebook","ruff_db")

def pack(p,b):
    with p.open("xb") as f:f.write(gzip.compress(b,compresslevel=3,mtime=0))

def cas(folder,data):
    h=hashlib.sha256(data).hexdigest();p=folder/(h+".gz")
    if not p.exists():pack(p,data)
    return h

def metadata(folder,name,path):
    raw=path.read_bytes(); t,g,root=decode.rmeta(raw)
    need(root["owner"]==("str",name),"foreign metadata issuer")
    lookup,_=decode.definitions(raw,t,name)
    hashes=decode.fingerprints(raw,t["local"]);rows={lookup(i)[-1]:(lookup(i)[0],h) for i,(_,h) in hashes.items()}
    need(len(rows)==len(hashes),"definition collision")
    compact=json.dumps(rows,sort_keys=True,separators=(",",":")).encode()
    return {"cas":cas(folder,raw),"size":len(raw),"path":str(path),"inode":[path.stat().st_dev,path.stat().st_ino],
            "issuer":name,"stamp":root["stamp"],"filename":root["filename"],"stable_id":root["stable_id"],"roster":root["roster"],
            "public":root["fields"]["self","public"][1],"private":root["fields"]["self","private"][1],"global":raw[g:g+16].hex(),
            "foreign":[[k[1],k[2],v[1]] for k,v in root["fields"].items() if k[0]=="dep"],
            "defs":cas(folder,compact),"def_count":len(rows)}

def store(env):
    seen={}
    for key in ("CARGO_TARGET_DIR","CARGO_BUILD_BUILD_DIR"):
        top=Path(env[key])
        for dir,dirs,files in os.walk(top,followlinks=False):
            paths=[Path(dir), *[Path(dir)/n for n in files], *[Path(dir)/n for n in dirs if (Path(dir)/n).is_symlink()]]
            for path in paths:
                stat=path.lstat();idx=(stat.st_dev,stat.st_ino);size=stat.st_blocks*512
                need(seen.setdefault(idx,size)==size,"same inode/other allocation")
    return {"allocated":sum(seen.values()),"inodes":len(seen)}

def trace_call(dest,argv,env,src,syscalls):
    need(not dest.exists(),"duplicate trace root");dest.mkdir()
    temporary=dest/"pids";temporary.mkdir();prefix=temporary/"pid"
    cmd=["strace","-ff","-qq","-yy","-s","65535","-e","trace="+syscalls,"-e","status=successful","-o",str(prefix),*map(str,argv)]
    r=subprocess.run(cmd,cwd=src,env=env,capture_output=True)
    files={t.name.removeprefix("pid."):t.read_text(errors="backslashreplace") for t in temporary.iterdir() if t.stat().st_size}
    payload=json.dumps(files,sort_keys=True,separators=(",",":")).encode();pack(dest/"trace.json.gz",payload)
    for t in temporary.iterdir():t.unlink()
    temporary.rmdir()
    return r,files

def exec_events(folder):
    """Reconstruct complete kernel EXEC events independently of syscall-string decoding."""
    roots=[];tasks={};edges={};exits={};serials={}
    for line in (folder/"tasks.tsv").read_text().splitlines():
        label,*values=line.split("\t");pid,*rest=map(int,values)
        if label=="root":need(not rest,"root fields");roots.append(pid)
        elif label=="task":need(pid not in tasks and len(rest)==2,"duplicate task");tasks[pid]=rest[0]
        elif label=="exit":need(pid not in exits and len(rest)==2,"duplicate exit");exits[pid]=rest
        elif label=="spawn":
            child,event=rest;need(child not in edges and event in (1,2,3),"invalid birth");edges[child]=pid
        elif label=="exec":
            idx,=rest;need(idx not in serials,"duplicate exec");serials[idx]=pid
        else:raise ValueError(label)
    root,=roots
    need(set(tasks)==set(exits)==set(edges)|{root} and exits[root]==[0,0],"incomplete native ancestry/exit")
    for pid,tgid in tasks.items():
        seen={pid}
        while pid!=root:
            pid=edges[pid];need(pid not in seen,"cycle");seen.add(pid)
        need(tgid in seen,"unrelated thread leader")
    need(list(map(int,(folder/"samples.tsv").read_text().split()))==[0,root,0,0,-1,0,0,0],"structural collector counted work")
    events=[]
    for line in (folder/"exec.tsv").read_text().splitlines():
        fields=line.split("\t",6);serial,pid,kind,enrolled,dev,ino=map(int,fields[:6]);p=Path(fields[6])
        need(p.is_absolute() and pid in tasks and serials[serial]==pid and serial==len(events)+1 and kind==enrolled==0,"unbound exec event")
        raw=(folder/f"args-{serial:04d}").read_bytes()
        need(len(raw)>1 and raw[-1]==0,"incomplete argv")
        events.append((pid,p,[dev,ino],list(map(os.fsdecode,raw[:-1].split(b"\0")))))
    need(len(serials)==len(events) and {f.name for f in folder.glob("args-*")}=={f"args-{n:04d}" for n in serials},"dropped argv/event")
    return events,exits

def native_roster(folder,sdk):
    compilers=[];linkers=[];generators=[]
    events,exits=exec_events(folder)
    for pid,exe,stat,a in events:
        name=exe.name
        need(name!="rustdoc","a Rustdoc process executed on this check")
        if name=="rustc" and "--crate-name" in a and any(s=="--emit" or s.startswith("--emit=") for s in a):
            n=a[a.index("--crate-name")+1]
            if n!="___":
                st=(sdk/"bin/rustc").stat()
                need(stat==[st.st_dev,st.st_ino] and exits[pid]==[0,0],"foreign or failed rustc frontend")
                compilers.append([pid,n])
        if name.startswith(("ld.","wild")) or name in {"ld","rust-lld"}:
            if "-o" in a:
                st=exe.stat();actual=sha(exe)
                need(stat==[st.st_dev,st.st_ino] and exits[pid]==[0,0] and actual=="0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5",("unregistered or failed GNU linker",exe,actual))
                linkers.append([pid,str(exe),actual])
        if name.startswith("build-script-"):generators.append([pid,str(exe)])
    return {"rustcs":compilers,"linkers":linkers,"generators":generators,"execs":len(events),"tasks":len(exits),"nonzero_children":{str(pid):v for pid,v in exits.items() if v!=[0,0]}}

def tree_call(label,command,src,env,sdk,plain):
    folder=label/"exec";folder.mkdir()
    # These four inert regular files keep the collector in a pure all-exec topology mode.
    # The native roster is independently recovered from every actual executable and inode.
    selectors=[HERE/n for n in ("PLAN.md","PLAN-v1.md","db-accessor.rs","db-neighbor.rs")]
    need(all(p.is_file() and not os.access(p,os.X_OK) for p in selectors),"executable selector")
    run=subprocess.run([plain.parent/"tree",folder,"topology",*selectors,*command],cwd=src,env=env,capture_output=True)
    if run.returncode:
        pack(label/"collector-stderr.gz",run.stderr);raise ValueError(("native collector",run.returncode,run.stderr[-600:]))
    roster=native_roster(folder,sdk)
    with tarfile.open(label/"exec.tar.gz","x:gz",compresslevel=2) as tar:
        for f in sorted(folder.iterdir()):
            need(f.is_file() and not f.is_symlink(),"unexpected collector entry");tar.add(f,arcname=f.name,recursive=False)
    shutil.rmtree(folder)
    return run,roster

def clients(log,src,env,prs,arts,sdk,driver,kind,casdir):
    dirs={str(Path(f).parent) for a in arts for f in a["filenames"]}
    for k in ("CARGO_TARGET_DIR","CARGO_BUILD_BUILD_DIR"):
        for pattern in ("*.rmeta","lib*.so"):dirs.update(str(p.parent) for p in Path(env[k]).rglob(pattern))
    answered={}
    for name in ("db-accessor","db-neighbor"):
        path=src.parent/(name+".rs");dest=src.parent/"reader.rmeta"
        if dest.exists():dest.unlink()
        cmd=["rustc","+ohm",str(path),"--crate-name","db_case","--edition=2024","--crate-type=lib","--emit=metadata","--error-format=json",
             "--extern","ruff_db="+prs["ruff_db"]["path"],*["-Ldependency="+d for d in sorted(dirs)],"-o",str(dest)]
        folder=log/name
        process,traces=trace_call(folder,cmd,env,src,"open,openat,execve,execveat")
        pack(folder/"stdout.gz",process.stdout);pack(folder/"stderr.gz",process.stderr)
        bad=name=="db-accessor" and kind=="A"
        need(process.returncode==int(bad),"wrong real third-crate exit: "+name)
        if bad:
            ds=[json.loads(l) for l in process.stderr.splitlines() if l.startswith(b"{")]
            diag,=[d for d in ds if d.get("code")]
            target,=[s for s in diag["spans"] if s["is_primary"]]
            need(diag["code"]["code"]=="E0599" and "no method named `metadata`" in diag["message"] and ".metadata()" in target["text"][0]["text"] and not dest.exists(),"wrong E0599")
        else:need(dest.is_file() and not process.stdout and not process.stderr,"invalid success witness")
        opens={"driver":[],**{n:[] for n in CRATES}}
        for pid,trace in traces.items():
            for line in trace.splitlines():
                if line.startswith(("open(","openat(")) and "O_RDONLY" in line:
                    m=re.search(r'= \d+<([^<>]+)>$',line)
                    if not m:continue
                    physical=Path(m[1]);key=next((k for k in CRATES if physical.name.startswith("lib"+k+"-") and physical.name.endswith(".rmeta")),None)
                    if physical.name==Path(driver).name:key="driver"
                    if key:
                        need(sha(physical)==(sha(sdk/driver) if key=="driver" else prs[key]["cas"]),("unmatched reader FD",key))
                        opens[key].append([pid,line])
        need(all(opens.values()),("missing physical reader input",name,{k:len(v) for k,v in opens.items()}))
        answered[name]={"argv":cmd,"exit":process.returncode,"opens":opens,"output":None if bad else cas(casdir,dest.read_bytes())}
        put(folder/"result.json",answered[name])
    return {k:{"exit":v["exit"],"output":v["output"]} for k,v in answered.items()}

def stage(out,work,src,env,name,kind,role,lane,sdk,driver,plain,casdir):
    label=out/"raw"/name;label.mkdir(parents=True)
    need((b"pub fn metadata(" in (src/FILE).read_bytes())==(kind=="B"),"wrong source")
    need(git(src,"diff","--name-only").decode().splitlines()==([FILE] if kind=="B" else []),"extra Ruff edit")
    if lane=="whole":
        result=subprocess.run([plain,label/"pmu.json",*CMD],cwd=src,env=env,capture_output=True)
        p=json.loads((label/"pmu.json").read_text())
        need(p["code"]==p["event_errno"]==0 and p["instructions"]>0 and 0<p["running"]<=p["enabled"] and p["running"]*1000>=995*p["enabled"],"unsupported/partial PMU")
        counts=p["instructions"];native=None
    else:
        result,native=tree_call(label,CMD,src,env,sdk,plain);counts=None
    pack(label/"stdout.gz",result.stdout);pack(label/"stderr.gz",result.stderr)
    put(label/"invocation.json",{"cmd":CMD,"cwd":str(src),"env":env,"observed":"ptrace" if lane=="structural" else [str(plain),str(label/"pmu.json")],"code":result.returncode,"source":sha(src/FILE)})
    need(result.returncode==0 and b"internal compiler error" not in result.stderr,(name,result.returncode,result.stderr[-800:]))
    rows=[json.loads(l) for l in result.stdout.splitlines()];need(rows[-1]=={"reason":"build-finished","success":True},"Ruff Cargo terminal")
    arts=[a for a in rows if a["reason"]=="compiler-artifact"];need(len(arts)==171,"unexpected complete Ruff graph")
    prs={}
    for n in CRATES:
        row,=[a for a in arts if a["target"]["name"]==n and a["target"]["kind"]==["lib"]]
        path,=[Path(f) for f in row["filenames"] if f.endswith(".rmeta")]
        prs[n]=metadata(casdir,n,path)
    reader=clients(label,src,env,prs,arts,sdk,driver,kind,casdir)
    roster=sorted((a["package_id"],a["target"]["name"],a["target"]["kind"],a["features"]) for a in arts)
    dirty=sorted([a["target"]["name"],a["target"]["kind"]] for a in arts if not a["fresh"])
    data={"role":role,"lane":lane,"phase":name,"state":kind,"storage":store(env),"counts":counts,"roster":roster,"dirty":dirty,"products":prs,"clients":reader,"native":native,"source":sha(src/FILE)}
    put(label/"result.json",data)
    return data
