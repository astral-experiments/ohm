"""Race the actual opened output generation and prove a stale incoming capability is isolated."""
from pathlib import Path
import os,time

def output_save(state,binary,replace):
    ready=state/'output-half'
    deadline=time.monotonic()+120
    while not ready.is_file():
        if time.monotonic()>deadline:raise RuntimeError('actual validated-output copy never reached its midpoint')
        time.sleep(.005)
    assert ready.read_text()==str(binary);info=binary.lstat()
    if replace:
        fresh=binary.parent/'atomic-racing-sentinel'
        with fresh.open('xb')as f:f.write(b'Ohm QA changed output inode in flight\n')
        os.replace(fresh,binary)
    else:
        with binary.open('r+b')as f:f.seek(18);f.write(b'\x00\x00')
        os.utime(binary,ns=(info.st_atime_ns,info.st_mtime_ns))
        assert binary.stat().st_mtime_ns==info.st_mtime_ns
    now=binary.lstat();(state/'output-continue').touch(exist_ok=False)
    return {'mode':'rename'if replace else 'in-place','prior':[info.st_dev,info.st_ino,info.st_size,info.st_ctime_ns],'current':[now.st_dev,now.st_ino,now.st_size,now.st_ctime_ns]}

def replace_before_lookup(state,binary):
    ready=state/'entry-ready';deadline=time.monotonic()+120
    while not ready.is_file():
        if time.monotonic()>deadline:raise RuntimeError('Wild did not enter the actual input lookup')
        time.sleep(.005)
    symbol=Path(ready.read_text())
    assert symbol.name=='symbols.o'and symbol.parent.parent==binary.parent
    src=binary.lstat();fresh=binary.parent/'qa-sparse-substitution'
    with fresh.open('xb')as f:
        f.write(b'Changed canonical output: matching permissions and logical size\n')
        f.truncate(src.st_size)
    os.chmod(fresh,src.st_mode & 0o7777);os.utime(fresh,ns=(src.st_atime_ns,src.st_mtime_ns))
    os.replace(fresh,binary);now=binary.lstat()
    assert (src.st_dev,src.st_mode,src.st_size,src.st_mtime_ns)==(now.st_dev,now.st_mode,now.st_size,now.st_mtime_ns)and src.st_ino!=now.st_ino
    (state/'entry-continue').touch(exist_ok=False)
    return {'mode':'replace-before-search','old_ino':src.st_ino,'new_ino':now.st_ino,'size':now.st_size,'mode_bits':now.st_mode,'mtime_ns':now.st_mtime_ns,'allocated':512*now.st_blocks}

def output_collision(state,binary):
    ready=state/'fresh-opening';limit=time.monotonic()+100
    while not ready.exists():
        if time.monotonic()>limit:raise RuntimeError('the actual new exclusive open did not start')
        time.sleep(.005)
    assert ready.read_text()==str(binary)
    payload=b'untouched native race witness before the exclusive open\n'
    fd=os.open(binary,os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_CLOEXEC,0o640)
    try:
        assert os.write(fd,payload)==len(payload);before=os.fstat(fd)
        (state/'fresh-continue').touch(exist_ok=False)
        until=time.monotonic()+100
        while os.fstat(fd).st_nlink:
            if time.monotonic()>until:raise RuntimeError('full native repair did not replace the racing output')
            time.sleep(.01)
        after=os.fstat(fd);actual=os.pread(fd,len(payload)+1,0)
        assert actual==payload and after.st_size==before.st_size==len(payload)
        return {'mode':'exclusive-collision','dev':before.st_dev,'ino':before.st_ino,'size':after.st_size,'old_link_count_after_native_repair':after.st_nlink,'sentinel_sha256':__import__('hashlib').sha256(actual).hexdigest()}
    finally:os.close(fd)
