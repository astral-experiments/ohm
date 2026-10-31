"""Capture actual subprocesses on one extra warm check, outside the timing comparisons."""
import gzip
import json
from pathlib import Path
import re

def argv(raw, state):
    directory=state/"processes";directory.mkdir()
    return ["/usr/bin/strace","-ff","-qq","-ttt","-s","4096","-e","trace=execve,execveat,exit_group","-o",str(directory/"trace"),"--",*raw]

def finish(state, reports):
    directory=state/"processes";data=[];compiled=[];generated=[];links=[]
    for f in sorted(directory.glob("trace.*")):
        text=f.read_text(errors="replace")
        if "execve(" not in text and "execveat(" not in text:continue
        lines=text.splitlines();pid=int(f.name.split(".")[-1]);execs=[]
        for line in lines:
            m=re.match(r'^([\d.]+) execve\("((?:\\.|[^"\\])*)",.*\)\s+= 0$',line)
            if m:execs.append((float(m[1]),m[2],line))
        data.append((f.name,text))
        if not execs:continue
        t,path,cmd=execs[-1];exits=[re.match(r'^([\d.]+) exit_group\((\d+)\)',q) for q in lines];exits=[m for m in exits if m]
        elapsed=(float(exits[-1][1])-t) if exits else None
        leaf=Path(path).name;unit=re.search(r'"--crate-name", "([^"]+)"',cmd)
        item=dict(pid=pid,path=path,elapsed_traced_s=elapsed)
        if leaf in ("rustc","rustc.exe"):
            item.update(crate=unit[1] if unit else None,link_only='"link-only"' in cmd,driver_version='"-vV"' in cmd);compiled.append(item)
        elif leaf in ("ld","ld.lld","wild","rust-lld","ld.wild") or leaf.endswith("-ld"):links.append(item)
        elif ("build-script" in leaf or "build_script" in leaf) and ("unicode_names2" in path or "unicode-names2" in path):generated.append(item)
    assert data and compiled,("strace did not capture a rustc invocation",len(data))
    (reports/"processes.execve.gz").write_bytes(gzip.compress(json.dumps(data).encode(),mtime=0))
    out=dict(rustc=compiled,unicode_program=generated,linkers=links)
    (reports/"processes.json").write_text(json.dumps(out,indent=2)+"\n")
    print("observed processes",len(compiled),"rustc",[(row["crate"],row["link_only"]) for row in compiled],len(generated),"Unicode generators",len(links),"linkers",flush=True)
