"""Reassemble overlapping strace exec syscalls by PID before counting successful processes."""
import ast,re
from pathlib import Path

def require(ok, msg):
    if not ok:raise ValueError(str(msg))

def read_execs(raw):
    pending={};finished=[];resumed=0
    for line in raw.decode().splitlines():
        m=re.fullmatch(r'(\d+)\s+(.*)',line);require(m, line[:180]);pid=int(m[1]);s=m[2]
        if s.startswith(('execve(','execveat(')) and s.endswith(' <unfinished ...>'):
            require(pid not in pending,('duplicate pending',pid));pending[pid]=s.removesuffix(' <unfinished ...>');continue
        if s.startswith('<... ') and 'resumed>' in s:
            m=re.fullmatch(r'<\.\.\. (execve|execveat) resumed>(.*)',s);require(m and pid in pending,('missing partial exec',pid,s));prefix=pending.pop(pid);require(prefix.startswith(m[1]+'('),('syscall name',pid));s=prefix+m[2];resumed+=1
        if not re.search(r'\)\s+= 0$',s) or not s.startswith(('execve(','execveat(')):continue
        m=re.fullmatch(r'execve\(("(?:[^"\\]|\\.)*"), (\[.*\]), 0x[0-9a-f]+ /\* [0-9]+ vars \*/\)\s+= 0',s);require(m,'unparsed successful exec: '+s[:180]);path=ast.literal_eval(m[1]);args=ast.literal_eval(m[2]);require(all(isinstance(x,str) for x in args),('truncated or malformed argv',pid,path));finished.append((pid,path,args))
    require(not pending,('unfinished exec groups',list(pending)));return finished,resumed

def census(raw,compiler):
    events,overlap=read_execs(raw);rust=[];link=[]
    for pid,path,args in events:
        if '--crate-name' in args and any(x.startswith('--emit=') for x in args) and '--print' not in args:
            require(path==compiler,('unexpected compiler',pid,path));rust.append({'pid':pid,'name':args[args.index('--crate-name')+1],'src':[x for x in args if x.endswith(('/lib.rs','/build.rs','/main.rs'))], 'target':args[args.index('--target')+1] if '--target' in args else None,'mode':'link-only' if ('link-only' in args or '-Zlink-only' in args) else 'full','argv':args})
        if Path(path).name in ('ld','ld.bfd','ld.lld','rust-lld','wild'):link.append({'pid':pid,'path':path,'argv':args})
    return rust,link,overlap
