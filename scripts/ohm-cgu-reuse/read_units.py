"""Read all measureme v9 codegen activity records and join them to rustc's mono-item assignment."""
import collections
import functools
import hashlib
import json
import re
import struct
from pathlib import Path

def read_profile(path):
    body=path.read_bytes(); hdr=struct.pack('<I',9)
    assert body[:8]==b'MMPD'+hdr
    streams=collections.defaultdict(bytearray)
    p=8
    while p<len(body):
        tag,n=struct.unpack_from('<BI',body,p);p+=5
        assert tag in (0,1,2) and 0<n<=len(body)-p
        streams[tag].extend(body[p:p+n]);p+=n
    assert [streams[t][:8] for t in range(3)]==[m+hdr for m in (b'MMES',b'MMSD',b'MMSI')]
    events,data,index=(streams[t] for t in range(3))
    by_virt=dict(struct.iter_unpack('<QQ',index[8:]))
    @functools.lru_cache(None)
    def string(i):
        pos=by_virt[i] if i<100000003 else i-100000003
        assert 8<=pos<len(data)
        out=bytearray()
        while data[pos]!=255:
            if data[pos]==254:
                out.extend(string(struct.unpack_from('<Q',data,pos+1)[0]));pos+=9
            else:
                out.append(data[pos]);pos+=1
        return bytes(out)
    modules=[]
    for kind,ident,tid,lo,hi,upper in struct.iter_unpack('<QQIIII',events[8:]):
        if string(kind)!=b'GenericActivity':continue
        text=string(ident)
        if text==b'codegen_module' or text.startswith(b'codegen_module\x1e'):
            fields=text.split(b'\x1e')
            assert len(fields)==3 and fields[2].isdigit(),fields
            modules.append(fields[1].decode())
    assert modules and len(modules)==len(set(modules)), modules
    return {'sha':hashlib.sha256(body).hexdigest(),'physical_codegen':sorted(modules)}

def record(d):
    result=json.loads((d/'result.json').read_bytes())
    profile,=result['profile']
    row=read_profile(d.parent/profile)
    assignments=collections.defaultdict(list)
    stdout=(d/'stdout').read_bytes()
    for name,unit in re.findall(rb'^MONO_ITEM (.*?) @@ ([^\[\n]+)\[(?:Internal|External)\]$',stdout,re.M):
        assignments[unit.decode()].append(name.decode())
    assert set(row['physical_codegen']) <= set(assignments)
    for name in ['opaque::payload','pure::value']:
        assert sum('fn '+name in names for names in assignments.values())==1
    return row | {'product':result,'assignments':dict(assignments),'stdout_sha':hashlib.sha256(stdout).hexdigest()}

if __name__=='__main__':
    root=Path.cwd()
    rows={p.name:record(p) for p in sorted(root.glob('guard-*')) if p.is_dir()}
    with (root/'signed-equal-time-control.json').open('x') as out:json.dump(rows,out,indent=2);out.write('\n')
    for label,row in rows.items():
        print(label,len(row['physical_codegen']),len(row['assignments']),row['product']['result'])
