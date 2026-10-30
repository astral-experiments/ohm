"""Freeze all original receipt contents, unwrapping nested gzip for solid compression."""
import gzip
import hashlib
import io
import json
import lzma
import sys
import tarfile
import zipfile
from pathlib import Path

SOURCE='ba90978f8720a4d8d8d54a12f5e970938d646dd85377e6a5be03bf3d28bd2d0c'
def h(body):return hashlib.sha256(body).hexdigest()
def add(tar,name,body):
    info=tarfile.TarInfo(name);info.size=len(body);info.mode=0o644
    tar.addfile(info,io.BytesIO(body))
def make(src,dst):
    assert src.stat().st_size==14345013 and h(src.read_bytes())==SOURCE
    with zipfile.ZipFile(src) as z, lzma.open(dst,'xb',preset=6) as out,tarfile.open(mode='w|',fileobj=out) as tar:
        roster={}
        names=z.namelist()
        assert len(names)==len(set(names))==428 and z.testzip() is None
        for name in sorted(names,key=lambda s:(Path(s).suffix,Path(s).name,s)):
            raw=z.read(name);body=gzip.decompress(raw) if name.endswith('.gz') else raw
            roster[name]=[len(raw),h(raw),len(body),h(body)]
            add(tar,'files/'+name,body)
        add(tar,'INDEX.json',json.dumps({'zip_sha256':SOURCE,'entries':roster},sort_keys=True,separators=(',',':')).encode())
if __name__=='__main__':make(Path(sys.argv[1]),Path(sys.argv[2]))
