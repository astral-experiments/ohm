"""Resolve a positively observed read to the most recent exec inherited by that tracee."""
import re
from pathlib import Path


def need(ok,msg):
    if not ok:raise ValueError(msg)


def original_calls(lines):
    result=[];pending=None
    for line in lines:
        if line.endswith(" <unfinished ...>"):
            if pending is not None:result.append(("opaque",pending))
            pending=line[:-len(" <unfinished ...>")]
            continue
        if line.startswith("<... "):
            name,sep,tail=line[5:].partition(" resumed>")
            if pending is None or not sep or not pending.startswith(name+"("):
                result.append(("opaque",line));pending=None;continue
            line=pending+tail;pending=None
        if pending is not None:
            result.append(("opaque",pending));pending=None
        if line.startswith("???("):result.append(("opaque",line))
        else:result.append(("call",line))
    if pending is not None:result.append(("opaque",pending))
    return result


def owner_reads(raw,selected,classify):
    parents={};transitions={};opens=[];wild=set();cargo=set()
    for pid,lines in raw.items():
        events=[]
        for index,(typ,line) in enumerate(original_calls(lines)):
            if typ=="opaque":
                events.append((index,"opaque",""));continue
            if line.startswith(("execve(","execveat(")) and re.search(r"= 0$",line):
                m=re.match(r'^execve\("([^"]+)",',line)
                path=m[1] if m else ""
                image=classify(path) if path else "unidentified-exec"
                events.append((index,image,path))
                if image=="wild":wild.add(pid)
                if image=="cargo":cargo.add(pid)
            clone=re.match(r"^(clone3?|vfork|fork)\(.*\)\s+= (\d+)$",line)
            if clone:
                kid=int(clone[2]);need(kid not in parents and pid!=kid,"ambiguous kernel birth")
                kind="thread" if "CLONE_THREAD" in line else "process"
                parents[kid]={"creator":pid,"event":index,"kind":kind,"syscall":clone[1]}
            fd=re.match(r"^openat\(.*\bO_RDONLY\b.*\)\s+= ([0-9]+)<([^>]+)>$",line)
            if fd and fd[2]==selected:opens.append((pid,index,int(fd[1])))
        transitions[pid]=events
    def owner(pid,index,chain):
        if pid in {r["pid"] for r in chain}:raise ValueError("kernel birth cycle")
        events=[a for a in transitions.get(pid,[]) if a[0]<index]
        if events:
            end,tag,path=events[-1]
            return tag,[*chain,{"pid":pid,"event":end,"exec":path,"image":tag}]
        p=parents.get(pid)
        if not p:return None,chain
        return owner(p["creator"],p["event"],[*chain,{"pid":pid,**p}])
    selected_fds=[]
    for pid,index,fd in opens:
        image,lineage=owner(pid,index,[])
        if image=="wild":
            selected_fds.append({"pid":pid,"event":index,"fd":fd,"lineage":lineage})
    need(cargo and wild and selected_fds,"no authentic Cargo, Wild or read by that inherited image")
    return {"cargo":sorted(cargo),"wild":sorted(wild),"archive_read_by":sorted({o["pid"] for o in selected_fds}),"linux_fd_evidence":selected_fds}
