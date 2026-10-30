from pathlib import Path
import hashlib,json,mmap,struct,sys
def sha(x):return hashlib.sha256(x).hexdigest()
def image(mm):
    header=struct.unpack_from('<16sHHIQQQIHHHHHH',mm)
    ident,_,machine,_,_,pho,sho,_,_,psz,pnum,ssz,snum,namesid=header
    assert ident[:6]==b'\x7fELF\x02\x01' and machine==62 and psz==56 and ssz==64
    secs=[struct.unpack_from('<IIQQQQIIQQ',mm,sho+i*ssz) for i in range(snum)]
    no,ns=secs[namesid][4:6];name_table=mm[no:no+ns]
    def get(n):return name_table[n:name_table.index(0,n)].decode('ascii')
    info={};build_desc=None;rostr=None
    for i,x in enumerate(secs):
        name=get(x[0]);off,sz=x[4:6]
        assert off>=0 and sz>=0 and (x[1]==8 or off+sz<=len(mm))
        raw='' if x[1]==8 else sha(memoryview(mm)[off:off+sz])
        info[name]={'offset':off,'size':sz,'type':x[1],'flags':x[2],'sha256':raw,'entsize':x[9]}
        if name=='.rodata':rostr=sho+i*ssz+56
        if name=='.note.gnu.build-id':
            nsize,dsize,kind=struct.unpack_from('<III',mm,off)
            pos=off+12+((nsize+3)//4)*4
            assert kind==3 and mm[off+12:off+12+nsize]==b'GNU\0' and pos+dsize<=off+sz
            build_desc=pos,dsize
    phdr=[struct.unpack_from('<IIQQQQQQ',mm,pho+i*psz) for i in range(pnum)]
    return info,phdr,build_desc,rostr,sha(mm),len(mm)
