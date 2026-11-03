"""Independently decode the original full ELF from the existing ZIP in two constant-memory passes."""
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from threading import Thread
from zipfile import ZipFile
import hashlib
import json
import shutil
import struct
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from elf_container import signed_blake3
D=Path(__file__).resolve().parent
@contextmanager
def content(z,name):
    with z.open(name)as entry:
        proc=subprocess.Popen(['zstd','-dqc','-M64MB'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
        def feed():
            try:shutil.copyfileobj(entry,proc.stdin,128<<10)
            finally:proc.stdin.close()
        t=Thread(target=feed);t.start()
        try:yield proc.stdout
        finally:
            for _ in iter(lambda:proc.stdout.read(128<<10),b''):pass
            t.join();assert proc.wait()==0;proc.stdout.close()
def decode(z,name,lib,mutate=False):
    with content(z,name)as f:
        h=f.read(64);eh=struct.unpack('<16sHHIQQQIHHHHHH',h);assert eh[0][:6]==b'\x7fELF\2\1' and eh[2]==62 and eh[11]==64
        size=64;shoff,n,id_=eh[6],eh[12],eh[13];raw=bytearray()
        while x:=f.read(128<<10):
            l=max(size,shoff);r=min(size+len(x),shoff+64*n)
            if l<r:raw.extend(x[l-size:r-size])
            size+=len(x)
        assert len(raw)==64*n
        rows=[struct.unpack_from('<IIQQQQIIQQ',raw,i*64)for i in range(n)];nm=rows[id_];names=bytearray()
    with content(z,name)as f:
        size2=0
        while x:=f.read(128<<10):
            l=max(size2,nm[4]);r=min(size2+len(x),nm[4]+nm[5])
            if l<r:names.extend(x[l-size2:r-size2])
            size2+=len(x)
        assert size2==size and len(names)==nm[5]
    names=bytes(names)
    ids=[names[r[0]:].split(b'\0',1)[0].decode()for r in rows];order=sorted([(r[4],r[5],i)for i,r in enumerate(rows)if r[5]and r[1]!=8])
    push,finish=signed_blake3(lib);full=hashlib.sha256();gap_digest=hashlib.sha256();end=0;budget=0;sections={};desc=None
    with content(z,name)as f:
        for off,num,i in [*order,(size,0,None)]:
            n=off-end;assert 0<=n<4<<20
            if n:
                seg=f.read(n);assert len(seg)==n;push(seg);full.update(seg);gap_digest.update(struct.pack('<QQ',end,n)+seg);budget+=n
            end=off+num
            if i is None:break
            sec=hashlib.sha256();label=ids[i]
            for j in range(0,num,128<<10):
                x=f.read(min(num-j,128<<10));assert len(x)==min(num-j,128<<10)
                if mutate and label=='.text'and j==0:x=bytes([x[0]^1])+x[1:]
                full.update(x);sec.update(x)
                if label=='.note.gnu.build-id':
                    assert i is not None and len(x)==48 and struct.unpack('<III',x[:12])==(4,32,3)and x[12:16]==b'GNU\0';desc=x[16:].hex();push(b'\0'*48)
                else:push(x)
            sections[label]=sec.hexdigest()
        assert not f.read(1)
    pre=finish()
    return dict(sha256=full.hexdigest(),size=size,complete_zeroed_b3=pre,gnu_descriptor=desc,
                stamped_hash_matches=pre==desc,section_count=len(rows),complement_bytes=budget,complement_sha_with_ranges=gap_digest.hexdigest(),
                section_headers=list(zip(ids,rows)),sections=sections)
if __name__=='__main__':
    p=Path(sys.argv[1]);lib=Path(sys.argv[2]);root=Path(sys.argv[3])
    with p.open('rb')as original:assert hashlib.file_digest(original,'sha256').hexdigest()=='2ab6618f9f643f0c2ef9c192192c3b4955fe02f378432c8c28f01f8f8718f677'
    with ZipFile(p)as z:
        reg={}
        for verdict,sha in [('old','f203086dc58594dc33899d25dcbdcd5ec86d04e3dfb493efe7c7a59f6abd97e2'),('new','86b94323a752a316a501f542a846408648ca8b74c56bc60298690b671b7b0563')]:
            key=sha+'.elf.zst';j=decode(z,key,lib);assert j['sha256']==sha and j['stamped_hash_matches'];reg[verdict]=j
            if verdict=='new':
                negative=decode(z,key,lib,True);assert negative['sha256']!=sha and not negative['stamped_hash_matches'] and negative['gnu_descriptor']==j['gnu_descriptor'];reg['changed_text_refused']={k:negative[k]for k in ('sha256','complete_zeroed_b3','stamped_hash_matches','gnu_descriptor')}
    root.write_text(json.dumps(reg,sort_keys=True,indent=2)+'\n')
