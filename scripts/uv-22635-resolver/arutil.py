"""Exact source-backed rlib comparison for the two named signed cold-control libraries."""
import re,struct
from model import require as need,digest
def enc(n):
    out=bytearray()
    while n>=128:out.append((n&127)|128);n>>=7
    return bytes(out)+bytes([n])
def ar(b):
    assert b.startswith(b'!<arch>\n');p=8;rows=[];long=None
    while p<len(b):
        h=b[p:p+60];assert h[58:]==b'`\n';n=h[:16].rstrip().decode();size=int(h[48:58]);v=b[p+60:p+60+size];assert len(v)==size
        if n=='//':long=v
        if n.startswith('/')and n[1:].isdigit():
            ix=int(n[1:]);end=long.index(b'/\n',ix);n=long[ix:end].decode()
        elif n not in ('/','//','/SYM64/'):n=n.removesuffix('/')
        rows.append((n,h,v,p+60));p+=60+size+(size%2)
    assert p==len(b);return rows
def sec(b):
    assert b[:6]==b'\x7fELF\x02\x01';header=struct.unpack_from('<16sHHIQQQIHHHHHH',b);off=header[6];sz=header[11];n=header[12];names=header[13];assert sz==64 and 0<names<n
    all0=[struct.unpack_from('<IIQQQQIIQQ',b,off+i*sz)for i in range(n)];txt=all0[names];strtab=b[txt[4]:txt[4]+txt[5]]
    name=lambda i:strtab[i:strtab.index(b'\0',i)].decode();return [(name(x[0]),x[1],x[2],int(x[4]),int(x[5]))for x in all0]
T={'ar':ar,'sec':sec,'sha':digest}
TOKEN=re.compile(r'^(.*\.)([a-z0-9]{7})(\.rcgu\.o)$')

def decompose(b):
    rows=T['ar'](b);objs=[(n,raw,pos) for n,header,raw,pos in rows if n.endswith('.rcgu.o')]
    names=[n for n,_,_ in objs];need(names and len(set(names))==len(names),'unique CGU objects')
    need([n for n,_,_,_ in rows if n not in names]==['/','//','lib.rmeta','lib.rmeta-link'],'additional archive member unsupported')
    logical=[];temps=set()
    for n in names:
        matched=TOKEN.fullmatch(n);need(matched,'CGU temp pattern');start,tok,end=matched.groups();need(int(tok,36)<=0xffffffff,'invocation-temp not a u32');logical.append(start+end);temps.add(tok)
    need(len(temps)==1 and len(set(logical))==len(logical),'not one fresh invocation affix')
    _,_,table,table_pos=next(e for e in rows if e[0]=='//')
    _,_,elf,elf_pos=next(e for e in rows if e[0]=='lib.rmeta-link')
    sec,= [e for e in T['sec'](elf) if e[0]=='.rmeta-link']
    _,_,_,off,size=sec
    # rustc_codegen_ssa/src/back/rmeta_link.rs: Vec<String>, Vec<Option<String>>, exact EOF.
    # For these particular archives there are zero bundled native libraries.
    long_names=b''.join(n.encode()+b'/\n'for n in names)
    encoded_link=enc(len(names))+b''.join(enc(len(n))+n.encode()+b'\xc1'for n in names)+b'\x00rust-end-file'
    need(long_names==table and elf[off:off+size]==encoded_link,'archive and independently encoded metadata member lists differ')
    return logical,temps.pop(),objs,(table_pos,long_names),(elf_pos+off,encoded_link)

def compare(a,b):
    l,t,objs,t1,s1=decompose(a);l2,t2,objs2,t_next,s_next=decompose(b)
    need(l==l2 and t!=t2 and len(a)==len(b),'different logical CGUs or input shape')
    need(all(x[1:]==y[1:] for x,y in zip(objs,objs2)),'changed machine object or archive location')
    res=bytearray(a)
    for (pos,old),(new,newv)in((t1,t_next),(s1,s_next)):
        need(pos==new and len(old)==len(newv),'container relocation')
        res[pos:pos+len(old)]=newv
    need(bytes(res)==b,'additional archive/header/ELF/symbol or embedded metadata change')
    return {'source_SHA256':[T['sha'](x)for x in(a,b)],'CGUs':len(l),'new_invocation_token':[t,t2],'byte_differences':sum(x!=y for x,y in zip(a,b)),'payload_bytes_and_ar_member_locations_identical':True,'original_complete_cold_archive_reconstructed':True,'paths':[['gnu-long-filenames',t1[0],len(t1[1])],['lib.rmeta-link ELF .rmeta-link',s1[0],len(s1[1])]]}
