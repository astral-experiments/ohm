"""Exercise the actual Linux O_EXCL and stale-O_PATH guarantees used by the candidate."""
from pathlib import Path
import errno,fcntl,hashlib,json,os,tempfile
def sha(v):return hashlib.sha256(v).hexdigest()
def signature(stat):return [stat.st_dev,stat.st_ino,stat.st_nlink,stat.st_size]
def run(root,collision,exclusive):
    expected=b'\x7fELF'+b'o'*511;intruder=b'do not alter this competing publisher';p=root/'a'
    p.write_bytes(expected);cap=os.open(p,os.O_PATH|os.O_CLOEXEC);fd=os.open(p,os.O_RDONLY);held=None
    try:
        initial=os.fstat(fd);assert os.pread(fd,len(expected),0)==expected
        p.unlink()
        if collision:
            held=os.open(p,os.O_RDWR|os.O_CREAT|os.O_EXCL,0o640);assert os.write(held,intruder)==len(intruder)
        flags=os.O_CREAT|os.O_RDWR|(os.O_EXCL if exclusive else os.O_TRUNC)
        try:dest=os.open(p,flags,0o640);refusal=None
        except OSError as e:
            assert exclusive and collision and e.errno==errno.EEXIST
            refusal=e.errno;assert os.pread(held,len(intruder)+1,0)==intruder
            p.unlink();dest=os.open(p,os.O_CREAT|os.O_EXCL|os.O_RDWR,0o640)
        try:
            assert os.write(dest,expected)==len(expected);new=os.fstat(dest);assert (initial.st_dev,initial.st_ino)!=(new.st_dev,new.st_ino)
            capfd=os.open('/proc/self/fd/'+str(cap),os.O_RDWR)
            try:
                assert os.pread(capfd,2,18)==b'oo' and os.pwrite(capfd,b'xx',18)==2 and os.pread(capfd,2,18)==b'xx'
            finally:os.close(capfd)
            assert p.read_bytes()==expected;polled=os.fstat(fd);assert polled.st_nlink==0
            result={'competing_publisher':collision,'exclusive_create':exclusive,'refusal_errno':refusal,'held_prior':signature(polled),'created':signature(new),'published':sha(p.read_bytes()),'held_old_after_write':sha(os.pread(fd,len(expected),0))}
            if held is not None:
                data=os.pread(held,len(expected)+1,0);assert data==(intruder if exclusive else expected)
                result.update(competing_inode=signature(os.fstat(held)),competing_intact=data==intruder)
            return result
        finally:os.close(dest)
    finally:
        for x in (cap,fd,held):
            if x is not None:os.close(x)
        p.unlink(missing_ok=True)
if __name__=='__main__':
    with tempfile.TemporaryDirectory()as tmp:
        root=Path(tmp);print(json.dumps({'kernel':os.uname().release,'rows':[run(root,*args)for args in ((False,True),(True,True),(True,False))]},sort_keys=True,indent=2))
