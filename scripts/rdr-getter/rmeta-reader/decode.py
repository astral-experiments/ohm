"""Offline signed-Ohm rmeta field attribution, no native code or writes outside the caller's output."""
import collections, functools, gzip, hashlib, json, re, subprocess, sys, zipfile
from pathlib import Path
SOURCE=Path('/home/dev-user/code/oss/ohm-rust-gnu-review-render-partitions-20261031')
PIN='c79998a5cd143c445a4b2528f20953b176a65c5d'
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from metadata_slots import Cursor, extract, need
BASE=Path(__file__).resolve().parent
ZIP=BASE.parent/'receipts/41189297097-13037628711-signed21-notebook-edit-compiler-ceiling.zip'
EXPECTED='4a2c78cd5ea191bb6e8d0f428cae1735637d4fd4750f2abf25e9dd2be5b1e8f4'
def sha(x): return hashlib.sha256(x).hexdigest()
def source(name):
    b=(ROOT/'source'/name).read_bytes()
    need(sha(b)==json.loads((ROOT/'source-hashes.json').read_bytes())[name], 'source SHA-256')
    return b.decode()
schema=source('compiler/rustc_metadata/src/rmeta/mod.rs')
spec=schema.split('\ndefine_tables! {',1)[1].split('\n}',1)[0]
tables=re.findall(r'^\s*([A-Za-z0-9_]+): Table<',spec,re.M)
need(len(tables)==len(set(tables))>60,'table schema')
defnames=source('compiler/rustc_hir_id/src/definitions.rs').split('pub enum DefPathData {',1)[1].split('\n}',1)[0]
keys=re.findall(r'^    (\w+)(\(Symbol\))?,',defnames,re.M)
need(len(keys)==17,'definition kinds')
class D(Cursor):
    def __init__(self,data,pos):super().__init__(data,pos);self.root=pos;self.prev=None
    def ptr(self):
        n=self.unsigned(); p=self.root-n if self.prev is None else self.prev+n
        need(1<=p<=self.root,'bad position');self.prev=p;return p
    def array(self):
        n=self.unsigned();return (n,self.ptr() if n else 1)
    def table(self):
        w,n=self.unsigned(),self.unsigned();return (self.ptr(),w,n)
def rmeta(data):
    old=extract(data);d=D(data,old['root'])
    need(d.unsigned()==0 and d.string()=='x86_64-unknown-linux-gnu','target');d.take(32)
    need(d.symbol()==old['owner'] and d.flag()==d.flag()==0,'wrong owner')
    need(d.string()==old['filename'] and d.take(8).hex()==old['stable_id'],'crate identity')
    if d.flag():need(d.unsigned() in range(3),'required panic')
    need(d.unsigned() in range(3) and d.unsigned() in range(5),'panic or edition')
    for _ in range(4): d.flag()
    for _ in range(13):d.array()
    need(d.unsigned() in (0,1),'impl kind');d.array();d.array();d.array()
    need(not d.flag(),'proc-macro');[d.array() for _ in range(5)];d.flag()
    t={name:d.table() for name in [*tables,'syntax_contexts','expn_data','expn_hashes']}
    d.ptr();t['source_map']=d.table();d.array();d.array()
    for _ in range(6):d.flag()
    need(d.unsigned() in range(3),'mangling');d.flag()
    need(d.flag()==d.flag()==1,'missing RDR')
    t['local']=d.table();t['expn']=d.table();gp=d.pos;d.take(16)
    need(d.take(13)==b'rust-end-file' and d.pos==len(data),'bad trailing CrateRoot')
    return t,gp,old
def entries(data,t):
    start,packed,n=t; w=packed&127
    need(n==0 or w>0,'empty nonzero-length table')
    if not packed&128:return {i:(start+i*w,data[start+i*w:start+(i+1)*w]) for i in range(n)}
    p=start+12*((n+63)//64);ret={};seen=0
    for bucket in range((n+63)//64):
        h=start+12*bucket;bm=int.from_bytes(data[h:h+8],'little');prev=int.from_bytes(data[h+8:h+12],'little')
        need(seen==prev and not bm>>min(64,n-64*bucket),'bad sparse index')
        for b in range(64):
            if (bm>>b)&1:
                ret[64*bucket+b]=(p+seen*w,data[p+seen*w:p+(seen+1)*w]);seen+=1
    return ret
def fingerprints(data,t):
    ret={}
    for i,(p,r) in entries(data,t).items():
        if any(r):
            need(len(r)==17 and r[0]==1,'invalid present fingerprint tag/width')
            ret[i]=(p+1,r[1:].hex())
    return ret
def definitions(data,t,crate):
    dt=entries(data,t['def_keys']);ht=entries(data,t['def_path_hashes'])
    @functools.lru_cache(None)
    def info(idx):
        val=int.from_bytes(dt[idx][1],'little');need(val>0,'zero DefKey');d=Cursor(data,val)
        parent=d.unsigned() if d.flag() else None;kind,name=keys[d.unsigned()]
        sym=d.symbol() if name else None
        dis=d.unsigned();part=sym[1] if sym and sym[0]=='str' else ('<sym:'+str(sym[1])+'>' if sym else '{'+kind+'}')
        if dis:part+='#'+str(dis)
        if parent is None:need(kind=='CrateRoot' and idx==0,'root key');path=crate
        else:need(parent!=idx,'self-parent');path=info(parent)[0]+'::'+part
        return (path,kind,val,data[val:d.pos].hex(),ht[idx][1].hex())
    return info,dt
def scan(z,st,cache):
    W=json.loads(gzip.decompress(z.read('T/'+st+'/work-products.json.gz')))
    res={}
    for crate,o in W.items():
        s=o['meta']['cargo']['sha256']
        if s not in cache:
            blob=gzip.decompress(z.read('metadata-cas/'+s+'.gz'));need(sha(blob)==s,'CAS body')
            cache[s]=(blob,rmeta(blob))
        res[crate]=(s,cache[s])
    return res
def test_pair(crate,a,b):
    ha,(A,(t,g,x))=a; hb,(B,(u,h,y))=b
    need(len(A)==len(B) and g==h and t==u and x['roster']==y['roster'],'geometry')
    need(x['owner']==y['owner']==('str',crate),'issuer name')
    I,dt=definitions(A,t,crate);J,du=definitions(B,u,crate)
    change=[];alls={}; ds={}
    def add(k,pos,v,other,w):
        need(pos==other,'offset')
        if v!=w:change.append((pos,pos+16,k,v,w))
    for k,(p,v) in x['fields'].items():
        add(k,p,v,*y['fields'][k])
    for name in ('local','expn'):
        P=fingerprints(A,t[name]);Q=fingerprints(B,u[name]); need(P.keys()==Q.keys(),'reachability differs')
        alls[name]={i:(v[0],v[1],Q[i][1]) for i,v in P.items()}
        dif=[]
        for i,(pos,v) in P.items():
            oth,w=Q[i];add((name,i),pos,v,oth,w)
            if name=='local':
                need(I(i)==J(i),'DefKey changed')
            if v!=w:dif.append(i)
        ds[name]={'geometry':t[name],'present':len(P),'changed':len(dif),'distinct_values':len({(P[i][1],Q[i][1]) for i in dif})}
    add(('public_global_hash',),g,A[g:g+16].hex(),h,B[h:h+16].hex())
    change.sort(); end=0;counts=collections.Counter();unmatched=[]
    for p,q,k,v,w in change:
        need(end<=p<q<=len(A) and v==A[p:q].hex() and w==B[p:q].hex(),'field proof')
        if A[end:p]!=B[end:p]:unmatched.append([end,p])
        end=q
        counts[k[0]]+=sum(a!=b for a,b in zip(A[p:q],B[p:q]))
    if A[end:]!=B[end:]:unmatched.append((end,len(A)))
    need(not unmatched,('unclassified changes',unmatched[:5]))
    def nar(i,row):
        pos,v,w=row;path,kind,kp,kraw,dh=I(i)
        return dict(id=i,path=path,kind=kind,range=[pos,pos+16],raw=[v,w],def_key_offset=kp,def_key=kraw,def_path_hash=dh)
    defs={i:nar(i,v) for i,v in alls['local'].items()}
    highlight=[p for p in defs.values() if any(q in p['path'] for q in ('VendoredFileSystem','file_system','SOURCE_COMMIT','TYPESHED','SourceKind','SourceMap'))]
    out={'bytes':len(A),'sha256':[ha,hb],'global':{'offset':g,'old':A[g:g+16].hex(),'new':B[g:g+16].hex()},'counts':ds,'changed_bytes':counts,'headers':[(k[2:] if len(k)>2 else k[1:],p,v,w) for p,_,k,v,w in change if k[0] in ('self','dep')], 'raw_diff_exactly_classified':True,'changed_bytes_total':sum(counts.values()),'root_item':defs.get(0),'highlight':highlight if crate=='ty_vendored' else highlight[:120]}
    return out,{'defs':list(defs.values()),'expn':alls['expn']}
def main():
    with ZIP.open('rb') as f:need(hashlib.file_digest(f,'sha256').hexdigest()==EXPECTED,'ZIP')
    with zipfile.ZipFile(ZIP) as z:
        reg=json.loads(z.read('registration.json'));need(reg['run']==41189297097 and reg['attempt']==1 and reg['head']=='42ab30fd5e6bcdcf908df81de9baac65ca64fbf9','wrong run')
        cache={}; states={st:scan(z,st,cache) for st in ('prior-repeat','edited','edit-repeat','restored','restore-repeat')}
        out={'zip_sha':EXPECTED,'source':PIN,'directions':{}};rows={}
        for before,after in (('prior-repeat','edited'),('edit-repeat','restored')):
            out['directions'][after]={};rows[after]={}
            for name in sorted(states[before]):
                old=states[before][name];new=states[after][name]
                q,allq=test_pair(name,old,new);out['directions'][after][name]=q;rows[after][name]=allq
                print(after,name,q['counts'],q['changed_bytes'],flush=True)
        for name,x in states['edited'].items():
            need(x[0]==states['edit-repeat'][name][0] and states['prior-repeat'][name][0]==states['restored'][name][0]==states['restore-repeat'][name][0],('repeat/repair',name))
    (BASE/'typed.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    (BASE/'definitions.json.gz').write_bytes(gzip.compress(json.dumps(rows,sort_keys=True,separators=(',',':')).encode(),mtime=0))
if __name__=='__main__':main()
