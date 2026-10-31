"""Linux VFS mount and allocated inode observations. Overlay regular-file st_dev may differ from directory st_dev."""
import ctypes
import os
from pathlib import Path
import re
import stat
import struct
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import tables as t

STATX_MNT_ID=0x1000
STATX_BASIC_STATS=0x7ff
AT_EMPTY_PATH=0x1000
libc=ctypes.CDLL(None,use_errno=True)
statx=libc.statx
statx.argtypes=(ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_uint,ctypes.c_void_p)
statx.restype=ctypes.c_int

def read(path):
    fd=os.open(path,os.O_PATH|os.O_CLOEXEC|os.O_NOFOLLOW)
    try:
        actual=t.shape(os.fstat(fd))
        body=Path(f'/proc/self/fdinfo/{fd}').read_text()
        mount,=re.findall(r'^mnt_id:\s*(\d+)$',body,re.MULTILINE)
        inode,=re.findall(r'^ino:\s*(\d+)$',body,re.MULTILINE)
        buf=ctypes.create_string_buffer(256)
        if statx(fd,b'',AT_EMPTY_PATH,STATX_MNT_ID|STATX_BASIC_STATS,buf):
            err=ctypes.get_errno();raise OSError(err,os.strerror(err),str(path))
        data=buf.raw
        u32=lambda n:struct.unpack_from('=I',data,n)[0]
        u64=lambda n:struct.unpack_from('=Q',data,n)[0]
        # Linux's reserved fixed-width statx layout, including the genuine mount number at byte 144.
        return dict(stat=actual,lstat=t.shape(path.lstat()),fdinfo=[int(mount),int(inode)],
                    statx=[u32(0),u64(144),os.makedev(u32(136),u32(140)),u64(32),
                           struct.unpack_from('=H',data,28)[0],u64(48),u64(40),u32(16)])
    finally:
        os.close(fd)

def capture(root,shadow,original):
    """Preserve each observation, including errors, before the independent terminal gate adjudicates it."""
    found={'roots':{},'original':{},'shadow':{}}
    for group,names,base in [('roots',['.','target','build',shadow.name],root),
                              ('original',sorted(original),root),
                              ('shadow',['.',*[str(p.relative_to(shadow)) for p in sorted(shadow.rglob('*'))]],shadow)]:
        for name in names:
            try:found[group][name]=read(base/name)
            except (OSError,ValueError) as exc:
                found[group][name]={'error':type(exc).__name__,'message':str(exc)}
    return found

def validate(proof,original,stages,shadow_name='displaced-shadow'):
    expected_roots={'.','target','build',shadow_name}
    t.need(set(proof)=={'roots','original','shadow'} and set(proof['roots'])==expected_roots
           and set(proof['original'])==set(original) and set(proof['shadow'])==set(stages),'incomplete mount proof')
    reference=proof['roots']['.']['fdinfo'][0]
    t.need(isinstance(reference,int) and reference>0,'invalid root mount ID')
    for group,rows in proof.items():
        for path,r in rows.items():
            t.need(set(r)=={'stat','lstat','fdinfo','statx'},('unreadable mounted entry',group,path))
            shape=r['stat'];mask,mnt,dev,ino,mode,blocks,size,links=r['statx']
            t.need(shape==r['lstat'] and mask&(STATX_MNT_ID|STATX_BASIC_STATS)==STATX_MNT_ID|STATX_BASIC_STATS
                   and [dev,ino,links,mode,blocks,size]==shape
                   and r['fdinfo']==[mnt,ino] and mnt==reference,('foreign mount or unstable identity',group,path))
            if group=='original':t.need(shape==original[path],('different original inode',path))
            elif group=='shadow':t.need(shape==stages[path],('different staged inode',path))
            else:t.need(stat.S_ISDIR(mode),('not a directory root',path))
    t.need(proof['roots'][shadow_name]==proof['shadow']['.'] and proof['roots']['target']==proof['original']['target']
           and proof['roots']['build']==proof['original']['build'],'root identity changed')
    owners={tuple(v[:2]) for v in original.values()}
    stage_ids={tuple(v[:2]) for v in stages.values()}
    t.need(not (owners & stage_ids),'physical shadow inode aliases an ordinary allocation')
    t.need(len(stage_ids)==len(stages) and all(s[2]==1 for s in stages.values() if stat.S_ISREG(s[3])),
           'staged payload has another hardlink')
    return dict(mount_id=reference,original_names=len(original),original_inodes=len(owners),stage_inodes=len(stage_ids),
                original_devices=sorted({x[0] for x in owners}),stage_devices=sorted({x[0] for x in stage_ids}),aliased_inodes=0)
