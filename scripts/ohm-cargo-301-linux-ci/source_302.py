"""Reopen all 3,114 Git blobs before a Linux build of the eight-line Apple target selector."""
import hashlib,json,os,stat,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import source

HEAD='9a102b4519b40f9034aa40533d92c83583dcb289'
TREE='600cea5b6ad055da905e7b9960e4419405b2153f'
CHANGED='src/compiler/fingerprint/mod.rs'
def materialize(path):
    parent=source.materialize(path)
    def git(*args,data=None):return subprocess.check_output(['git','-C',path,*args],input=data)
    assert git('rev-parse','HEAD').decode().strip()==source.HEAD
    patch=(HERE/'302.patch').read_bytes();commit=(HERE/'302.commit').read_bytes()
    assert commit.splitlines()[:2]==[b'tree '+TREE.encode(),b'parent '+source.HEAD.encode()]
    assert git('hash-object','-t','commit','--stdin',data=commit).decode().strip()==HEAD
    git('apply','--index','--binary','-',data=patch)
    assert git('write-tree').decode().strip()==TREE
    assert git('hash-object','-w','-t','commit','--stdin',data=commit).decode().strip()==HEAD
    git('update-ref','HEAD',HEAD,source.HEAD)
    assert git('status','--porcelain')==b'' and git('diff','--name-only',source.HEAD,HEAD).decode().splitlines()==[CHANGED]
    git('fsck','--full','--strict','--no-progress')
    rows=git('ls-tree','-rz','HEAD').split(b'\0')[:-1]
    assert len(rows)==3114
    inventory=hashlib.sha256()
    for row in rows:
        meta,name=row.split(b'\t',1);mode,kind,blob=meta.split()
        p=path/os.fsdecode(name);m=p.lstat()
        if mode==b'120000':
            assert stat.S_ISLNK(m.st_mode);contents=os.fsencode(os.readlink(p))
        else:
            assert stat.S_ISREG(m.st_mode) and mode in (b'100644',b'100755')
            assert bool(m.st_mode&0o111)==(mode==b'100755');contents=p.read_bytes()
        assert kind==b'blob' and hashlib.sha1(b'blob %d\0'%len(contents)+contents).hexdigest().encode()==blob
        inventory.update(mode+b' '+hashlib.sha256(contents).hexdigest().encode()+b'\t'+name+b'\0')
    return {'source':HEAD,'parent':source.HEAD,'tree':TREE,'inventory_sha256':inventory.hexdigest(),'entries':len(rows),'changed':CHANGED,'parent_receipt':parent}
if __name__=='__main__':print(json.dumps(materialize(Path(sys.argv[1]).resolve()),sort_keys=True))
