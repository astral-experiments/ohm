"""Freeze/reopen all original artifact payloads with member hashes and lossless solid compression."""
import gzip
import hashlib
import io
import json
import lzma
import sys
import tarfile
import zipfile
from pathlib import Path

def sha(body):return hashlib.sha256(body).hexdigest()
def members(path,digest):
    assert sha(path.read_bytes())==digest
    with zipfile.ZipFile(path) as z:
        names=z.namelist();assert len(names)==len(set(names)) and z.testzip() is None
        for name in sorted(names,key=lambda s:(Path(s).suffix,Path(s).name,s)):
            assert name and '..' not in Path(name).parts and not name.startswith('/') and not name.endswith('/')
            yield name,z.read(name)
def add(tar,name,body):
    info=tarfile.TarInfo(name);info.size=len(body);info.mode=0o644
    tar.addfile(info,io.BytesIO(body))
def pack(src,digest,dst):
    with lzma.open(dst,'xb',preset=6) as out,tarfile.open(mode='w|',fileobj=out) as tar:
        roster={}
        for name,original in members(src,digest):
            body=gzip.decompress(original) if name.endswith('.gz') else original
            roster[name]={'size':len(original),'sha':sha(original),'retained_bytes':len(body),'retained_sha':sha(body)}
            add(tar,'files/'+name,body)
        add(tar,'INDEX.json',json.dumps({'zip_sha':digest,'members':roster},sort_keys=True,separators=(',',':')).encode())
def read(src,digest):
    if src.suffix=='.zip':
        return {name:(gzip.decompress(body) if name.endswith('.gz') else body) for name,body in members(src,digest)}
    data={}
    with tarfile.open(src,'r|xz') as tar:
        for e in tar:
            assert e.isfile() and (e.name.startswith('files/') or e.name=='INDEX.json') and '..' not in Path(e.name).parts
            name=e.name.removeprefix('files/');assert name not in data
            data[name]=tar.extractfile(e).read()
    index=json.loads(data.pop('INDEX.json'))
    assert index['zip_sha']==digest and set(index['members'])==set(data)
    for name,body in data.items():
        assert [len(body),sha(body)]==[index['members'][name][k] for k in ('retained_bytes','retained_sha')]
    return data
if __name__=='__main__':pack(Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3]))
