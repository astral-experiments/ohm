#!/usr/bin/python3
"""Forward the actual GCC argv, measuring only the requested constructors Wild invocation."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
D=Path(os.environ["WILD_DIAG_JOB"]);cfg=json.loads((D/"dispatch.json").read_bytes())
argv=sys.argv
stock=cfg["stock"];matched=cfg["matched"]
if "-o" not in argv or not Path(argv[argv.index("-o")+1]).name.startswith("constructors-"):
    os.execv(stock,[argv[0],*argv[1:]])
phase=Path(os.environ["WILD_DIAG_PHASE"]);mode=os.environ["WILD_DIAG_SUBJECT"]
role=mode.split("-")[0]
assert role in ("stock","off","active")
subject=stock if role=="stock" else matched
env=os.environ.copy()
# WILD_* are ordinary linker controls; remove private launcher routing from all real subjects.
for k in list(env):
    if k.startswith("WILD_DIAG_"):del env[k]
if role=="active":
    env["OHM_WILD_OBSERVATION_CACHE"]=cfg["witness"];env["OHM_WILD_OBSERVATION_EVENTS"]=str(phase/"events")
if "-race" in mode:env["OHM_DIAGNOSTIC_BARRIER"]=str(phase/"barrier")
out=Path(argv[argv.index("-o")+1])
def fs(p):
    try:s=p.lstat()
    except FileNotFoundError:return None
    return [s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
syms=[Path(x) for x in argv if x.endswith("/symbols.o")];assert len(syms)==1
ancestry=[]
pid=os.getppid()
while pid>1 and len(ancestry)<12:
    proc=Path("/proc")/str(pid)
    path=os.readlink(proc/"exe")
    args=[os.fsdecode(s) for s in (proc/"cmdline").read_bytes().split(b"\0") if s]
    if Path(path).name in ("rustc","cargo","collect2","gcc","cc") or "gcc" in Path(path).name:
        ancestry.append({"pid":pid,"path":path,"args":args})
    if Path(path).name=="cargo":break
    # The command can contain spaces and parentheses. Linux appends state and PPID after its final closing bracket.
    pid=int((proc/"stat").read_text().rsplit(")",1)[1].split()[1])
front,=[x for x in ancestry if Path(x["path"]).name=="rustc" and "--crate-name" in x["args"] and x["args"][x["args"].index("--crate-name")+1]=="constructors"]
assert any(Path(x["path"]).name=="cargo" for x in ancestry)
proof={"dispatch_pid":os.getpid(),"observed_ns":time.monotonic_ns(),"ancestry":ancestry,"owning_rustc_is_link_only":any(x=="link-only" or x.startswith("-Zlink-only") for x in front["args"]),"args":argv,"mode":mode,"subject":subject,"uid":os.geteuid(),"output":str(out),"output_before":fs(out),
       "symbols_file":str(syms[0]),"symbols_bytes":syms[0].stat().st_size,"symbols_sha256":hashlib.sha256(syms[0].read_bytes()).hexdigest(),
       "argv_binding":"unchanged physical arguments as received from GCC"}
with (phase/("link-selection."+str(os.getpid())+".json")).open("x") as f:json.dump(proof,f)
if "-count" not in mode:
    os.execve(subject,[argv[0],*argv[1:]],env)
sel=cfg["counter"]
if sel=="hardware":
    os.execve(cfg["launcher"],[cfg["launcher"],str(phase/"counter.json"),subject,argv[0],*argv[1:]],env)
# Unlike the hardware launcher Valgrind supplies the subject filename as argv[0]. Its own link flags are retained.
os.execve(cfg["valgrind"],[cfg["valgrind"],"--tool=callgrind","--trace-children=no","--collect-jumps=no","--dump-instr=no","--callgrind-out-file="+str(phase/"callgrind.%p"),"--log-file="+str(phase/"valgrind.%p"),subject,*argv[1:]],env)
