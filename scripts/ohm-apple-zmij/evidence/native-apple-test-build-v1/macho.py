"""Check each signed image page before treating observed Cargo N_OSO paths as equivalent."""
import hashlib
import re
import struct
from pathlib import PurePosixPath

TOKEN=re.compile(rb"/workspaces/([0-9a-f]{16})/v2-([0-9a-f]{16})/")
sha=lambda b:hashlib.sha256(b).hexdigest()
le=lambda fmt,d,i:struct.unpack_from("<"+fmt,d,i)
be=lambda fmt,d,i:struct.unpack_from(">"+fmt,d,i)
NEW=b"0"*16

def directories(image):
    magic,cpu,_,typ,n,size,_,_=le("8I",image,0)
    assert (magic,cpu,typ)==(0xfeedfacf,0x0100000c,2)
    commands={};sections={};i=32
    for _ in range(n):
        c,l=le("II",image,i);assert l>=8 and i+l<=32+size
        commands.setdefault(c,[]).append((i,l))
        if c==0x19:
            count,=le("I",image,i+64);assert l==72+80*count
            for j in range(count):
                sec=i+72+80*j
                name,seg,_,sz,off=le("16s16sQQI",image,sec)
                if off and sz:
                    key=seg.rstrip(b"\0").decode()+","+name.rstrip(b"\0").decode()
                    assert key not in sections and off+sz<=len(image)
                    sections[key]=(off,sz,sha(image[off:off+sz]))
        i+=l
    assert i==size+32
    (sym,_),=commands[2];(sig,_),=commands[0x1d];(uuid,_),=commands[0x1b]
    symoff,count,strings,string_bytes=le("4I",image,sym+8)
    off,sigsize=le("II",image,sig+8);assert off+sigsize==len(image)
    smagic,ssize,sblobs=be("3I",image,off);assert smagic==0xfade0cc0 and 0<=sigsize-ssize<16 and sblobs==1
    tag,cd=be("2I",image,off+12);cd+=off;assert tag==0 and cd==off+20 and not any(image[off+ssize:off+sigsize])
    cmagic,clen,ver,flags,hashoff,ident,special,pages,limit,word,alg,platform,lg=be("9I4B",image,cd)
    assert cmagic==0xfade0c02 and ver==0x20400 and flags==0x20002 and alg==2 and word==32 and platform==0 and special==0
    assert 0<ident<hashoff and cd+hashoff+pages*word==cd+clen==off+ssize and limit==off and lg==12
    span=1<<lg;assert pages==(limit+span-1)//span
    return {'commands':commands,'header_end':i,'sections':sections,'uuid':uuid+8,'sym':(symoff,count,strings,string_bytes),'page':(pages,span,limit,cd+hashoff)}

def checked_slots(body,d,replace=False):
    pages,span,limit,h=d['page'];out=bytearray(body)
    for i in range(pages):
        at=h+i*32;b=hashlib.sha256(body[i*span:min(limit,(i+1)*span)]).digest()
        if replace:out[at:at+32]=b
        else:assert body[at:at+32]==b,(i,"original CodeDirectory slot does not authenticate its page")
    return bytes(out)

def audit(image,ld,returned=None):
    d=directories(image);checked_slots(image,d);off,count,strings,sbytes=d['sym'];q=bytearray(image);names=[];slots=[];members=0
    result,=[ld[i+1] for i,a in enumerate(ld) if a=="-o"]
    assert returned is None or returned==result
    output_key,=list(TOKEN.finditer(result.encode()))
    owner={}
    for idx,typ,sect,desc,value in struct.iter_unpack("<IBBHQ",image[off:off+count*16]):
        assert idx<sbytes
        owner.setdefault(idx,[]).append((typ,sect,desc,value))
    for j in range(count):
        pos=off+j*16;s,t,_,_,_=le("IBBHQ",image,pos)
        if t!=0x66:continue
        n=strings+s;end=image.index(0,n,strings+sbytes);path=image[n:end];hit=list(TOKEN.finditer(path))
        if not hit:continue
        match,=hit
        assert (match[1],match[2])==(output_key[1],output_key[2]) and path.startswith(result.encode()[:output_key.end()])
        assert sorted(i for i in owner if s<=i<s+len(path))==[s]
        assert all(x==(0x66,0,1,0) for x in owner[s])
        obj=re.fullmatch(rb"(.+\.rlib)\(([^/()]+)\)",path);operand=obj[1] if obj else path
        assert ld.count(operand.decode())==1,"N_OSO value is not one literal linker input"
        members+=int(bool(obj))
        # More restrictive than masking the whole path: preserve the first workspace key,
        # slash delimiters, prefix, archive member (if any) and every other original byte.
        a,b=n+match.start(2),n+match.end(2);assert b-a==16
        q[a:b]=NEW;slots.append((a,b));names.append((match[1].decode(),match[2].decode(),PurePosixPath(operand.decode()).name,sha(path)))
    assert len(set((w,k) for w,k,_,_ in names))==1 and len(slots) in (29,30)
    result=checked_slots(q,d,replace=True)
    checked_slots(result,d)
    return result,{"layout":d,"slots":slots,"names":names,"archive_members":members}
