"""Observe actual write-lease support separately from the mandatory live O_PATH replay."""
import errno,fcntl,os,signal,tempfile
from pathlib import Path
def probe(path):
    rows=[]
    for access in (os.O_RDONLY,os.O_RDWR):
        try:fd=os.open(path,access|os.O_CLOEXEC|os.O_NONBLOCK|os.O_NOFOLLOW)
        except OSError as e:rows.append({'access':access,'open_errno':e.errno});continue
        try:
            try:
                fcntl.fcntl(fd,fcntl.F_SETLEASE,fcntl.F_WRLCK)
                assert fcntl.fcntl(fd,fcntl.F_GETLEASE)==fcntl.F_WRLCK
                fcntl.fcntl(fd,fcntl.F_SETLEASE,fcntl.F_UNLCK);err=0
            except OSError as e:err=e.errno
            rows.append({'access':access,'setlease_errno':err})
        finally:os.close(fd)
    return rows

def peers(path,ours):
    observed=path.stat();fds=[];maps=[]
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            for f in (proc/'fd').iterdir():
                try:
                    if proc.name==str(os.getpid())and f.name==str(ours):continue
                    st=f.stat()
                    if (st.st_dev,st.st_ino)==(observed.st_dev,observed.st_ino):fds.append([proc.name,f.name,(proc/'comm').read_text().strip()])
                except OSError:pass
            for line in (proc/'maps').read_text(errors='replace').splitlines():
                cols=line.split(None,5)
                if len(cols)==6 and cols[5] in (str(path),str(path)+' (deleted)'):maps.append([proc.name,cols[1],cols[3],cols[4]])
        except OSError:pass
    return {'fd':fds,'mapped':maps}

def fixture(parent):
    with tempfile.TemporaryDirectory(prefix='.ohm-lease-fixture-',dir=parent)as tmp:
        path=Path(tmp)/'object';path.write_bytes(b'unchanged content');ids=path.stat()
        solo=probe(path);cap=os.open(path,os.O_PATH|os.O_CLOEXEC)
        try:capability=probe(path)
        finally:os.close(cap)
        with path.open('rb')as reader:regular=probe(path)
        if any(r.get('setlease_errno')==0 for r in solo):assert not any(r.get('setlease_errno')==0 for r in regular),(solo,regular)
        return {'dev':ids.st_dev,'ino':ids.st_ino,'alone':solo,'O_PATH':capability,'other_regular_read':regular}
def held(path,writer):
    old=signal.signal(signal.SIGIO,signal.SIG_IGN)
    try:
        a=path.stat();baseline=probe(path);cap=os.open(path,os.O_PATH|os.O_CLOEXEC)
        try:
            active=probe(path);f=fixture(path.parent)
            shm=fixture(Path('/dev/shm'))
            watch=peers(path,cap)
            record={'diagnostic_only':True,'kernel':os.uname().release,'real_identity':[a.st_dev,a.st_ino,a.st_size],'real_without_capability':baseline,'real_with_capability':active,'visible_fds_or_maps':watch,'same_mount':f,'tmpfs':shm}
            writer(record)
            assert any(v.get('setlease_errno')==0 for famil in (f,shm)for v in famil['O_PATH']),record
            b=path.stat();assert (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(b.st_dev,b.st_ino,b.st_size,b.st_mtime_ns,b.st_ctime_ns)
        except BaseException:os.close(cap);raise
        return cap
    finally:signal.signal(signal.SIGIO,old)
