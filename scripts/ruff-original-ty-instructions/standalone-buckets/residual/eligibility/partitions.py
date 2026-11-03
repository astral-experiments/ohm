"""Decode the serialized MonoItemPartitions record in the original rustc query cache."""
import argparse,hashlib,json,struct,subprocess,zipfile
from pathlib import Path
def check(c,msg):
    if not c:raise ValueError(msg)
def leb(b,p):
    v=0;i=p
    while i<len(b)and i-p<10:
        a=b[i];v|=(a&127)<<(7*(i-p));i+=1
        if a<128:
            check(i==p+1 or a!=0,'noncanonical integer');return v,i
    raise ValueError('unterminated integer')
def preceding(b,end):
    i=end-1;check(b[i]<128,'no integer terminator')
    while i>0 and b[i-1]&128:i-=1
    v,p=leb(b,i);check(p==end,'reverse integer boundary');return v,i
def readstring(b,p):
    n,p=leb(b,p);check(0<n<1024*1024 and b[p+n]==193,'rustc terminated string')
    return b[p:p+n].decode(),p+n+1
def cache(z,state):
    record=json.loads(z.read(f'ordinary/{state}/project-session.json'));q=record['raw']['query-cache.bin']
    b=subprocess.check_output(['zstd','-qdc'],input=z.read('native/'+q['sha256']+'.zst'))
    check(len(b)==q['bytes']and hashlib.sha256(b).hexdigest()==q['sha256'],'unbound ordinary query cache')
    check(b[:6]==b'RSIC'+(24450).to_bytes(2,'little')and b[7:7+b[6]]==b'1.99.0-dev'and b[-13:]==b'rust-end-file','wrong compiler format')
    return b,record
def table(b,rec,version):
    names=sorted(n[:-2]for n in rec['objects']);check(len(names)==245 and len(set(names))==245,'physical WIPs')
    starts=[];offsets={}
    for name in names:
        raw=name.encode();hits=[];p=-1
        while (p:=b.find(raw,p+1))>=0:hits.append(p)
        check(len(hits)==version+1,(name,hits));offsets[name]=hits;starts.append(hits[-1])
    check(starts==sorted(starts),'missing serialized order')
    first=starts[0]-2;n,beg=preceding(b,first);check(n==len(names),'missing actual vector count')
    tagged=[]
    for i in range(beg-10,beg):
        try:
            dep,q=leb(b,i)
            if q==beg:tagged.append((i,dep))
        except ValueError:pass
    check(tagged,'missing query record tag')
    footer=struct.unpack_from('<Q',b,len(b)-21)[0];check(starts[-1]<footer<len(b)-21,'footer bounds')
    # The last skipped field is the serialized DefIdSet. CacheEncoder writes each DefId as exactly
    # 16 bytes of DefPathHash. Query values end with a length covering both the dep index and value.
    candidates=[]
    for pos in range(starts[-1]+26,min(footer,starts[-1]+100000)):
        if b[pos-1]not in(0,1)or b[pos-2]not in(0,1):continue
        try:
            count,p=leb(b,pos)
            if not 0<count<50000:continue
            end=p+16*count
            if end>=footer:continue
            length,stop=leb(b,end)
            for start,dep in tagged:
                if length==end-start:
                    ids=[b[j:j+16]for j in range(p,end,16)]
                    if len(set(ids))==count:candidates.append((pos,count,start,dep,stop))
        except (IndexError,ValueError):pass
    check(len(candidates)==1,('nonunique end of typed record',candidates));after,last_count,start,dep,stop=candidates[0]
    rows={}
    for i,name in enumerate(names):
        p=starts[i];check(b[p-2:p]==b'\0\x19'and b[p+25:p+28]==b'\xc1\1\0','real Symbol and Some(symbol)')
        sym,p=readstring(b,p+28);check(sym.startswith('_R'),'native CGU symbol');count,p=leb(b,p);check(0<count<100000,'bounded MonoItems')
        end=starts[i+1]-2 if i+1<len(starts)else after
        check(b[end-2]in(0,1)and b[end-1]in(0,1),'two trailing CGU flags')
        weight,we=preceding(b,end-2);check(0<weight<2**40 and p<we,'invalid cached MIR sum')
        rows[name]={'name_offset':starts[i],'items':count,'items_start':p,'items_end':we,'size':weight,'primary':bool(b[end-2]),'dead_code_coverage':bool(b[end-1]),'encoded_symbol':sym}
    return {'table_count':len(rows),'tagged_query_index':dep,'tagged_from':start,'tagged_until':stop,'all_mono_def_ids':last_count,'prior_record_name_occurrences':version,'sha256':hashlib.sha256(b).hexdigest(),'rows':rows}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--write-caches-to',type=Path);a=p.parse_args()
    with a.archive.open('rb')as src:check(hashlib.file_digest(src,'sha256').hexdigest()=='5d63df07b51a860e1f0f364f877d222ddbf3d850465e374204cc0af4a09176aa','unregistered archive')
    z=zipfile.ZipFile(a.archive);r={}
    for n,ver in (('old',0),('edit',1)):
        b,rec=cache(z,n);r[n]=table(b,rec,ver)
        if a.write_caches_to:(a.write_caches_to/f'partition-{n}-query-cache.bin').write_bytes(b)
    a.output.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    print([(s,v['tagged_query_index'],v['all_mono_def_ids'],len(v['rows']),max(q['size']for q in v['rows'].values()))for s,v in r.items()])
