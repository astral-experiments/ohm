"""Switch immutable Cargo images at one actual path without changing the physical compiler."""
import os
import runpy
from pathlib import Path
import shutil
import stat
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parent/'ohm-aarch64-fallback'))
from version_kit import bind,capsule,rt
from transport import SOURCES
from study import sha,load,save
PREVIOUS = runpy.run_path(str(HERE.parent/'ohm-aarch64-fallback/acquire.py'))
CLASSIC, CLASSIC_ELF = PREVIOUS['COMMIT'], PREVIOUS['PRODUCT']

def identity(p):
    s=p.stat()
    assert stat.S_ISREG(s.st_mode)
    return {'sha256':sha(p),'dev':s.st_dev,'ino':s.st_ino,'mtime_ns':s.st_mtime_ns,'mode':s.st_mode&0o777,'size':s.st_size}

class Selection:
    def __init__(self,inputs,compiler_role):
        bind()
        self.reg=load(HERE/'qualified-builds.json')
        archive=inputs/'versioned'/'sdk.tar.zst'
        assert sha(archive)==self.reg['capsule']
        assert not rt.SDK.exists();rt.SDK.parent.mkdir(parents=True,exist_ok=True)
        self.sdk_checked=capsule.verify(archive,compiler_role,rt.SDK)
        self.driver,=(rt.SDK/'lib').glob('librustc_driver-*.so')
        self.original_driver=identity(self.driver)
        assert self.original_driver['sha256']==self.reg['drivers'][compiler_role]
        self.active='signed';self.exe=rt.SDK/'bin/cargo';self.parking=rt.ROOT/'native-cargo-parking';self.parking.mkdir()
        self.versions={'signed':rt.CARGO_SOURCE,'classic':CLASSIC,'aware':SOURCES['cargo']['source']}
        self.identities={'signed':identity(self.exe)}
        assert self.identities['signed']['sha256']==rt.TOOLS['bin/cargo']
        for name,src,key in [('classic',inputs/'fixed',CLASSIC_ELF),('aware',inputs/'versioned'/'cargo',self.reg['cargo_elf'])]:
            manifest=load(src/'product.json');assert manifest['git']==self.versions[name] and manifest['cargo_sha256']==key==sha(src/'cargo')
            p=self.parking/name;shutil.copyfile(src/'cargo',p);p.chmod(manifest['mode']);self.identities[name]=identity(p)
            assert self.identities[name]['sha256']==key
        self.visits=[]
    def choose(self,name):
        assert identity(self.exe)==self.identities[self.active]
        if name!=self.active:
            os.rename(self.exe,self.parking/self.active)
            os.rename(self.parking/name,self.exe)
            self.active=name
        assert identity(self.exe)==self.identities[name]
        assert identity(self.driver)==self.original_driver
        n=f'{len(self.visits):03}-{name}'
        vers=rt.record(['cargo','+ohm','-Vv'],rt.LOG/'versions'/n,rt.ROOT,rt.environment())
        assert ('commit-hash: '+self.versions[name]).encode() in vers.stdout
        self.visits.append({'name':name,'cargo':identity(self.exe),'driver':self.original_driver,'version_receipt':sha(rt.LOG/'versions'/n/'command.json')})
        return name
    def close(self):
        save(rt.LOG/'all-product-selections.json',{'SDK':self.sdk_checked,'registered':self.reg,'identities':self.identities,'visits':self.visits})
