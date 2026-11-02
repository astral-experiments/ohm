"""Read selected signed 008a21ac dep-graph nodes and their actual ordered edges without allocating the whole graph as Python objects."""
from contextlib import contextmanager
from pathlib import Path
import gzip,hashlib,json,mmap,re,shutil,struct,tempfile
D=Path(__file__).resolve().parent
kind_data=(D/'dep-kinds.txt').read_bytes()
assert hashlib.sha256(kind_data).hexdigest()=='e641981dc943099a33fe24bd78b3645482859eb86b1fb4ab125b0cf4864ea898'
NAMES=kind_data.decode('ascii').splitlines()
assert len(NAMES)==len(set(NAMES))==362 and NAMES[5]=='CompileCodegenUnit'
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
    assert raw[:6]==b'RSIC\x0a\x00',('signed file header',raw[:7])
    pos=7+raw[6];ver=raw[7:pos].decode();assert '008a21ac0' in ver and raw[-13:]==b'rust-end-file'
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
def signed_names(sdk):
    with sdk.open('rb')as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)as m:
        assert m[:6]==b'\x7fELF\x02\x01';offset=struct.unpack_from('<Q',m,32)[0];size,count=struct.unpack_from('<HH',m,54);loads=[]
        for i in range(count):
            typ,_,off,va,_,filesize,_,_=struct.unpack_from('<IIQQQQQQ',m,offset+i*size)
            if typ==1:loads.append((va,va+filesize,off))
        def at(va):return next(o+va-lo for lo,hi,o in loads if lo<=va<hi)
        lens=at(0xe3aab0);table=0xe3ac1c;names=[]
        for i in range(len(NAMES)):
            n=m[lens+i];off=struct.unpack_from('<i',m,at(table)+4*i)[0];p=at(table+off);names.append(m[p:p+n].decode())
    assert names==NAMES,(len(names),[(i,a,b) for i,(a,b) in enumerate(zip(names,NAMES))if a!=b][:5]);return names
if __name__=='__main__':
    import sys
    if sys.argv[1]=='work':print(json.dumps(work(Path(sys.argv[2])),indent=2))
    else:
        h,rows=graph(Path(sys.argv[2]),indices=map(int,sys.argv[3:]),all_cgus=True);print(json.dumps(dict(summary=h,nodes=rows),indent=2))
