"""Collect the kernel-confirmed destination of every native object rewrite off the hardware counter."""
import ast
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
from unittest.mock import patch

from common import need, save

QUOTED = re.compile(r'"(?:\\.|[^"\\])*"')
NAME=re.compile(r'(?P<owner>[a-z][a-z0-9_]*)-(?P<crate>[0-9a-f]{16})\.(?P<cgu>[a-z0-9]{25})(?:\.(?P<nonce>[a-z0-9]{7}))?\.rcgu\.o$')
EXTRA=("rename","renameat","renameat2")


@contextmanager
def add_file_calls(guards, dest):
    original=guards.run
    seen=[]
    def call(argv,cwd,env,where,*args,**kwargs):
        if where!=dest or argv[0]!="/usr/bin/strace":
            return original(argv,cwd,env,where,*args,**kwargs)
        need(not seen and len([x for x in argv if x.startswith("trace=")])==1 and "--" in argv,"unexpected immutable tracing entry")
        i=next(i for i,x in enumerate(argv) if x.startswith("trace="))
        more=list(EXTRA)
        # Full cold and clean acquisitions keep the existing stdin proof. Limit file opens to dirty work.
        if "read=0" not in argv and "openat" not in argv[i].split(","):
            more+=["openat","openat2"]
        changed=argv[:]
        changed[i]+=","+",".join(more)
        seen.append(changed)
        save(where/"effective-file-trace.json",{"registered_observer":argv,"actual_observer":changed,
             "ordinary":changed[changed.index("--")+1:]})
        return original(changed,cwd,env,where,*args,**kwargs)
    try:
        with patch.object(guards,"run",call):
            yield
    finally:
        if not seen and (dest/"result.json").exists():
            raise ValueError("file observer never ran")


def identity(tid,parents,compilers,executions):
    seen=set()
    while tid not in seen:
        if tid in compilers:return compilers[tid]
        if tid in executions:return None
        seen.add(tid)
        if tid not in parents:return None
        tid=parents[tid]
    raise ValueError("cycle in real kernel ancestry")


def classify(line):
    if not line.rstrip().endswith("= 0") or not line.startswith(("rename(","renameat(","renameat2(")):
        return None
    paths=[ast.literal_eval(v) for v in QUOTED.findall(line)]
    if not paths or not any("ohm-placement-" in str(p) for p in paths):return None
    need(len(paths)==2,"unsupported rename encoding")
    source,dest=map(Path,paths)
    need(source.is_absolute() and dest.is_absolute() and source.name=="object" and source.parent.parent==dest.parent and
         re.fullmatch(r"ohm-placement-[A-Za-z0-9_.-]+",source.parent.name) and dest.name.endswith(".rcgu.o"),
         ("unmodeled source-placement publication",line))
    return source,dest


def read(dest,sdk):
    k=json.loads((dest/"kernel.json").read_bytes())
    parents={int(c):p for c,p in k["tree"]["parents"].items()}
    compiled={r["pid"]:r for r in k["compilers"] if r["kind"]=="full"}
    executions={r["pid"] for r in k["tree"]["processes"] if r["path"]!=str(sdk/"bin/rustc")}
    renames=[]; emitted=[]
    for file in sorted((dest/"trace").glob("exec.*")):
        tid=int(file.suffix[1:])
        owner=identity(tid,parents,compiled,executions)
        for raw in file.open():
            if "ohm-placement-" in raw and raw.startswith(("rename(","renameat(","renameat2(")):
                pair=classify(raw)
                if pair:
                    need(owner is not None and Path(owner["exec"]).samefile(sdk/"bin/rustc"),"rename outside physical compiler lineage")
                    src,dst=pair
                    match=NAME.fullmatch(dst.name)
                    need(match is not None and match["owner"]==owner["name"],("unknown accepted native CGU name",dst,owner["name"]))
                    renames.append({"pid":owner["pid"],"tid":tid,"owner":owner["name"],"cgu":match["cgu"],
                                   "source":str(src),"destination":str(dst),"syscall_sha256":hashlib.sha256(raw.encode()).hexdigest()})
            elif owner and raw.startswith(("openat(","openat2(")) and ".rcgu.o" in raw and "O_CREAT" in raw and ("O_WRONLY" in raw or "O_RDWR" in raw) and not re.search(r"= -1\b",raw):
                strs=QUOTED.findall(raw)
                if not strs:continue
                filename=Path(ast.literal_eval(strs[0]))
                match=NAME.fullmatch(filename.name)
                if match and match["owner"]==owner["name"]:
                    emitted.append({"pid":owner["pid"],"tid":tid,"owner":owner["name"],"cgu":match["cgu"],"path":str(filename),
                                    "syscall_sha256":hashlib.sha256(raw.encode()).hexdigest()})
    sets={k for k in ((r["pid"],r["cgu"]) for r in renames)}
    need(len(sets)==len(renames),"duplicate accepted native CGU publication")
    return {"renames":renames,"ordinary_native_object_writes":emitted,"raw_kernel_tree_sha256":hashlib.sha256((dest/"kernel.json").read_bytes()).hexdigest()}


def inc_root(case,owner):
    comp=json.loads((case/"kernel.json").read_bytes())["compilers"]
    selected=[r for r in comp if r["kind"]=="full" and r["name"]==owner]
    need(len(selected)==1,"missing unique real root compilation")
    args=selected[0]["argv"]
    dirs=[v.split("=",1)[1] for i,v in enumerate(args) if (i and args[i-1]=="-C" and v.startswith("incremental="))]
    need(len(dirs)==1 and Path(dirs[0]).is_absolute() and Path(dirs[0]).is_dir(),"wrong literal incremental directory")
    return Path(dirs[0])
