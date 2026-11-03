"""Compare two independently saved full Ruff programs by actual ELF sections and changed symbolic addresses."""
import bisect,contextlib,hashlib,json,mmap,pathlib,shutil,struct,subprocess,sys,tempfile,zipfile
def need(ok,why):
    if not ok:raise ValueError(why)
def sh(b):return hashlib.sha256(b).hexdigest()
class Image:
 def __init__(self,f):
    self.m=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ);b=self.m
    need(b[:7]==b'\x7fELF\x02\x01\x01' and b[18:20]==b'\x3e\0','ELF machine')
    _,_,_,_,_,offset,_,_,_,_,width,count,index=struct.unpack_from('<HHIQQQI6H',b,16)
    need(width==64 and 0<index<count and offset+width*count<=len(b),'section header bounds')
    self.rows=[struct.unpack_from('<IIQQQQIIQQ',b,offset+i*width) for i in range(count)]
    n=self.rows[index];table=b[n[4]:n[4]+n[5]]
    self.sections={}
    for row in self.rows:
        end=table.index(b'\0',row[0]);name=table[row[0]:end].decode()
        need(name not in self.sections and (row[1]==8 or row[4]+row[5]<=len(b)),'section bounds')
        self.sections[name]=row
 def symbol_rows(self,points):
    a=self.sections['.symtab'];s=self.rows[a[6]]
    need(a[9]==24 and a[5]%24==0 and s[1]==3,'symbol table')
    positions=sorted(points);result={}
    for at in range(a[4],a[4]+a[5],a[9]):
        name,kind,other,section,address,length=struct.unpack_from('<IBBHQQ',self.m,at)
        found=bisect.bisect_left(positions,address)
        if found==len(positions) or positions[found]>=address+length:continue
        first=s[4]+name;end=self.m.find(b'\0',first,min(s[4]+s[5],first+65536));need(end>=first,'symbol string')
        text=self.m[first:end].decode(errors='replace');spots=[i-address for i in positions[found:bisect.bisect_left(positions,address+length)]]
        result[str(address)+' '+text]=spots[:64]
    return result
def main(path,digest,out):
 with path.open('rb')as f:need(hashlib.file_digest(f,'sha256').hexdigest()==digest,'original archive')
 need(int(next(l.split()[1]for l in pathlib.Path('/proc/meminfo').read_text().splitlines()if l.startswith('MemAvailable:')))*1024>8*2**30,'RAM floor')
 need(shutil.disk_usage(out.parent).free>15*2**30,'disk reserve')
 with zipfile.ZipFile(path)as z,contextlib.ExitStack()as stack:
    images=[];input_proof=[]
    for role in ('old','edit'):
        body=json.loads(z.read(role+'/products.json'))['elf'];need(0<body['size']<256*2**20,'bounded regular CLI')
        f=stack.enter_context(tempfile.TemporaryFile(dir=out.parent));raw=stack.enter_context(z.open('bodies/'+body['sha256']+'.zst'))
        proc=subprocess.Popen(['zstd','-dqc'],stdin=subprocess.PIPE,stdout=f)
        with proc.stdin as data:shutil.copyfileobj(raw,data,length=65536)
        need(proc.wait(timeout=60)==0 and f.tell()==body['size'],'full original ELF length');f.seek(0)
        need(hashlib.file_digest(f,'sha256').hexdigest()==body['sha256'],'full original ELF bytes')
        image=Image(f);stack.callback(image.m.close);images.append(image);input_proof.append(body)
    a,b=images;need(a.sections.keys()==b.sections.keys(),'different section sets')
    sections={};text_points=[];constants={}
    for name,v in a.sections.items():
        w=b.sections[name]
        if v[1]==8:continue
        if name=='.rodata':
            for j,(img,row) in enumerate(((a,v),(b,w))):
                for needle in (b'lint.line-length = 100',b'--config "line-length = 100"',b'--config "lint.line-length = 100"'):
                    p=row[4];at=[]
                    while True:
                        n=img.m.find(needle,p,row[4]+row[5])
                        if n<0:break
                        at.append(n-row[4]);p=n+len(needle)
                    constants['old new'.split()[j]+':'+needle.decode()]=at
            left=a.m[v[4]:v[4]+v[5]];right=b.m[w[4]:w[4]+w[5]]
            start=left.find(b'lint.line-length = 100');after=left.find(b'lint.line-length = 100',start+1)
            constants['sole_unqualified_edit_explains_every_rodata_byte']=(start>=0 and after<0 and left[:start]+left[start+5:]==right)
        if (v[1],v[2],v[3],v[5])!=(w[1],w[2],w[3],w[5]):
            sections[name]={'different_shape':True,'old':v,'new':w};continue
        xy=0;locations=[];runs=0;prev=-2
        for off in range(0,v[5],2048):
            m=min(2048,v[5]-off);left=a.m[v[4]+off:v[4]+off+m];right=b.m[w[4]+off:w[4]+off+m]
            if left==right:continue
            for i,(x,y)in enumerate(zip(left,right)):
                if x!=y:
                    p=off+i;xy+=1
                    if p!=prev+1:runs+=1
                    prev=p
                    if len(locations)<64:locations.append([p,x,y])
                    if name=='.text'and len(text_points)<512:text_points.append(v[3]+p)
        if xy:sections[name]={'bytes':v[5],'different_positions':xy,'different_runs':runs,'first':locations,'flags':v[2]}
    o={'input_archive':digest,'old_edit':input_proof,'section_counts':[len(x.sections)for x in images],'differences':sections,'source_literals':constants,
       'text_witness_limit':512,'symbol_names_at_first_old_text_witnesses':a.symbol_rows(text_points),'symbol_names_at_first_new_text_witnesses':b.symbol_rows(text_points)}
    out.write_text(json.dumps(o,sort_keys=True,indent=1)+'\n')
    print([(n,x.get('different_positions','shape'))for n,x in sections.items()]);print('native symbols',len(o['symbol_names_at_first_old_text_witnesses']))
if __name__=='__main__':main(pathlib.Path(sys.argv[1]),sys.argv[2],pathlib.Path(sys.argv[3]))
