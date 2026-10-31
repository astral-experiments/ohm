"""Attach a private bind mount after the live Cargo GC opens its trash owner record."""
import ctypes
import gzip
import os
from pathlib import Path
import select
import struct
import subprocess

import compare
import observe as o


def watch(path):
    libc=ctypes.CDLL(None,use_errno=True)
    libc.fanotify_init.argtypes=[ctypes.c_uint,ctypes.c_uint]
    libc.fanotify_mark.argtypes=[ctypes.c_int,ctypes.c_uint,ctypes.c_uint64,ctypes.c_int,ctypes.c_char_p]
    group=libc.fanotify_init(0x01|0x04,os.O_RDONLY|os.O_CLOEXEC)  # FAN_CLOEXEC | FAN_CLASS_CONTENT
    if group<0:raise OSError(ctypes.get_errno(),'fanotify_init')
    if libc.fanotify_mark(group,1,0x10000,-100,os.fsencode(path))<0:  # FAN_MARK_ADD, FAN_OPEN_PERM
        error=ctypes.get_errno();os.close(group);raise OSError(error,'fanotify_mark')
    return group


def case(f, fallback):
    label='no-openat2' if fallback else 'native'
    c=f.makecase(label);root=c['shared']
    payload=f.context(root,True,compare.ROOT);owner=payload.parent/'owner'
    healthy=f.context(root,True,compare.OTHER)/'ordinary';f.write(healthy,compare.HEALTHY)
    view=f.mkdir(payload/'mounted');outside=f.mkdir(c['outside']/'external');sentinel=outside/o.NAME;f.write(sentinel,o.PAYLOAD)
    before=o.st(sentinel);origin=o.st(view);held=os.open(sentinel,os.O_RDONLY|os.O_NOFOLLOW)
    assert before['dev']==origin['dev'] and before['mount_id']==origin['mount_id']
    preview=f.gc(c,'unmounted-preview',True,root)
    assert compare.count(preview,1,len(compare.HEALTHY)) and o.st(sentinel)==before
    group=watch(owner);trace=f.o/(label+'.trace');trace.touch();os.chown(trace,f.uid,f.gid)
    args=['/usr/bin/strace','-f','-qq','-ttt','-yy','-s','1024','-e','trace=execve,openat,openat2,rename,renameat,renameat2,unlink,unlinkat,rmdir']
    if fallback:args+=['-e','inject=openat2:error=ENOSYS']
    args+=['-o',str(trace),'--',str(f.w/'shims/cargo'),'+ohm','gc','--color','never','-v','--build-dir',str(root)]
    process=subprocess.Popen(args,cwd=c['cwd'],env=c['env'],user=f.uid,group=f.gid,extra_groups=[],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    mid=None;event_fd=None
    try:
        assert select.select([group],[],[],35)[0],('no owner open permission event',process.poll())
        raw=os.read(group,4096)
        length,version,_,metadata,mask,event_fd,pid=struct.unpack_from('=IBBHQii',raw)
        assert length==len(raw) and metadata>=24 and version==3 and mask&0x10000 and event_fd>=0
        marker=owner.stat();event=os.fstat(event_fd)
        assert (marker.st_dev,marker.st_ino)==(event.st_dev,event.st_ino)
        executable=Path('/proc')/str(pid)/'exe'
        assert executable.samefile(f.runtime/'bin/cargo') and Path('/proc',str(pid)).stat().st_uid==f.uid
        assert o.st(view)==origin and o.st(sentinel)==before
        mid=f.bind(outside,view);bound=o.st(view/o.NAME)
        assert bound['dev']==before['dev'] and bound['ino']==before['ino'] and bound['mount_id']==mid!=origin['mount_id']
        assert os.write(group,struct.pack('=iI',event_fd,1))==8  # FAN_ALLOW
        os.close(event_fd);event_fd=None;os.close(group);group=None
        stdout,stderr=process.communicate(timeout=45)
        tr=trace.read_bytes();trace.with_suffix('.trace.gz').write_bytes(gzip.compress(tr,mtime=0));trace.unlink()
        info=os.fstat(held);remaining=o.st(sentinel);after=o.mounts()[mid]['path']
        snapshot={'role':f.role,'lane':label,'command':args,'collector_uid':f.uid,'collector_pid':pid,'marker':[marker.st_dev,marker.st_ino],
                  'before':before,'origin':origin,'bound':bound,'held_ino':info.st_ino,'held_nlink':info.st_nlink,'held_hash':o.sha(os.pread(held,4096,0)),
                  'external_after':remaining,'healthy_after':o.st(healthy),'mount_position_after':after,'mountpoint':str(view),'status':process.returncode,
                  'stdout':stdout.decode(),'stderr':stderr.decode(),'trace_sha256':o.sha(tr)}
        o.save(f.o/(label+'.json'),snapshot)
        assert after==str(view) and info.st_ino==before['ino'] and snapshot['held_hash']==before['sha256']
        if f.role=='signed':
            assert process.returncode==101 and remaining is None and info.st_nlink==0 and b'Device or resource busy' in stderr
        else:
            assert process.returncode==0 and remaining==before and info.st_nlink==1 and not healthy.exists()
            assert b'/proc/self/mountinfo' in tr and b'left untouched' in stderr
            if fallback:
                assert b'ENOSYS' in tr and b'INJECTED' in tr and b'/proc/self/fdinfo/' in tr
            else:
                assert b'EXDEV' in tr and b'RESOLVE_NO_XDEV' in tr and b'INJECTED' not in tr
        return snapshot
    finally:
        if group is not None:os.close(group)
        if event_fd is not None:os.close(event_fd)
        if process.poll() is None:
            try:process.communicate(timeout=12)
            except subprocess.TimeoutExpired:process.kill();process.communicate()
        if mid is not None:f.unmount(mid)
        os.close(held)


def run(f):
    lanes=[False,True] if f.role=='fixed' else [False]
    facts=[case(f,lane) for lane in lanes]
    assert not [m for m in o.mounts().values() if Path(m['path']).is_relative_to(f.w)]
    o.save(f.o/'result.json',{'lanes':[r['lane'] for r in facts],'qualified':True})
