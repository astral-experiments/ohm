"""Read selected signed d57fd151 dep-graph nodes and their actual ordered edges without allocating the whole graph as Python objects."""
from contextlib import contextmanager
from pathlib import Path
import gzip,hashlib,json,mmap,re,shutil,struct,tempfile
D=Path(__file__).resolve().parent
kind_data=(D/'signed-kinds.txt').read_bytes()
assert hashlib.sha256(kind_data).hexdigest()=='a92cfdd978008b0bea9c0aaee9fe94c34bb56d5283e09c3170ce745796835574'
NAMES=kind_data.decode('ascii').splitlines()
assert len(NAMES)==len(set(NAMES))==365 and NAMES[5]=='CompileCodegenUnit'
def sha(p):
    with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def stable(raw):return ''.join(f'{i:016x}'for i in struct.unpack('<QQ',raw))
def leb(data,p,limit):
    x=0
    for i in range(10):
        assert p<limit;v=data[p];p+=1;x|=(v&127)<<(7*i)
        if v<128:return x,p
    raise ValueError('invalid LEB128')
@contextmanager
def file(path):
    if path.suffix=='.gz':
        with tempfile.TemporaryFile()as f, gzip.open(path,'rb')as z:
            shutil.copyfileobj(z,f,length=256*1024);f.flush()
            with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)as mm:yield mm
    else:
        with path.open('rb')as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)as mm:yield mm
def header(raw):
    assert raw[:6]==b'RSIC'+struct.pack('<H',26655) and raw[-13:]==b'rust-end-file'
    pos=7+raw[6]
    assert raw[7:pos]==b'1.99.0-dev (d57fd1515 2026-11-02) (ohm-1.99.0-23)'
    return pos,len(raw)-13
def graph(path,indices=(),keys=(),all_cgus=False):
    indices=set(indices);keys=set(keys);rows={};bits=(len(NAMES)-1).bit_length()
    with file(path)as raw:
        p,end=header(raw)
        args=raw[p:p+8].hex();p+=8
        mx,count,edge_count=struct.unpack_from('<QQQ',raw,end-24)
        assert 0<count<=mx<=2**31 and count*38<=end-p
        graph_end=end-24
        index=False
        if end>=48 and raw[end-32:end-24]==b'OHMIDX01':
            start,root_n=struct.unpack_from('<QQ',raw,end-48)
            assert root_n<=count and start>=p+count*38 and start+mx*8+root_n*4==end-48
            graph_end=start;index=True
        seen=bytearray((mx+7)//8);counts=[0]*len(NAMES);edges_read=0
        for _ in range(count):
            assert p+38<=graph_end
            head,idx=struct.unpack_from('<HI',raw,p);kind=head&((1<<bits)-1);assert 0<kind<len(NAMES) and idx<mx
            counts[kind]+=1;byte,bit=divmod(idx,8);assert not (seen[byte]>>bit)&1;seen[byte]|=1<<bit
            width=((head>>bits)&3)+1;num=(head>>(bits+2))-1;h=p;p+=38
            if num<0:num,p=leb(raw,p,graph_end)
            limit=p+width*num;assert limit<=graph_end
            chosen=idx in indices or (all_cgus and kind==5)
            key=stable(raw[h+6:h+22])if chosen or keys else None
            if chosen or (kind,key) in keys:
                edges=[int.from_bytes(raw[i:i+width],'little')for i in range(p,limit,width)]
                assert all(x<mx for x in edges)
                rows[idx]=dict(index=idx,kind=kind,name=NAMES[kind],key=key,value=stable(raw[h+22:h+38]),edges=edges)
            p=limit;edges_read+=num
        for expected in counts:
            actual,p=leb(raw,p,graph_end);assert actual==expected,(actual,expected)
        session_count,p=leb(raw,p,graph_end)
        assert p==graph_end and edges_read==edge_count,(p,graph_end,edges_read,edge_count)
    return dict(session_count=session_count,node_max=mx,nodes=count,edges=edge_count,seek_index=index,commandline_hash=args),rows
def work(path):
    rows={}
    with file(path)as b:
        p,end=header(b);n,p=leb(b,p,end)
        def string():
            nonlocal p
            l,p=leb(b,p,end);assert p+l<end and b[p+l]==193
            s=b[p:p+l].decode();p+=l+1;return s
        for _ in range(n):
            assert p+16<end;key=stable(b[p:p+16]);p+=16;name=string();m,p=leb(b,p,end)
            f={}
            for j in range(m):
                ext=string();out=string();assert ext not in f;f[ext]=out
            assert key not in rows;rows[key]=dict(name=name,files=f)
        assert p==end
    return rows

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
