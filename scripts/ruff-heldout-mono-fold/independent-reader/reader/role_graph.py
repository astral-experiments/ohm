"""Tie real contributor CGU dep-nodes to rustc work-product files in either registered format."""
from array import array
import hashlib,json,mmap,struct
from pathlib import Path

MASK=(1<<64)-1

def need(cond, why):
    if not cond:raise ValueError(why)

def sip(data):
    """LLVM is uninvolved: rustc-stable-hash 0.1.2's zero-key SipHash-1-3 with 128-bit output."""
    a,b,c,d=0x736f6d6570736575,0x646f72616e646f6d^0xee,0x6c7967656e657261,0x7465646279746573
    def rot(x,n):return ((x<<n)|(x>>(64-n)))&MASK
    def run(a,b,c,d):
        a=(a+b)&MASK;b=rot(b,13)^a;a=rot(a,32);c=(c+d)&MASK;d=rot(d,16)^c;a=(a+d)&MASK;d=rot(d,21)^a;c=(c+b)&MASK;b=rot(b,17)^c;c=rot(c,32);return a,b,c,d
    end=len(data)//8*8;tail=data[end:];words=[w[0]for w in struct.iter_unpack('<Q',data[:end])]+[int.from_bytes(tail,'little')|((len(data)&255)<<56)]
    for w in words:a,b,c,d=run(a,b,c,d^w);a^=w
    c^=0xee
    for _ in range(3):a,b,c,d=run(a,b,c,d)
    low=a^b^c^d;b^=0xdd
    for _ in range(3):a,b,c,d=run(a,b,c,d)
    return f'{low:016x}{a^b^c^d:016x}'

def cgu_key(name):
    bs=name.encode();return sip(struct.pack('<Q',len(bs))+bs)

def product_key(name):return sip(name.encode()+b'\xff')

def stable(data):return ''.join(f'{n:016x}'for n in struct.unpack('<QQ',data))

def leb(data,pos,end):
    v=0
    for shift in range(0,35,7):
        need(pos<end,'truncated LEB128');b=data[pos];pos+=1;v|=(b&127)<<shift
        if b<128:return v,pos
    raise ValueError('overlong number')

def header(raw,fmt,version='1.99.0-dev'):
    need(raw[:4]==b'RSIC' and struct.unpack_from('<H',raw,4)[0]==fmt and raw[7:7+raw[6]].decode()==version and raw[-13:]==b'rust-end-file','different role format/version');return 7+raw[6],len(raw)-13

def products(path,fmt,version='1.99.0-dev'):
    raw=path.read_bytes();p,end=header(raw,fmt,version);size,p=leb(raw,p,end);keys={}
    def string():
        nonlocal p
        l,p=leb(raw,p,end);need(p+l<end and raw[p+l]==193,'invalid filename');s=raw[p:p+l].decode();p+=l+1;return s
    for _ in range(size):
        pid=stable(raw[p:p+16]);p+=16;name=string();n,p=leb(raw,p,end);files={}
        for _ in range(n):
            ext=string();f=string();need(ext not in files and Path(f).name==f,'unsafe or duplicate file');files[ext]=f
        ck=cgu_key(name);need(pid==product_key(name) and ck not in keys,'different physical product hash');keys[ck]=dict(name=name,product=pid,files=files)
    need(p==end,'extra work products');return keys

def graph(path,fmt,names,query=None,chosen_indices=(),observe_kinds=(),version='1.99.0-dev'):
    bits=(len(names)-1).bit_length();mask=(1<<bits)-1;selection=set(chosen_indices);cgu=names.index('CompileCodegenUnit');owner=names.index('upstream_monomorphizations_for') if 'upstream_monomorphizations_for' in names else None;raw_query=struct.pack('<QQ',int(query[:16],16),int(query[16:],16)) if query else None
    roots={};hits={};selected={};nowner=0;observed={names.index(k) for k in observe_kinds}
    with path.open('rb')as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)as raw:
        begin,end=header(raw,fmt,version);begin+=8;slots,nodes,total=struct.unpack_from('<QQQ',raw,end-24);need(0<nodes<=slots<=3_000_000 and total<=20_000_000,'graph outside bounded scope');limit=end-24
        if raw[end-32:end-24]==b'OHMIDX01':limit=struct.unpack_from('<Q',raw,end-48)[0]
        reachable=bytearray(slots);next_hop=array('i',[-1])*slots;bits_seen=bytearray(slots);counts=[0]*len(names)
        allpasses=[]
        for visit in range(65):
            pos=begin;changed=0;nedges=0
            for _ in range(nodes):
                h=pos;word,idx=struct.unpack_from('<HI',raw,pos);typ=word&mask;w=((word>>bits)&3)+1;n=(word>>(bits+2))-1;pos+=38
                if n<0:n,pos=leb(raw,pos,limit)
                after=pos+n*w;need(after<=limit,'edge overflow')
                if visit==0:
                    need(0<typ<len(names) and idx<slots and not bits_seen[idx],'invalid sparse node');bits_seen[idx]=1;counts[typ]+=1;nedges+=n
                    if typ==owner:nowner+=1
                    match=typ==owner and raw_query is not None and raw[h+6:h+22]==raw_query
                    if match or idx in selection or typ==cgu or typ in observed:
                        row=dict(index=idx,kind=names[typ],key=stable(raw[h+6:h+22]),value=stable(raw[h+22:h+38]));selected[idx]=row
                        if typ==cgu:roots[row['key']]=idx
                        if match:hits[idx]=row;reachable[idx]=1
                elif not reachable[idx]:
                    while pos<after:
                        child=int.from_bytes(raw[pos:pos+w],'little');pos+=w
                        if reachable[child]:reachable[idx]=1;next_hop[idx]=child;changed+=1;break
                pos=after
            if visit==0:
                for count in counts:
                    observed,pos=leb(raw,pos,limit);need(observed==count,'invalid kind footer')
                _,pos=leb(raw,pos,limit);need(pos==limit and nedges==total and len(roots)==counts[cgu],'invalid graph/CGU inventory')
                if not hits:break
            else:
                allpasses.append(changed)
                if not changed:break
        need(not allpasses or allpasses[-1]==0,'owner reachability did not converge');paths={}
        for key,idx in roots.items():
            if reachable[idx]:
                chain=[idx]
                while chain[-1] not in hits:chain.append(next_hop[chain[-1]])
                paths[key]=chain
    return dict(nodes=nodes,edges=total,owner_count=nowner,roots=roots,hits=list(hits.values()),paths=paths,rows=selected)
