"""Reopen exact Cargo trees using the private packaging repository's self-contained object seed."""
import gzip
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
SEED='735e1528ed741015c57676dccf05dbdc0ff7bed1'
SEED_TREE='9cb7035b7adc52ecac48495666b95ba857ed3cdd'
BASE='2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c'
BASE_TREE='bc9fe7b15f4d1e9b935f8624f8b004ce0a7d2c66'
BASE_PARENT='7277e6cdaba44c43294a07c0661fc8e69fd8e3e7'
PACK='775494565d10143c9f34679ad21d90020ed9c82518f774fde923f4d5ef90ea4b'
def git(repo,*args,data=None):
    return subprocess.check_output(['git','-c','core.autocrlf=false','-C',repo,*args],input=data)
def hash_files(dest,head):
    roster=git(dest,'ls-tree','-rz','--full-tree',head).split(b'\0')[:-1]
    h=hashlib.sha256()
    for row in roster:
        meta,name=row.split(b'\t',1);mode,kind,blob=meta.split()
        path=dest/os.fsdecode(name);info=path.lstat()
        if mode==b'120000':
            assert stat.S_ISLNK(info.st_mode);body=os.fsencode(os.readlink(path))
        else:
            assert mode in (b'100644',b'100755') and stat.S_ISREG(info.st_mode)
            assert bool(info.st_mode&0o111)==(mode==b'100755');body=path.read_bytes()
        assert kind==b'blob' and hashlib.sha1(b'blob %d\0'%len(body)+body).hexdigest().encode()==blob
        h.update(mode+b' '+hashlib.sha256(body).hexdigest().encode()+b'\t'+name+b'\0')
    return {'files':len(roster),'mode_path_sha256_inventory':h.hexdigest()}
def tree(dest,pack,fixed=None):
    assert pack.stat().st_size==5307709 and hashlib.sha256(pack.read_bytes()).hexdigest()==PACK
    dest.mkdir()
    git(dest,'init','--quiet','--template=','-b','exact-seed')
    git(dest,'index-pack','--stdin',data=pack.read_bytes())
    shallow=dest/'.git/shallow';shallow.write_text(SEED+'\n')
    git(dest,'update-ref','refs/heads/exact-seed',SEED);git(dest,'checkout','-q','--detach',SEED)
    assert git(dest,'rev-parse','HEAD^{tree}').decode().strip()==SEED_TREE
    def visit(name,head,parent,wanted_tree,cut):
        commit=(HERE/(name+'.commit')).read_bytes()
        assert commit.splitlines()[:2]==[b'tree '+wanted_tree.encode(),b'parent '+parent.encode()]
        patch=gzip.decompress((HERE/(name+'.patch.gz')).read_bytes())
        assert git(dest,'hash-object','-t','commit','--stdin',data=commit).decode().strip()==head
        git(dest,'apply','--binary','--index','-',data=patch)
        assert git(dest,'write-tree').decode().strip()==wanted_tree
        assert git(dest,'hash-object','-t','commit','-w','--stdin',data=commit).decode().strip()==head
        if cut:shallow.write_text(SEED+'\n'+BASE+'\n')
        git(dest,'update-ref','HEAD',head)
        assert git(dest,'status','--porcelain=v1')==b'' and git(dest,'rev-parse','HEAD').decode().strip()==head
    visit('parent',BASE,BASE_PARENT,BASE_TREE,True)
    parent=BASE
    if fixed:
        if 'merge_parent' in fixed:
            second=fixed['merge_parent']
            assert second['pack']=='diagnostic-parent.pack'
            other=(Path(__file__).resolve().parent.parent/'gc-mount-evidence'/'candidate-source'/second['pack']).read_bytes()
            assert hashlib.sha256(other).hexdigest()==second['pack_sha256']
            git(dest,'index-pack','--stdin',data=other)
            assert git(dest,'cat-file','-t',second['commit'])==b'commit\n'
        for element in fixed['commits']:
            visit(element['key'],element['head'],parent,element['tree'],False)
            parent=element['head']
        assert parent==fixed['head']
        if 'merge_parent' in fixed:
            assert git(dest,'rev-parse','HEAD^2').decode().strip()==fixed['merge_parent']['commit']
    head=fixed['head'] if fixed else BASE
    git(dest,'fsck','--no-progress','--full','--strict')
    return {'commit':head,'tree':git(dest,'rev-parse','HEAD^{tree}').decode().strip(),'source_pack':PACK,
            'lock':hashlib.sha256((dest/'Cargo.lock').read_bytes()).hexdigest(),**hash_files(dest,head)}
