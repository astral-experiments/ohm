"""Read the complete GenericActivity intervals of rustc measureme 12's v9 stream."""
import collections
import functools
import struct

def activities(body):
    header=struct.pack('<I',9)
    assert body[:8]==b'MMPD'+header
    streams=collections.defaultdict(bytearray)
    pos=8
    while pos<len(body):
        tag,n=struct.unpack_from('<BI',body,pos);pos+=5
        assert tag in (0,1,2) and 0<n<=len(body)-pos
        streams[tag].extend(body[pos:pos+n]);pos+=n
    assert [streams[t][:8] for t in range(3)]==[m+header for m in (b'MMES',b'MMSD',b'MMSI')]
    events,data,index=(streams[t] for t in range(3))
    virtual=dict(struct.iter_unpack('<QQ',index[8:]))
    @functools.lru_cache(None)
    def string(key):
        i=virtual[key] if key<100000003 else key-100000003
        assert 8<=i<len(data)
        out=bytearray()
        while data[i]!=255:
            if data[i]==254:out.extend(string(struct.unpack_from('<Q',data,i+1)[0]));i+=9
            else:out.append(data[i]);i+=1
        return bytes(out)
    count=collections.Counter()
    observed=[]
    for kind,ident,tid,lo,hi,upper in struct.iter_unpack('<QQIIII',events[8:]):
        category=string(kind).decode();count[category]+=1
        if category!='GenericActivity':continue
        name=string(ident).decode().split('\x1e')[0]
        start=lo|((upper>>16)<<32);end=hi|((upper & 65535)<<32)
        if end >= (2**48 - 2):continue
        assert start<=end
        observed.append([name,tid,start,end])
    assert observed
    return count,observed

if __name__=='__main__':
    from pathlib import Path
    import json,sys
    counts,rows=activities(Path(sys.argv[1]).read_bytes())
    print(json.dumps([counts,sorted(rows,key=lambda r:r[3]-r[2],reverse=True)[:55]],indent=1))
