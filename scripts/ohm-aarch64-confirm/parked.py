"""Select an independently materialized SDK without changing any member inode or timestamp."""
import ctypes
import hashlib
import os
from pathlib import Path
import shutil
import stat

def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()

def identity(path):
    s=path.stat(follow_symlinks=False)
    assert stat.S_ISREG(s.st_mode),path
    return {'dev':s.st_dev,'ino':s.st_ino,'mode':stat.S_IMODE(s.st_mode),'nlink':s.st_nlink,'size':s.st_size,
            'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns,'sha256':digest(path)}

def swap(left,right):
    libc=ctypes.CDLL(None,use_errno=True)
    change=libc.renameat2
    change.argtypes=(ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint)
    change.restype=ctypes.c_int
    if change(-100,os.fsencode(left),-100,os.fsencode(right),2)!=0:
        err=ctypes.get_errno()
        raise OSError(err,os.strerror(err),os.fspath(left),os.fspath(right))

def fingerprint(tree,names):
    assert {p.relative_to(tree).as_posix() for p in tree.rglob('*') if p.is_file()}==set(names)
    return {n:identity(tree/n) for n in sorted(names)}

class Parked:
    def __init__(self,store,visible,files,origins,driver):
        assert not store.exists() and not visible.exists() and set(files)==set(origins)==set('ANM')
        self.store,self.visible,self.names,self.driver=store,visible,set(files['A']),driver
        store.mkdir();visible.parent.mkdir(parents=True,exist_ok=True)
        assert visible.parent.stat().st_dev==store.stat().st_dev
        for role in 'ANM':
            folder=store/role;folder.mkdir()
            assert set(files[role])==self.names
            for name,(h,size,mode) in sorted(files[role].items()):
                src=origins[role]/name;dst=folder/name;dst.parent.mkdir(parents=True,exist_ok=True)
                source=identity(src)
                assert [source['sha256'],source['size'],source['mode']]==[h,size,mode]
                if role=='A' or name==driver:
                    with src.open('rb') as inp,dst.open('xb') as out:
                        shutil.copyfileobj(inp,out,2**20)
                    dst.chmod(mode)
                else:
                    assert files[role][name]==files['A'][name]
                    os.link(store/'A'/name,dst)
        # Freeze only after every initial link has been established and all writers have closed.
        self.initial={k:fingerprint(store/k,self.names) for k in 'ANM'}
        for name in self.names:
            ids=[v[name] for v in self.initial.values()]
            if name==driver:
                assert len({(t['dev'],t['ino']) for t in ids})==len({t['sha256'] for t in ids})==3
                assert all(t['nlink']==1 for t in ids)
            else:
                assert ids[0]==ids[1]==ids[2] and ids[0]['nlink']==3
        self.active=None
    def select(self,role):
        assert role in self.initial
        before=self.active
        if before is None:
            (self.store/role).rename(self.visible)
        elif before!=role:
            assert not (self.store/before).exists()
            swap(self.visible,self.store/role)
            (self.store/role).rename(self.store/before)
        actual=fingerprint(self.visible,self.names)
        assert actual==self.initial[role],(before,role,actual[self.driver],self.initial[role][self.driver])
        self.active=role
        return {'from':before,'to':role,'driver':actual[self.driver],'members':len(actual),'files':actual}
