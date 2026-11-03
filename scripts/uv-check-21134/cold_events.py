"""Record a full cold build while preserving the measured observer and its smaller limit."""
from pathlib import Path
import json
import os
import signal

from common import EV

# The measured observer and the cold observer use the same ptrace ABI and exec snapshots.
WALL, TRACEME, CONT, OPTIONS, OPTS = (EV[k] for k in ("WALL", "TRACEME", "CONT", "OPTIONS", "OPTS"))
ptrace, msg, image = (EV[k] for k in ("ptrace", "msg", "image"))

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
            assert len(rows)<120000 and pid>0
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
