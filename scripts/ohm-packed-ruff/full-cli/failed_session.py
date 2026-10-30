"""Inspect the deliberately rejected parser compilation before requesting its repair."""
import fcntl
import os
from pathlib import Path
import re
import stat
import time

from omission import publish, require


def observed(work):
    found={}
    for root in (work/'target',work/'build'):
        for base, dirs, _ in os.walk(root,followlinks=False):
            for name in dirs:
                path=Path(base)/name
                if not (name.startswith('s-') and name.endswith('-working') and 'incremental' in path.parts):continue
                rel=str(path.relative_to(work));parts=name.split('-')
                require(len(parts)==4 and re.fullmatch(r'ruff_python_parser-[0-9a-z]+',path.parent.name) and path.is_dir() and not path.is_symlink(),('unrelated failed session',rel))
                created_ns=int(parts[1],36)*1000
                lock=path.with_name(name.removesuffix('-working')+'.lock')
                fd=os.open(lock,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
                try:
                    # The pinned Linux rustc uses flock. A live writer rejects this nonblocking request.
                    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    lock_stat=os.fstat(fd);session=path.lstat()
                    require(stat.S_ISREG(lock_stat.st_mode) and stat.S_ISDIR(session.st_mode),'invalid failed-session identity')
                    found[rel]={'created_ns':created_ns,'directory':[session.st_dev,session.st_ino],
                                'lock':[lock_stat.st_dev,lock_stat.st_ino],'lock_name':str(lock.relative_to(work))}
                finally:os.close(fd)
    return found


def before_repair(work, previous, receipt):
    require(observed(work)==previous,'abandoned session changed after the rejected Cargo process exited')
    now=time.time_ns();cutoff=max((record['created_ns'] for record in previous.values()),default=0)+11_000_000_000
    delay=max(0,cutoff-now);require(delay<=12_000_000_000,'unreliable session creation timestamp')
    if delay:time.sleep(delay/1_000_000_000)
    ready=time.time_ns()
    require(ready>=cutoff and observed(work)==previous,'failed session did not stay unlocked across the compiler GC grace period')
    publish(receipt,{'read_ns':now,'ready_ns':ready,'cutoff_ns':cutoff,'sessions':previous,'rustc_gc_grace_ns':10_000_000_000})
