"""Source identity for the two Git checkouts in the historical unmodified Ruff lockfile."""
import hashlib,json,os,re,stat,subprocess,tomllib
from pathlib import Path

SOURCES={
    'git+https://github.com/salsa-rs/salsa?rev=fc00eba89e5dcaa5edba51c41aa5f309b5cb126b':('fc00eba89e5dcaa5edba51c41aa5f309b5cb126b',{'salsa','salsa-macros','salsa-macro-rules'}),
    'git+https://github.com/astral-sh/lsp-types.git?rev=3512a9f':('3512a9f33eadc5402cfab1b8f7340824c8ca1439',{'lsp-types'})}
def need(c,reason):
    if not c:raise ValueError(reason)
def external(pid):return pid.startswith(('registry+','git+'))
def owner(pid,lock):
    loc,frag=pid.rsplit('#',1)
    need(loc in SOURCES,'unregistered Git URL')
    rev,allowed=SOURCES[loc]
    if '@' in frag:name,version=frag.rsplit('@',1)
    else:name,version=loc.split('?',1)[0].rsplit('/',1)[-1].removesuffix('.git'),frag
    need(name in allowed and sum(p.get('source')==loc+'#'+rev and p['name']==name and p['version']==version for p in lock['package'])==1,'Git Cargo ID absent or duplicated in the actual lockfile')
    return name,version,rev
def root(home,d,expected):
    base=home/'git/checkouts';d=d.resolve(strict=True);need(d.is_relative_to(base),'Git package outside private source')
    src=Path(subprocess.check_output(['git','-C',d,'rev-parse','--show-toplevel'],text=True).strip())
    need(src.resolve(strict=True)==src and src.is_relative_to(base)and len(src.relative_to(base).parts)==2 and (src/'.git').is_dir(),'indirect Git source path')
    need(subprocess.check_output(['git','-C',src,'rev-parse','HEAD'],text=True).strip()==expected,'wrong checkout commit')
    return src
def verify(root,rev):
    tree=subprocess.check_output(['git','-C',root,'rev-parse',rev+'^{tree}'],text=True).strip()
    data=subprocess.check_output(['git','-C',root,'ls-tree','--full-tree','-rz',rev]);files={};digest=hashlib.sha256()
    for row in data.split(b'\0'):
        if not row:continue
        hdr,name=row.split(b'\t',1);mode,typ,oid=hdr.split();p=root/os.fsdecode(name)
        need(typ==b'blob'and mode in (b'100644',b'100755',b'120000')and not p.is_dir(),'unrecognized Git source member')
        info=p.lstat()
        if mode==b'120000':
            need(stat.S_ISLNK(info.st_mode)and p.resolve(strict=True).is_relative_to(root),'external Git source link')
            raw=os.fsencode(os.readlink(p))
        else:
            need(stat.S_ISREG(info.st_mode)and bool(info.st_mode&0o100)==(mode==b'100755'),'wrong Git mode')
            raw=p.read_bytes()
        need(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest().encode()==oid,'changed Git source bytes')
        files[name]=True;digest.update(mode+b' '+name+b'\0'+hashlib.sha256(raw).digest())
    extra={}
    for parent,dirs,names in os.walk(root,followlinks=False):
        if Path(parent)==root:dirs[:]=[n for n in dirs if n!='.git']
        for n in names+[x for x in dirs if (Path(parent)/x).is_symlink()]:
            p=Path(parent)/n;k=os.fsencode(p.relative_to(root))
            if k in files:continue
            need(k==b'.cargo-ok' and p.is_file()and not p.is_symlink(),'unknown untracked locked-Git member '+os.fsdecode(k))
            extra[os.fsdecode(k)]=hashlib.sha256(p.read_bytes()).hexdigest()
    return [rev,tree,len(files),digest.hexdigest(),extra]
