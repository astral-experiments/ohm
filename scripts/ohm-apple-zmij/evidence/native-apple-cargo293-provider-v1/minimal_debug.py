"""Locate byte differences between actual minimal-shell runtimes and their original independent native reference. These observations do not pass the original byte-identity requirement."""
import argparse,gzip,hashlib,json,re,struct
from pathlib import Path,PurePosixPath
from zipfile import ZipFile
sha=lambda b:hashlib.sha256(b).hexdigest()
le=lambda fmt,d,i:struct.unpack_from("<"+fmt,d,i)
be=lambda fmt,d,i:struct.unpack_from(">"+fmt,d,i)
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
    tag,cd=be("2I",image,off+12);cd+=off;assert tag==0
    cmagic,clen,ver,flags,hashoff,ident,special,pages,limit,word,alg,platform,lg=be("9I4B",image,cd)
    assert cmagic==0xfade0c02 and ver==0x20400 and flags&2 and alg==2 and word==32 and platform==0 and special==0
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

SUFFIX=re.compile(rb'\.([a-z0-9]{7})\.rcgu\.o\Z')

def layout_paths(image,ops):
    d=directories(image);checked_slots(image,d);sym,n,start,ssize=d['sym'];bindings={}
    for i,kind,sect,desc,value in struct.iter_unpack('<IBBHQ',image[sym:sym+16*n]):bindings.setdefault(i,[]).append((kind,sect,desc,value))
    paths={};at=start
    for entry in image[start:start+ssize].split(b'\0'):
        j=at-start;at+=len(entry)+1
        match=SUFFIX.search(entry)
        if not match or b'.rlink-objects/' not in entry:continue
        assert [off for off in bindings if j<=off<j+len(entry)]==[j] and all(x==(0x66,0,1,0) for x in bindings[j])
        assert ops.count(entry.decode())==1,(PurePosixPath(entry.decode()).name,ops[-9:])
        begin=start+j+match.start(1);paths[begin]=(entry[:match.start(1)]+b'<suffix>'+entry[match.end(1):],entry[match.start(1):match.end(1)])
    assert paths and at==start+ssize+1
    return d,paths

def compare(a,opa,b,opb):
    da,pa=layout_paths(a,opa);db,pb=layout_paths(b,opb);assert da==db and len(a)==len(b) and list(pa)==list(pb)
    q=bytearray(a);changed_names=0;source=0;slots=[]
    for i,(path,replay) in pa.items():
        other,want=pb[i];assert path==other;diff=sum(x!=y for x,y in zip(replay,want));source+=diff
        if diff:
            q[i:i+7]=want;changed_names+=1;slots.extend([i+j for j,(x,y) in enumerate(zip(replay,want)) if x!=y])
    rebuilt=checked_slots(q,da,replace=True);assert rebuilt==b
    assert changed_names and source;all_bytes=sum(x!=y for x,y in zip(a,b));assert all_bytes>source
    return {'warm':sha(a),'empty':sha(b),'different_bytes':all_bytes,'debug_symbol_bytes':source,'signature_bytes':all_bytes-source,'different_native_cgu_names':changed_names,'cgu_names':len(pa),
            'all_original_signed_pages':da['page'][0],'__text':da['sections']['__TEXT,__text'][2],'affected_pages':sorted(set(i//4096 for i in slots)),'normalized_only_for_diagnosis':True}

def measure(z):
    buckets={};image_to_argv={};visits={}
    for n in z.namelist():
        if not n.endswith('/verified.json'):continue
        if n.startswith(('provider-matrix/Rclean-','ruff-293/R/minimal-shell/')):
            path=n.removesuffix('/verified.json');raw=json.loads(z.read(n));cargo=path.startswith('provider-matrix/');rec=raw.get('image' if cargo else 'product')
            if not rec:continue
            h=rec['raw'];group='/'.join(path.split('/')[:2 if cargo else 3]);bucket='edge-images' if cargo else 'test-executables';buckets[group]=bucket
            ev=json.loads(gzip.decompress(z.read(path+'/exec.json.gz')))
            if cargo:root_ids={x['pid'] for x in raw['final_links']};args=[x['argv'] for x in ev if x['pid'] in root_ids and x['path'].endswith('/ld')]
            else:
                stream=list(map(json.loads,gzip.decompress(z.read(path+'/stdout.gz')).splitlines()));p,=[v['executable'] for v in stream if v.get('executable') and v['target']['name']=='ruff_python_ast']
                args=[x['argv'] for x in ev if x['path'].endswith('/ld') and [v for k,v in zip(x['argv'],x['argv'][1:]) if k=='-o']==[p]]
            if args:
                arg,=args;image_to_argv.setdefault((group,h),[]).append(arg)
            visits[path]=(h,raw.get('state'))
    results={}
    for path,(lh,state) in visits.items():
        cargo=path.startswith('provider-matrix/');group='/'.join(path.split('/')[:2 if cargo else 3]);
        if (cargo and not path.endswith('/warm')) or (not cargo and '/visit/' not in path):continue
        refpath=path.removesuffix('warm')+'empty' if cargo else group+'/empty-'+state+'/clean';rh=visits[refpath][0]
        if lh==rh:continue
        bx=buckets[group];read=lambda h:gzip.decompress(z.read(bx+'/'+h+'.macho.gz'))
        results[path]=compare(read(lh),image_to_argv[group,lh][0],read(rh),image_to_argv[group,rh][0])
    return results

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('zip',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    assert hashlib.file_digest(a.zip.open('rb'),'sha256').hexdigest()=='60fe0f0d2c85ffb2df304c27cb5823d50a266d4746619828db5388e298559668'
    with ZipFile(a.zip) as z:r=measure(z)
    out=(json.dumps(r,sort_keys=True,indent=2)+'\n').encode();assert not a.output.exists() or a.output.read_bytes()==out;a.output.write_bytes(out);print(len(r),'compared',sha(out))
