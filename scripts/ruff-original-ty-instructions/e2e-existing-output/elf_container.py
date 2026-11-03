"""Cover every ELF byte without retaining large section payloads or another executable."""
from pathlib import Path
import base64
import ctypes
import hashlib
import os
import struct
def signed_blake3(llvm):
    api=ctypes.CDLL(str(llvm));ptr=ctypes.c_void_p
    h=api.llvm_blake3_hasher_init;h.argtypes=[ptr];h.restype=None
    u=api.llvm_blake3_hasher_update;u.argtypes=[ptr,ptr,ctypes.c_size_t];u.restype=None
    f=api.llvm_blake3_hasher_finalize;f.argtypes=[ptr,ptr,ctypes.c_size_t];f.restype=None
    state=(ctypes.c_uint64*512)();out=(ctypes.c_ubyte*32)();h(state);f(state,out,32)
    assert bytes(out).hex()=='af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262';h(state)
    def push(block):u(state,block,len(block))
    def finish():f(state,out,32);return bytes(out).hex()
    return push,finish
def inspect(path,lib):
    p=Path(path); size=p.stat().st_size;push,finish=signed_blake3(lib);full=hashlib.sha256()
    with p.open('rb')as f:
        def at(off,n):
            assert 0<=off<=size and 0<=n<=size-off
            f.seek(off);b=f.read(n);assert len(b)==n;return b
        header=struct.unpack('<16sHHIQQQIHHHHHH',at(0,64));assert header[0][:6]==b'\x7fELF\x02\x01' and header[2]==62 and header[11]==64
        shoff,ents,n,si=header[6],header[11],header[12],header[13];assert 0<si<n<256
        rows=[struct.unpack('<IIQQQQIIQQ',at(shoff+i*ents,ents))for i in range(n)];names=at(rows[si][4],rows[si][5])
        secs=[];layout=[]
        for idx,row in enumerate(rows):
            name=names[row[0]:].split(b'\0',1)[0].decode();off,num=row[4:6]
            secs.append({'index':idx,'section':name,'header':list(row)})
            if not num or row[1]==8:continue
            layout.append((off,num,idx,name))
        layout.sort();cursor=0;gaps=[];budget=0;buildid=None
        def gap(a,b):
            nonlocal budget
            if a==b:return
            assert 0<=a<b and budget+b-a<=4*2**20
            x=at(a,b-a);budget+=len(x);gaps.append([a,len(x),base64.b64encode(x).decode()]);push(x);full.update(x)
        for off,num,idx,name in layout:
            assert off>=cursor;gap(cursor,off);cursor=off+num
            section=hashlib.sha256()
            for i in range(0,num,1<<20):
                block=at(off+i,min(1<<20,num-i));section.update(block);full.update(block)
                if name=='.note.gnu.build-id':
                    assert buildid is None and len(block)==48 and struct.unpack('<III',block[:12])==(4,32,3) and block[12:16]==b'GNU\0'
                    buildid=block[16:].hex();push(b'\0'*len(block))
                else:push(block)
            secs[idx]['sha256']=section.hexdigest()
        gap(cursor,size);preimage=finish()
        assert buildid==preimage,(buildid,preimage)
        m=p.stat()
        return {'size':size,'sha256':full.hexdigest(),'dev':m.st_dev,'ino':m.st_ino,'hardlinks':m.st_nlink,'buildid':buildid,'zeroed_complete_buildid':preimage,'sections':secs,'complement_bytes':budget,'complete_complement':gaps}
def compare(a,b):
    assert [(i['index'],i['section'])for i in a['sections']]==[(i['index'],i['section'])for i in b['sections']]
    table=[(l['section'],i,v,w)for l,r in zip(a['sections'],b['sections']) for i,(v,w)in enumerate(zip(l['header'],r['header']))if v!=w]
    sections=[x['section']for x,y in zip(a['sections'],b['sections'])if x.get('sha256')!=y.get('sha256')]
    return {'entire_elf_equal':a['sha256']==b['sha256'],'different_section_headers':table,'different_section_payloads':sections,'complement_equal':a['complete_complement']==b['complete_complement'],'same_total_bytes':a['size']==b['size']}
