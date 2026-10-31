"""Immutable subjects and small, shared integrity checks."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess

HERE=Path(__file__).resolve().parent
RUST='625207d26ce4449c9c95d871c88cfb50e904c09f'
RTREE='8b72462af9b3251a8610e4310d34b9de4f1c8344'
ROLES={'pinned':('2554a1dfaf22474b360a4298883acf41f82bd78f','014d4b308410fdaa2acdadaff6aba2a410fc43da'),
       'fourfix':('4591cf45cc10abb19d2456c40b99606e08167f29','a2c9a62722e1ef849cb68874e79617c92d165a8b')}
GNU='x86_64-unknown-linux-gnu'
APPLE='aarch64-apple-darwin'
WILD='0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5'
RUFF='93526150df078af7dd8fc4226cdcc469539d2001'
LOCKED={'zmij':('1.0.10','30e0d8dffbae3d840f64bda38e28391faef673a7b5a6017840f2a106c8145868'),
        'objc2':('0.6.3','b7c2599ce0ec54857b29ce62166b0ed9b4f6f1a70ccc9a71165b6154caca8c05')}
SEEDS={'public-seed':'85c467e1190d80fa8607fb0f9ef0824b4271266a','signed-rust':'d1e77f9acf1bb19ceb72274b89a5aaa119fb8bf1',
       'cargo-seed':'46d28e8bff1c6b52f3e7b7bc13192019e964a7da','signed-reader':'f40b16cdb9c041c941a5e339f816111a80a84bdf',
       'kernel-reader':'2969895dc49c9d8970ef121e1ff024ef001dc7ce','apple-reader':'14c9d13d68f3dd21c53f1ef6c3721de8363c0123',
       'marker-reader':'89a055549f4335e6e172f96c65d162dcd9cb1046','ruff':RUFF}
def require(value,msg):
    if not value:raise RuntimeError(str(msg))
def read(p):return json.loads(Path(p).read_bytes())
def save(p,d):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as f:json.dump(d,f,indent=2,sort_keys=True);f.write('\n')
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def member(p):
    s=Path(p).lstat();require(stat.S_ISREG(s.st_mode),('not regular',p))
    return {'sha256':sha(p),'bytes':s.st_size,'mode':stat.S_IMODE(s.st_mode)}
def ident(p):
    p=Path(p).resolve(strict=True);s=p.stat()
    return {'path':str(p),'dev':s.st_dev,'ino':s.st_ino,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns,**member(p)}
def run(args,**options):return subprocess.check_output([str(x) for x in args],**options).decode().strip()
def git(p,*a):return run(['git','-C',p,*a])
def host():
    key=(platform.system(),platform.machine())
    require(key in [('Linux','x86_64'),('Darwin','arm64')],key)
    return GNU if key[0]=='Linux' else APPLE
def seed(name):
    p=Path(os.environ['GITHUB_WORKSPACE'])/name
    require(git(p,'rev-parse','HEAD')==SEEDS[name],('incorrect source checkout',name));return p
def context(root,sdk):
    """Use real rustup proxies and a single canonical, physically verified toolchain root."""
    root=Path(root).resolve();sdk=Path(sdk).resolve()
    proxy=root/'proxies';proxy.mkdir(exist_ok=True)
    shim=Path(shutil.which('rustup')).resolve(strict=True)
    for name in ('rustup','cargo','rustc','rustdoc'):
        p=proxy/name
        if not p.exists():p.symlink_to(shim)
        require(p.samefile(shim),p)
    alias=root/'rustup/toolchains/ohm';alias.parent.mkdir(parents=True,exist_ok=True)
    if not alias.exists():alias.symlink_to(sdk,target_is_directory=True)
    require(alias.samefile(sdk),alias)
    paths={k:root/v for k,v in {'HOME':'home','CARGO_HOME':'registry','TMPDIR':'tmp'}.items()}
    for d in paths.values():d.mkdir(exist_ok=True)
    e={**{k:str(v) for k,v in paths.items()},'PATH':str(proxy)+':'+os.environ['PATH'],'RUSTUP_HOME':str(root/'rustup'),'RUSTUP_AUTO_INSTALL':'0','LANG':'C','LC_ALL':'C','CARGO_TERM_COLOR':'never','CARGO_TARGET_DIR':str(root/'target'),'CARGO_BUILD_BUILD_DIR':str(root/'shared')}
    require(Path(run(['rustc','+ohm','--print','sysroot'],env=e)).samefile(sdk),'wrong sysroot')
    return e
def job():
    return {k:os.environ[k] for k in ('GITHUB_REPOSITORY','GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_JOB')}
