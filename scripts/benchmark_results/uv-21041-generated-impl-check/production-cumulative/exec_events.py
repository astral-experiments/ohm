"""Read argv at successful Linux exec stops; no syscall entry/exit tracing or workload flags."""
import ctypes
import errno
import json
import os
import signal
from pathlib import Path
import sys

WALL = 0x40000000
TRACEME, CONT, OPTIONS, GETEVENT = 0, 7, 0x4200, 0x4201
# TRACEFORK, TRACEVFORK, TRACECLONE, TRACEEXEC, EXITKILL
OPTS = 0x10001e
P = ctypes.CDLL(None, use_errno=True).ptrace
P.restype = ctypes.c_long
P.argtypes = (ctypes.c_uint, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
def ptrace(op, pid, value=0):
    ctypes.set_errno(0)
    if P(op, pid, None, value) == -1:
        e=ctypes.get_errno()
        raise OSError(e,os.strerror(e))
def msg(pid):
    out=ctypes.c_ulong()
    ptrace(GETEVENT,pid,ctypes.byref(out))
    assert 0<out.value<1<<31
    return out.value
def file_id(path):
    s=path.stat()
    return [s.st_dev,s.st_ino,s.st_size]
def image(pid,chosen,root):
    proc=Path("/proc")/str(pid)
    image=os.readlink(proc/"exe")
    ident=file_id(proc/"exe")
    # Read while the successful PTRACE_EVENT_EXEC stop is still held.
    data=(proc/"cmdline").read_bytes()
    assert 0<len(data)<=2<<20 and data.endswith(b"\x00")
    argv=data[:-1].split(b"\x00")
    selected=(ident==chosen or pid==root or Path(image).name=="rustc" or os.path.basename(argv[0])==b"rustc")
    row={"exe":image,"file":ident}
    if selected:row["argv"]=[os.fsdecode(v) for v in argv]
    return row
def capture(path,argv,env,cwd,selected,on_exec=None):
    path=Path(path);assert path.is_absolute() and path.is_dir() and argv and Path(argv[0]).is_absolute()
    with (path/"stdout").open("xb") as out,(path/"stderr").open("xb") as err:
        root=os.fork()
        if not root:
            try:
                os.chdir(cwd)
                os.dup2(out.fileno(),1);os.dup2(err.fileno(),2)
                ptrace(TRACEME,0);os.kill(os.getpid(),signal.SIGSTOP)
                os.execve(argv[0],argv,env)
            except BaseException:os._exit(126)
        pid,status=os.waitpid(root,0)
        assert pid==root and os.WIFSTOPPED(status) and os.WSTOPSIG(status)==signal.SIGSTOP,"child tracing unavailable"
        ptrace(OPTIONS,root,OPTS)
        ptrace(CONT,root)
        rows=[];first={root}
        while True:
            try:pid,status=os.waitpid(-1,WALL)
            except ChildProcessError:break
            assert len(rows)<20000 and pid>0
            if os.WIFEXITED(status) or os.WIFSIGNALED(status):
                rows.append([pid,status]);continue
            assert os.WIFSTOPPED(status)
            event=status>>16;sig=os.WSTOPSIG(status)
            if event:
                assert sig==signal.SIGTRAP and event in (1,2,3,4)
                child=msg(pid);row=[pid,status,child]
                if event==4:
                    snapshot=image(pid,selected,root)
                    if on_exec is not None:on_exec(pid,child,snapshot)
                    row.append(snapshot)
                rows.append(row);deliver=0
            elif pid not in first and sig==signal.SIGSTOP:
                first.add(pid);deliver=0
            else:
                # Forward the application's real delivery stops. Job-control stops after birth
                # need different semantics and cannot be admitted by this workload.
                assert sig not in (signal.SIGSTOP,signal.SIGTSTP,signal.SIGTTOU,signal.SIGTTIN)
                deliver=sig
            try:ptrace(CONT,pid,deliver)
            except ProcessLookupError:
                # A sibling may already have ended the thread. Require its final kernel status
                # or an explicit nonleader exec handoff in the independent reader.
                rows.append([pid,"resume-ESRCH"])
    with (path/"kernel-events.json").open("x")as f:json.dump({"root":root,"options":OPTS,"events":rows},f,separators=(",",":"))
def decode(data):
    root=data["root"];assert type(root)is int and root>0 and data["options"]==OPTS
    births={};exits={};images=[];handoffs={};unresumed=set()
    for row in data["events"]:
        pid,status=row[:2];assert type(pid)is int and pid>0
        if status=="resume-ESRCH":
            assert len(row)==2
            unresumed.add(pid);continue
        assert type(status)is int and 0<=status<1<<24
        if os.WIFEXITED(status)or os.WIFSIGNALED(status):
            assert len(row)==2 and pid not in exits
            exits[pid]=os.waitstatus_to_exitcode(status);continue
        assert os.WIFSTOPPED(status)and os.WSTOPSIG(status)==signal.SIGTRAP
        event=status>>16;child=row[2];assert type(child)is int and child>0
        if event in (1,2,3):
            assert len(row)==3 and pid!=child and child not in births and child!=root
            births[child]=pid
        else:
            assert event==4 and len(row)==4
            im=row[3];assert isinstance(im["exe"],str) and len(im["file"])==3 and all(type(x)is int for x in im["file"])
            images.append(dict(im,pid=pid,previous_tid=child))
            if child!=pid:
                assert child not in handoffs
                handoffs[child]=pid
    tracees={root,*births}
    assert all(p in tracees for p in births.values()) and {v["pid"]for v in images}<=tracees
    for child in births:
        seen=set()
        while child!=root:
            assert child in births and child not in seen
            seen.add(child);child=births[child]
    assert set(handoffs)<=tracees and set(handoffs.values())<=tracees
    assert tracees==set(exits)|set(handoffs) and unresumed<=set(exits)|set(handoffs)
    assert all((pid==root or pid in births)for pid in exits)and images and images[0]["pid"]==root
    return {"root":root,"images":images,"births":births,"exits":exits,"handoffs":handoffs}
def main():
    f=Path(sys.argv[1]);r=json.loads(f.read_bytes());assert len(sys.argv)==2
    capture(f.parent,r["command"],r["environment"],r["cwd"],r["compiler_file"])
if __name__=="__main__":main()
