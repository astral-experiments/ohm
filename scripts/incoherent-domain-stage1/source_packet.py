"""Verify a small, self-contained child commit against the exact materialized parent Git objects."""
from hashlib import sha256
from pathlib import Path, PurePosixPath
import json, re, subprocess
def run(repo,*args,stdin=None):
    return subprocess.check_output(['git','-C',repo,*args],input=stdin)
def git(repo,*args):
    return run(repo,*args).decode().strip()
def filehash(p):
    with p.open('rb') as f:
        import hashlib
        return hashlib.file_digest(f,'sha256').hexdigest()
def blob(repo,rev,path):
    b=run(repo,'ls-tree','-z',rev,'--',path).split(b'\0')
    if b==[b'']:return None
    assert len(b)==2 and b[1]==b''
    hdr,rp=b[0].split(b'\t',1)
    mode,kind,oid=hdr.split()
    assert mode==b'100644' and kind==b'blob' and rp.decode()==path
    return oid.decode()
def ids(repo,child,parent):
    a=sorted(git(repo,'rev-list','--objects','--no-object-names',child,'^'+parent).splitlines())
    assert 2<=len(a)<=250 and len(set(a))==len(a) and child in a and all(re.fullmatch(r'[a-f0-9]{40}',oid)for oid in a)
    return a
def snapshot(repo,parent,child):
    assert git(repo,'rev-parse',child+'^@')==parent and re.fullmatch(r'[0-9a-f]{40}',child)
    paths=run(repo,'diff-tree','--no-commit-id','--no-renames','--name-only','-r','-z',parent,child).split(b'\0')
    assert paths[-1]==b'' and 1<=len(paths)-1<=45
    files={}
    for raw in paths[:-1]:
        path=raw.decode('ascii')
        assert re.fullmatch(r'(compiler|tests)/[a-zA-Z0-9_./-]+',path)and '..'not in PurePosixPath(path).parts and not path.endswith('/')
        files[path]=[blob(repo,parent,path),blob(repo,child,path)]
        assert files[path][0]!=files[path][1]
    objects=ids(repo,child,parent)
    return {'commit':child,'parent':parent,'tree':git(repo,'rev-parse',child+'^{tree}'),
            'parent_tree':git(repo,'rev-parse',parent+'^{tree}'),'delta':files,'object_count':len(objects),
            'object_ids_sha256':sha256(('\n'.join(objects)+'\n').encode()).hexdigest()}
def pack(repo,parent,child,folder):
    desc=snapshot(repo,parent,child);lines=('\n'.join(ids(repo,child,parent))+'\n').encode()
    data=run(repo,'pack-objects','--no-reuse-delta','--no-reuse-object','--stdout',stdin=lines)
    assert data.startswith(b'PACK') and 64<len(data)<=3*2**20
    desc['pack_size']=len(data);desc['pack_sha256']=sha256(data).hexdigest();desc['pack_git_id']=data[-20:].hex()
    (folder/'derive.pack').write_bytes(data);(folder/'derive-source.json').write_text(json.dumps(desc,sort_keys=True,indent=2)+'\n')
    return desc
def install(repo,folder,parent,parent_tree,manifest_digest,name='derive'):
    f=folder/(name+'-source.json');assert filehash(f)==manifest_digest
    desc=json.loads(f.read_bytes());data=folder/(name+'.pack')
    assert desc['parent']==parent and desc['parent_tree']==parent_tree and git(repo,'rev-parse',parent+'^{tree}')==parent_tree
    assert data.stat().st_size==desc['pack_size'] and filehash(data)==desc['pack_sha256']
    with data.open('rb')as stream:
        oid=subprocess.check_output(['git','-C',repo,'index-pack','--strict','--stdin'],stdin=stream,text=True).split()[-1]
    assert oid==desc['pack_git_id'] and re.fullmatch(r'[a-f0-9]{40}',oid)
    idx=Path(git(repo,'rev-parse','--absolute-git-dir'))/'objects/pack'/('pack-'+oid+'.idx')
    members=sorted(s.split()[0]for s in git(repo,'verify-pack','-v',idx).splitlines()if re.match(r'^[a-f0-9]{40} (tree|blob|commit) ',s))
    observed=snapshot(repo,parent,desc['commit']);assert all(desc[k]==v for k,v in observed.items())
    assert members==ids(repo,desc['commit'],parent) and len(members)==desc['object_count']
    return desc
