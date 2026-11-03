#!/usr/bin/python3 -IB
"""Handle precisely one real Cargo invocation, recording the unchanged argv and original jobserver."""
from pathlib import Path
import json
import fcntl
import resource
import os
import re
import sys

file,*argv=sys.argv[1:]
assert argv[argv.index("--crate-name")+1]=="ron" and not os.environ.get("LD_PRELOAD")
visit=Path(os.environ["OHM_CAPTURE_VISIT"]);visit.mkdir(exist_ok=True)
def raw(name,data):
    with (visit/name).open("xb") as f:f.write(data)
raw("cargo-argv.nul",b"\0".join(map(os.fsencode,[file,*argv]))+b"\0")
raw("cwd",os.fsencode(os.getcwd()));raw("jobserver",os.fsencode(os.environ["CARGO_MAKEFLAGS"]))
m=re.search(r"--jobserver-(?:auth|fds)=(\d+),(\d+)",os.environ["CARGO_MAKEFLAGS"]);assert m
assert all(os.get_inheritable(int(v)) for v in m.groups())
# Report the actual old reserved numbers without opening, closing or publishing their contents.
status={}
for fd in sorted({*range(190,212),*(int(s)for s in m.groups())}):
    try:status[fd]=[fcntl.fcntl(fd,fcntl.F_GETFD),os.fstat(fd).st_mode,os.fstat(fd).st_ino]
    except OSError as problem:status[fd]=[problem.errno]
raw("inherited-fd-status.json",json.dumps({"descriptors":status,"limit":resource.getrlimit(resource.RLIMIT_NOFILE)},sort_keys=True).encode())
raw("loader-environment.json",json.dumps({k:os.environ.get(k) for k in ("LD_LIBRARY_PATH","LD_AUDIT","LD_PRELOAD","LD_PROFILE","LD_DEBUG","LLVM_PROFILE_FILE")},sort_keys=True).encode())
mode=os.environ["OHM_CAPTURE_ACTION"]
if mode=="observe":
    os.execvpe(file,argv,os.environ)
assert mode in ("stock","reuse") and Path(file).samefile(Path(argv[0]))
assert not any(os.environ.get(k) for k in ("LD_AUDIT","LD_PROFILE","LD_DEBUG","LLVM_PROFILE_FILE"))
out=Path(argv[argv.index("--out-dir")+1]);suffix,=[s.split("=",1)[1]for s in argv if s.startswith("extra-filename=")]
assert re.fullmatch("-[0-9a-f]{16}",suffix)
tool=Path(os.environ["OHM_CAPTURE_ACTOR"])
env=dict(os.environ,OHM_RON_ARCHIVE=str(out/("libron"+suffix+".rlib")),OHM_RON_RECEIPT=str(out/(".ron-native-"+suffix+".receipt")),
         OHM_RON_BINDING=str(visit/"binding.tsv"),OHM_RON_GATE=str(visit/"gate.tsv"),OHM_RON_OBSERVATIONS=str(visit/"native.tsv"),
         OHM_RON_PAID_PLUGIN=str(tool/"contact.so"),OHM_RON_PAID_TERMINAL=str(visit/"children.tsv"))
# In this mode the inherited hardware counter covers precisely one complete
# signed compiler (P), or the supervisor and all real compiler processes (C).
# The matching whole-Cargo phase runs a separate counter, without this one.
counter=os.environ.get("OHM_RON_NATIVE_PMU")
if counter:
    program=Path(file) if mode=="stock" else tool/"supervise"
    cmd=argv if mode=="stock" else [str(program),mode,*argv]
    os.execve(counter,[counter,str(visit/"complete-hardware.json"),str(program),*cmd],env)
if mode=="stock":
    os.execve(file,argv,env)
os.execve(tool/"supervise",[str(tool/"supervise"),mode,*argv],env)
