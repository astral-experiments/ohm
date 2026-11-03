"""Reopen a pre-link O_PATH capability after the canonical name is replaced or reused."""
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import tempfile

def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def material(where):
    with tempfile.TemporaryDirectory(dir=where) as temporary:
        tmp=Path(temporary);p=tmp/'canonical';p.write_bytes(b'X'*65536)
        clone=tmp/'reflink'
        with p.open('rb')as a,clone.open('wb')as b:
            try:
                fcntl.ioctl(b,0x40049409,a.fileno());reflink=0
            except OSError as e:reflink=e.errno
        rows=[]
        for previous in ('read','path'):
            for label in ('existing-inode','fresh-inode'):
                p.write_bytes(b'X'*65536)
                pre=os.open(p,os.O_RDONLY if previous=='read'else os.O_PATH)
                with p.open('rb')as f:
                    try:
                        fcntl.fcntl(f,fcntl.F_SETLEASE,fcntl.F_WRLCK);disposition=fcntl.fcntl(f,fcntl.F_GETLEASE);err=0
                        fcntl.fcntl(f,fcntl.F_SETLEASE,fcntl.F_UNLCK)
                    except OSError as e:err=e.errno;disposition=None
                    before=os.fstat(f.fileno())
                if label=='fresh-inode':
                    new=tmp/'ordinary-output';new.write_bytes(b'X'*65536);os.replace(new,p)
                got=os.open('/proc/self/fd/'+str(pre),os.O_WRONLY);os.pwrite(got,b'!',8192);os.close(got);os.close(pre)
                rows.append(dict(handle=previous,output=label,lease_errno=err,lease=disposition,dev=before.st_dev,
                                 old_ino=before.st_ino,new_ino=p.stat().st_ino,canonical_corrupt=p.read_bytes()[8192:8193]==b'!'))
        return dict(reflink_errno=reflink,rows=rows)
if __name__=='__main__':
    import sys
    signal.signal(signal.SIGIO,signal.SIG_IGN)
    print(json.dumps(material(sys.argv[1]),sort_keys=True,indent=2))
