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

def corrupt_text(binary, flip, expected):
    """Install a genuinely wrong text byte even when Linux still protects the executing inode."""
    import errno,hashlib,shutil,tempfile
    original=binary.stat()
    start=time.monotonic_ns();deadline=time.monotonic()+1;busy=0;tmp=None;method='in-place'
    stamp=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_ctime_ns,s.st_mtime_ns)
    while True:
        try:at=flip(binary);break
        except OSError as e:
            if e.errno!=errno.ETXTBSY:raise
            busy+=1
            if time.monotonic()<deadline:time.sleep(.02);continue
            fd,name=tempfile.mkstemp(prefix='.ohm-corrupt-stimulus-',dir=binary.parent);tmp=Path(name)
            try:
                with os.fdopen(fd,'wb')as out,binary.open('rb')as src:
                    assert stamp(os.fstat(src.fileno()))==stamp(original)
                    shutil.copyfileobj(src,out,1024*1024)
                    assert stamp(os.fstat(src.fileno()))==stamp(original)
                at=flip(tmp);os.chmod(tmp,original.st_mode&0o7777)
                assert stamp(binary.stat())==stamp(original)
                os.replace(tmp,binary)
            finally:tmp.unlink(missing_ok=True)
            method='atomic-one-byte-copy-after-ETXTBSY';break
    os.utime(binary,ns=(original.st_atime_ns,original.st_mtime_ns))
    now=binary.stat();assert (now.st_size,now.st_mtime_ns,now.st_mode)==(original.st_size,original.st_mtime_ns,original.st_mode)
    actual=hashlib.sha256();inverse=hashlib.sha256();changed=None;pos=0
    with binary.open('rb')as source:
        while block:=source.read(1024*1024):
            actual.update(block)
            if pos<=at<pos+len(block):
                i=at-pos;changed=block[i];inverse.update(block[:i]);inverse.update(bytes([changed^1]));inverse.update(block[i+1:])
            else:inverse.update(block)
            pos+=len(block)
    assert changed is not None and inverse.hexdigest()==expected and actual.hexdigest()!=expected and pos==original.st_size
    return {'method':method,'busy_attempts':busy,'elapsed_ns':time.monotonic_ns()-start,'old':[original.st_dev,original.st_ino],'new':[now.st_dev,now.st_ino],'bytes':pos,'text_offset':at,'byte_before':changed^1,'byte_after':changed,'inverse_full_sha256':inverse.hexdigest(),'sha256':actual.hexdigest(),'mode':now.st_mode,'mtime_ns':now.st_mtime_ns}
