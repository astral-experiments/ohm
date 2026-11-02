"""Kernel wait4's maximum RSS of one descendant, with an independent per-owner VmHWM sample off-counter."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import threading
from unittest.mock import patch

from common import need, save, sha


def calibrate(tool,where):
    where.mkdir()
    rows=[]
    for size,code in ((4,0),(64,31)):
        dest=where/(str(size)+".json")
        body="import os,sys; x=bytearray(int(sys.argv[1])<<20); x[::4096]=bytes([7])*len(x[::4096]); y=os.fork(); os._exit(int(sys.argv[2])) if not y else os.waitpid(y,0); sys.exit(int(sys.argv[2]))"
        argv=[str(tool),str(dest),"/usr/bin/python3","-IB","-c",body,str(size),str(code)]
        result=subprocess.run(argv,check=False,env={"PATH":"/usr/bin:/bin","LC_ALL":"C"})
        row=json.loads(dest.read_bytes())
        need(result.returncode==code==os.waitstatus_to_exitcode(row["status"]),"changed actual process exit in RSS observer")
        rows.append(row)
    need(rows[1]["maxrss_kib"]-rows[0]["maxrss_kib"]>48*1024,"kernel wait4 failed to see known committed pages")
    save(where/"verified.json",{"observer":sha(tool),"small":rows[0],"large":rows[1]})


def sample(complete,kit,owners,rows):
    # Physical PID + exe device/inode and actual owner argv are rechecked against the kernel trace reader.
    front=os.stat(kit.front); target=(front.st_dev,front.st_ino)
    while not complete.is_set():
        for ent in os.scandir("/proc"):
            if not ent.name.isdecimal():continue
            p=Path(ent.path)
            try:
                st=(p/"exe").stat()
                if (st.st_dev,st.st_ino)!=target:continue
                args=(p/"cmdline").read_bytes().split(b"\0")
                if b"--crate-name" not in args:continue
                owner=args[args.index(b"--crate-name")+1].decode()
                if owner not in owners:continue
                fields=dict(l.split(":",1) for l in (p/"status").read_text().splitlines() if ":" in l)
                if str(int(fields["Tgid"]))!=ent.name or "VmHWM" not in fields:continue
                val,unit=fields["VmHWM"].split()
                need(unit=="kB","unknown /proc peak RSS unit")
                pid=int(ent.name);row=rows.setdefault(pid,{"owner":owner,"front_dev_ino":list(target),"readings":0,"observed_highwater_kib":0})
                need(row["owner"]==owner,"sampled PID changed physical Rust owner")
                row["readings"]+=1;row["observed_highwater_kib"]=max(row["observed_highwater_kib"],int(val))
            except (FileNotFoundError,ProcessLookupError,PermissionError,IndexError):
                continue
        complete.wait(.1)


@contextmanager
def observe(guards,where,kit,*,owners=()):
    original=guards.run
    def run(argv,cwd,env,dest,*args,**kwargs):
        if dest!=where or argv[0]!="/usr/bin/strace":
            return original(argv,cwd,env,dest,*args,**kwargs)
        kernel=dest/"wait4-rss.json";tool=kit.tools/"rss"
        complete=threading.Event();observed={};errors=[]
        def snapshot():
            try:sample(complete,kit,set(owners),observed)
            except BaseException as exc:errors.append(repr(exc))
        thread=threading.Thread(target=snapshot) if owners else None
        if thread:thread.start()
        try:
            status=original([str(tool),str(kernel),*argv],cwd,env,dest,*args,**kwargs)
        finally:
            complete.set()
            if thread:thread.join()
        need(not errors,("RSS observer",errors))
        row=json.loads(kernel.read_bytes())
        need(os.waitstatus_to_exitcode(row["status"])==status and row["maxrss_kib"]>0,"incomplete kernel RSS")
        save(dest/"rss.json",{"tracer_argv":argv,"rss_observer":sha(tool),"raw_sha256":sha(kernel),
            "rss_scope":"Linux wait4 ru_maxrss, greatest singly resident child or descendant including strace; not summed simultaneous RSS",
            "observed_owner_highwater":observed,"sample_period_ms":100 if owners else None})
        return status
    with patch.object(guards,"run",run):yield
