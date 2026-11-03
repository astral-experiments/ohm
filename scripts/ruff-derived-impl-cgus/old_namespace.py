"""Copy and authenticate the actual pre-edit Cargo state for an independent forward diagnostic."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

DIRS=('build','cargo-home','target')
MARKERS=('ruff-incremental-roots.json','selected-binary-input.json')
def check(ok,message):
    if not ok:raise ValueError(message)
def fingerprint(root, names=(*DIRS,*MARKERS)):
    """Bind every supported path, link group, regular body, permission and modification time."""
    digest=hashlib.sha256(); owners={}; bytes_=files=dirs=links=0
    def record(fields):
        digest.update(json.dumps(fields,ensure_ascii=True,separators=(',',':')).encode()+b'\n')
    def visit(p):
        nonlocal bytes_,files,dirs,links
        name=p.relative_to(root).as_posix();st=p.lstat();kind=stat.S_IFMT(st.st_mode);identity=(st.st_dev,st.st_ino)
        extra=[(attr,hashlib.sha256(os.getxattr(p,attr,follow_symlinks=False)).hexdigest())for attr in sorted(os.listxattr(p,follow_symlinks=False))]
        row=[name,st.st_mode,st.st_mtime_ns,extra]
        if stat.S_ISLNK(kind):
            links+=1;record(row+[os.readlink(p)]);return
        if stat.S_ISDIR(kind):
            dirs+=1;record(row);[visit(child)for child in sorted(p.iterdir())];return
        check(stat.S_ISREG(kind),('unrepresentable present file',name))
        if identity not in owners:
            with p.open('rb')as f:value=hashlib.file_digest(f,'sha256').hexdigest()
            owners[identity]=(name,value);bytes_+=st.st_size
        origin,h=owners[identity];files+=1;record(row+[st.st_size,origin,h])
    for n in names:visit(root/n)
    return {'sha256':digest.hexdigest(),'logical_unique_bytes':bytes_,'regular_paths':files,'distinct_regular_files':len(owners),'directories':dirs,'symlinks':links},set(owners)
def save(root):
    dst=root/'authenticated-initial-old';check(not dst.exists(),'existing namespace')
    source,identities=fingerprint(root);check(shutil.disk_usage(root).free>=15*2**30+source['logical_unique_bytes']+512*2**20,'insufficient reserve for an independent namespace')
    dst.mkdir();paths=[root/n for n in (*DIRS,*MARKERS)]
    subprocess.run(['cp','--archive','--reflink=auto','--',*paths,dst],check=True)
    copy,other=fingerprint(dst);check(source==copy and not identities&other,'old snapshot differs or shares a mutable inode')
    return source
def restore(root,proof):
    src=root/'authenticated-initial-old';f,_=fingerprint(src);check(f==proof,'private pre-edit source changed')
    for n in DIRS:
        live=root/n;check(live.is_dir()and not live.is_symlink(),'unsafe namespace restore');shutil.rmtree(live)
    for n in MARKERS:
        live=root/n;check(live.is_file()and not live.is_symlink(),'unsafe marker restore');live.unlink()
    for n in (*DIRS,*MARKERS):(src/n).rename(root/n)
    src.rmdir();out,_=fingerprint(root);check(out==proof,'rebuilt observed source differs from original OLD')
    return out

def save_checkout(work, private):
    check(work.name=='ruff' and (work/'.git').is_dir() and not work.is_symlink(),'unrecognized private Ruff checkout')
    private.mkdir();original,ids=fingerprint(work.parent,(work.name,))
    subprocess.run(['cp','--archive','--reflink=auto','--',work,private],check=True)
    copy,other=fingerprint(private,(work.name,));check(original==copy and not ids&other,'incomplete or mutable source copy')
    return original
def restore_checkout(work, private, original):
    check(work.name=='ruff' and (work/'.git').is_dir() and not work.is_symlink() and (private/work.name/'.git').is_dir(),'unexpected source checkout')
    saved,_=fingerprint(private,(work.name,));check(saved==original,'archived source changed')
    parked=work.parent/'prior-edited-ruff-namespace';check(not parked.exists(),'unexpected previous source')
    work.rename(parked)
    subprocess.run(['cp','--archive','--reflink=auto','--',private/work.name,work],check=True)
    rebuilt,_=fingerprint(work.parent,(work.name,));check(rebuilt==original,'full source, file times or Git state differ')
    shutil.rmtree(parked)
    return rebuilt
