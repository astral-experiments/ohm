"""Identify the actual Ruff test CGUs the release compiler retains through a renderer edit."""
import gzip
import hashlib
import os
from pathlib import Path
import struct
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'ruff-heldout-mono-fold'))
from role_graph import products

def capture(state,prior_sessions,release,folder):
    sessions={p.parent.resolve() for p in state.rglob('work-products.bin') if
              p.parent.parent.name.startswith('ruff_db-') and p.parent.name.startswith('s-') and not p.parent.name.endswith('-working')}
    new=sessions-prior_sessions
    if new:
        current,=new
    else:
        current,=sessions
        assert sessions==prior_sessions
    manifest=current/'work-products.bin';raw=manifest.read_bytes()
    assert raw[:4]==b'RSIC' and raw[7:7+raw[6]].decode()==release
    rows=products(manifest,struct.unpack_from('<H',raw,4)[0],release)
    (folder/'consumer-work-products.bin.gz').write_bytes(gzip.compress(raw,compresslevel=2,mtime=0))
    objects={}
    pins={}
    for key,row in rows.items():
        name=row['name'];fn=row['files']['o'];path=current/fn
        assert path.parent==current and path.resolve()==path and name not in objects
        f=path.open('rb');st=os.fstat(f.fileno())
        objects[name]=dict(cgu_key=key,work_product=row['product'],file=fn,identity=[st.st_dev,st.st_ino,st.st_size],
                           sha256=hashlib.file_digest(f,'sha256').hexdigest())
        f.seek(0);pins[name]=f
    assert len(objects)==216 and len({p['file'] for p in objects.values()})==len(objects)
    return sessions,pins,objects

def retained(before,after,pins):
    assert set(before)==set(after)==set(pins)
    kept=[]
    for name,old in before.items():
        f=pins[name];st=os.fstat(f.fileno())
        assert old['identity']==[st.st_dev,st.st_ino,st.st_size] and hashlib.file_digest(f,'sha256').hexdigest()==old['sha256']
        new=after[name];assert new['cgu_key']==old['cgu_key'] and new['work_product']==old['work_product']
        if new['identity']==old['identity']:
            assert new['sha256']==old['sha256'];kept.append(name)
    return sorted(kept)
