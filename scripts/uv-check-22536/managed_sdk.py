"""Move worker-owned installed directories at one fixed sysroot. Never modify a launcher inode."""
from pathlib import Path
import os
from basis import LOCK,Env,EVENTS,canon,filehash,read

class Managed(Env):
    def __init__(self,cfg):
        super().__init__(cfg)
        self.pool=self.root.parent/'ctfe22-root-sdks';self.active=None;self.identities=read(self.results/'actual-inputs.json')
        assert cfg.get('fresh_private_sdk_pool')==str(self.pool)and not self.pool.is_symlink()and self.pool.is_dir()
        for role,path in cfg['sdks'].items():
            assert Path(path)==self.pool/role and not Path(path).is_symlink()
        assert self.sdk==self.root/'sdk'and not self.sdk.exists()and not self.sdk.is_symlink()
        assert self.pool.stat().st_dev==self.root.stat().st_dev
    def identity(self,role,where):
        v=self.identities[role];parts={}
        for tool in ('cargo','rustc'):
            f=where/'bin'/tool;st=f.stat();fid=EVENTS['file_id'](f);assert fid==v[tool+'_kernel_identity']and f.is_file()and not f.is_symlink()
            parts[tool]=[fid,st.st_ctime_ns]
        return parts
    def move(self,role,src,dst):
        assert src.is_dir()and not src.is_symlink()and not dst.exists()and not dst.is_symlink()
        old=self.identity(role,src);os.rename(src,dst);assert self.identity(role,dst)==old
        with (self.results/'sdk-directory-moves.jsonl').open('ab')as f:
            f.write(canon({'role':role,'source':str(src),'destination':str(dst),'launcher_and_cargo':old})+b'\n')
    def home(self):
        if self.active is not None:self.move(self.active,self.sdk,self.pool/self.active);self.active=None
    def choose(self,role):
        assert role in self.identities and role in self.inp['sdks']
        if self.active!=role:
            self.home();self.move(role,self.pool/role,self.sdk);self.active=role
        assert filehash(self.sdk/'bin/cargo')==self.identities[role]['signed_cargo']==LOCK['signed_cargo']
