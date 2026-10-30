import hashlib
import struct
def sha(x):return hashlib.sha256(x).hexdigest()
def section(data):
    magic,cpu,_,kind,n,sz,_,_=struct.unpack_from('<8I',data)
    assert (magic,cpu)==(0xfeedfacf,0x0100000c) and kind in (1,2) and 32+sz<=len(data)
    pos=32;texts=[];uuid=[]
    for i in range(n):
        t,s=struct.unpack_from('<II',data,pos)
        assert s>=8 and pos+s<=32+sz
        if t==0x1b:uuid.append(data[pos+8:pos+24].hex())
        if t==0x19:
            count=struct.unpack_from('<I',data,pos+64)[0]
            assert s==72+count*80
            for k in range(count):
                name,seg,_,length,off=struct.unpack_from('<16s16sQQI',data,pos+72+k*80)
                if name.rstrip(b'\0')==b'__text' and seg.rstrip(b'\0')==b'__TEXT':
                    assert 0<length and off+length<=len(data)
                    texts.append(data[off:off+length])
        pos+=s
    assert pos==32+sz and len(texts)==1
    if kind==2:assert len(uuid)==1
    return kind,texts[0],uuid
def archive_objects(data):
    assert data.startswith(b'!<arch>\n')
    i=8;objects=[]
    while i<len(data):
        h=data[i:i+60];assert len(h)==60 and h[-2:]==b'\x60\n'
        n=int(h[48:58]);name=h[:16].strip()
        start=i+60;end=start+n;i=end+n%2;assert i<=len(data)
        if name.startswith(b'#1/'):
            l=int(name[3:]);name=data[start:start+l].rstrip(b'\0');start+=l
        body=data[start:end]
        if name.rstrip(b'/').endswith(b'.o'):objects.append((name,body))
    assert i==len(data)
    return objects
