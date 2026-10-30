"""Hold APFS response-file inodes from the enrolled directories while a real clang runs."""
from dataclasses import dataclass
import os
from pathlib import Path
import select
import stat
import threading
import time

from study import need
from xcode_response import LIMIT, NAME, stamp

MAX_HELD=256
MAX_SECONDS=2160

@dataclass
class Held:
    fd:int
    initial:list
    acquired_ns:int

class DirectoryHandles:
    """Open exact new names using the directory fd. Read contents only for a genuine observed ld."""
    def __init__(self,roots,*,native=True):
        self.roots=sorted({Path(n).resolve(strict=True) for n in roots})
        need(0<len(self.roots)<=2,'wrong native response directory count')
        self.native=native;self.dirs={};self.initial={};self.files={};self.rejected={};self.errors=[]
        self.lock=threading.Lock();self.stop=threading.Event();self.thread=None;self.kq=None
        self.start_ns=time.monotonic_ns();self.root_stats={}
    def __enter__(self):
        try:
            if self.native:
                need(hasattr(select,'kqueue'),'macOS kqueue is required')
                self.kq=select.kqueue()
            for root in self.roots:
                fd=os.open(root,os.O_RDONLY|os.O_NOFOLLOW|os.O_DIRECTORY|os.O_CLOEXEC);self.dirs[root]=fd;s=os.fstat(fd)
                need(stat.S_ISDIR(s.st_mode) and s.st_uid==os.getuid(),'foreign temporary-directory owner')
                self.root_stats[root]=[s.st_dev,s.st_ino,s.st_uid]
                if self.kq:
                    self.kq.control([select.kevent(fd,filter=select.KQ_FILTER_VNODE,flags=select.KQ_EV_ADD|select.KQ_EV_CLEAR,fflags=select.KQ_NOTE_WRITE|select.KQ_NOTE_RENAME|select.KQ_NOTE_DELETE|select.KQ_NOTE_REVOKE)],0,0)
                self.initial[root]={n for n in os.listdir(fd) if NAME.fullmatch(n)}
            if self.native:
                self.thread=threading.Thread(target=self.watch,name='response kqueue directory',daemon=True)
                self.thread.start()
            return self
        except BaseException:
            self.close();raise
    def scan(self):
        with self.lock:
            need(time.monotonic_ns()-self.start_ns<=MAX_SECONDS*10**9,'response capture window exceeded')
            for root,fd in self.dirs.items():
                names=os.listdir(fd);need(len(names)<150000,'Darwin temporary directory has too many entries')
                for n in names:
                    if not NAME.fullmatch(n):continue
                    key=(root,n)
                    if n in self.initial[root] or key in self.rejected:continue
                    try:
                        named=os.stat(n,dir_fd=fd,follow_symlinks=False)
                    except FileNotFoundError:continue
                    history=self.files.get(key,{})
                    if (named.st_dev,named.st_ino) in history:
                        if not stat.S_ISREG(named.st_mode) or named.st_uid!=os.getuid() or named.st_nlink!=1:
                            self.rejected[key]='changed owner, kind or link count'
                        continue
                    try:
                        f=os.open(n,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=fd)
                    except FileNotFoundError:continue
                    except OSError as exc:
                        self.rejected[key]='could not open safely: '+str(exc);continue
                    try:
                        s=os.fstat(f)
                        if ((s.st_dev,s.st_ino)!=(named.st_dev,named.st_ino) or not stat.S_ISREG(s.st_mode) or
                            s.st_uid!=os.getuid() or s.st_nlink!=1 or s.st_size>LIMIT):
                            self.rejected[key]='unsafe or atomically replaced response inode';continue
                        need(sum(len(v) for v in self.files.values())<MAX_HELD,'too many active response handles')
                        self.files.setdefault(key,{})[(s.st_dev,s.st_ino)]=Held(f,stamp(s),time.monotonic_ns());f=None
                    finally:
                        if f is not None:os.close(f)
    def watch(self):
        try:
            last=0
            while not self.stop.is_set():
                changes=self.kq.control(None,len(self.dirs),.047)
                need(all(not (e.flags&select.KQ_EV_ERROR) and not(e.fflags&(select.KQ_NOTE_RENAME|select.KQ_NOTE_DELETE|select.KQ_NOTE_REVOKE)) for e in changes),'enrolled Darwin response directory was revoked')
                now=time.monotonic()
                if changes or now-last>.25:self.scan();last=now
        except (OSError,RuntimeError) as e:self.errors.append(str(e));self.stop.set()
    def final(self,path,unlink):
        key=(path.parent.resolve(strict=True),path.name);need(key[0] in self.dirs,'outside the enrolled physical temporary directory')
        self.scan()
        with self.lock:
            need(not self.errors and key not in self.rejected and path.name not in self.initial[key[0]],'ineligible or pre-existing response: '+str(self.rejected.get(key,self.errors)))
            states=self.files.get(key,{});need(len(states)==1,'response was missed or its basename was reused')
            item,=states.values();initial=item.initial
            before=stamp(os.fstat(item.fd))
            after_name=os.stat(key[0]).st_ino
            need(after_name==self.root_stats[key[0]][1] and not os.path.lexists(path),'response still exists or directory changed')
            need(initial[:4]==before[:4]==unlink[:4] and initial[4]==unlink[4]==1 and before[4]==0 and
                 0<before[5]<=LIMIT and before[5:7]==unlink[5:7], 'held inode differs from the witnessed complete, unlinked response')
            data=os.pread(item.fd,LIMIT+1,0)
            after=stamp(os.fstat(item.fd));second=os.pread(item.fd,LIMIT+1,0)
            need(before==after==stamp(os.fstat(item.fd)) and len(data)==before[5] and data==second,'final response bytes or stamp changed')
            end=time.monotonic_ns()
            need(self.start_ns<=item.acquired_ns<=end<=self.start_ns+MAX_SECONDS*10**9,'unbounded response identity')
            return data,{'root':self.root_stats[key[0]],'initial':initial,'complete_unlink':unlink,'final_before':before,'final_after':after,
                         'window_start_ns':self.start_ns,'opened_ns':item.acquired_ns,'read_ns':end,'unique_inodes':len(states),'read_bytes':len(data)}
    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=4)
        need(not self.thread or not self.thread.is_alive(),'response vnode thread did not stop')
        if self.kq:self.kq.close();self.kq=None
        for history in self.files.values():
            for x in history.values():os.close(x.fd)
        self.files.clear()
        for f in self.dirs.values():os.close(f)
        self.dirs.clear()
    def __exit__(self,*unused):self.close()
