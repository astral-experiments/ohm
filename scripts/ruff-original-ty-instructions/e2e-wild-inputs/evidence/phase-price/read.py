"""Independently re-open all real epoch and cutoff counters, every selected input and the array readback."""
from collections import Counter
from pathlib import Path
import ctypes,functools,gzip,hashlib,json,os,re,struct,sys,zipfile
D=Path(__file__).resolve().parent
def sha(b):return hashlib.sha256(b).hexdigest()
@functools.lru_cache(maxsize=1)
def hasher():
    dll=Path(os.environ.get('OHM_BLAKE3_LLVM','/run/ohm-ruff-option-28106-projection-20261102/signed-sdk/lib/libLLVM.so.23.1-rust-1.99.0-beta'))
    lib=ctypes.CDLL(str(dll));P=ctypes.c_void_p
    funcs=[lib.llvm_blake3_hasher_init,lib.llvm_blake3_hasher_update,lib.llvm_blake3_hasher_finalize]
    for f,sig in zip(funcs,[[P],[P,P,ctypes.c_size_t],[P,P,ctypes.c_size_t]]):f.argtypes=sig;f.restype=None
    def invoke(raw):
        state=(ctypes.c_uint64*512)();digest=(ctypes.c_ubyte*32)();funcs[0](state);funcs[1](state,raw,len(raw));funcs[2](state,digest,32);return bytes(digest).hex()
    assert invoke(b'')=='af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262'
    return invoke
def read(z,k):return json.loads(gzip.decompress(z.read(k))if k.endswith('.gz')else z.read(k))
def hw(z,label):
    v=read(z,'phase-price/'+label+'/hardware.json');assert v['status']==0 and v['instructions']>0 and v['running']==v['enabled']>0,(label,v);return v['instructions']
def get(z,label):return z.read('phase-price/'+label+'/stderr').decode().splitlines()
def native(z,roles):
    census=read(z,'current-observed/owner-census.json.gz');outer=census['outer'];assert outer[0]>0 and outer[1]==outer[2]>0 and outer[3]==0
    result={r['output']:[]for r in roles}
    for r in census['roles']:
        av=z.read('current-observed/tasks/'+r['argv']).decode().split('\0')[4:-1];hits={v if v in result else v.removesuffix('.rlink')for v in av if v in result or v.endswith('.rlink')and v.removesuffix('.rlink')in result}
        if not hits:continue
        assert len(hits)==1;p,=hits;result[p].append({'epoch':r['epoch'],'pid':r['pid'],'image':Path(r['path']).name,'trigger':r['trigger'],'counters':r['counter']})
    complete=set();refused=[]
    for p,rows in result.items():
        assert len(rows)==8 and Counter((r['image'],r['trigger'])for r in rows)==Counter((image,tr)for image in ('rustc','x86_64-linux-gnu-gcc-13','collect2','ld.bfd')for tr in ('exec','first'))
        for r in rows:
            n,e,t=r['counters']
            if e!=t or min(n,e,t)<=0:refused.append([p,r])
            if r['image']=='ld.bfd':assert n>0 and e==t and e>0
    wild=sum(r['counters'][0]for rows in result.values()for r in rows if r['image']=='ld.bfd')
    all_image_work=sum(row['counter'][0]for row in census['roles']);delta=outer[0]-all_image_work
    return result,outer,wild,refused,{'all_epochs':all_image_work,'difference':delta,'max_abs_difference':1_000_000,'conserved':abs(delta)<=1_000_000}
def scan(z,label,expect,compact=False):
    base='phase-price/'+label+'/';rec=hw(z,label);names=expect
    if not compact:
        obs=z.read(base+'paths.nul').split(b'\0');assert obs.pop()==b'' and list(map(os.fsdecode,obs))==names
    lines=z.read(base+'observed.txt').splitlines();assert len(lines)==len(names)
    result=[]
    for i,(p,l)in enumerate(zip(names,lines)):
        j,n,e,d,ino,h=l.split();assert int(j)==i and int(n)>=0 and int(d)>=0 and int(ino)>0 and re.fullmatch(b'[a-f0-9]{64}',h)
        result.append([p,int(n),int(e),int(d),int(ino),h.decode()])
    return rec,result
def main(zpath,expected,head,run,output):
    p=Path(zpath)
    with p.open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==expected
    z=zipfile.ZipFile(p);assert z.testzip()is None and len(z.namelist())==len(set(z.namelist()))
    orig=read(z,'registration.json');assert orig['head']==head and orig['run']==str(run)
    gate=read(z,'phase-price/gate.json');roles=read(z,'phase-price/roles.json');assert len(roles)==gate['roles']==50
    source=read(z,'phase-price/source.json');assert source['patch']=='2290a824f89a84692ffb756daf45c63c7417d4555e61268be012d792cd46cf8d' and source['lib_rs']=='3bb077ad012b626c654aed662245c144e7af94c5fb5d220351facf4d730fd6b0'
    inv=read(z,'current-observed/inventory.json.gz')['executables'];assert len(inv)==102
    nrows,outer,swild,refused,conservation=native(z,roles);hit=[];allpaths=[];payload={};per=[];primary=gate['primary']
    for i,r in enumerate(roles):
        tag=f'role-{i:02}';o=r['output'];rel='target/'+o.split('/target/',1)[1];expected_elf=inv[rel]['elf'];assert [expected_elf['bytes'],expected_elf['sha256']]==[r['bytes'],r['output_sha']]
        if r['full_emitted_sha']==r['output_sha']:hit.append(i)
        steps={m:hw(z,tag+'-'+m)for m in ('complete','paths','hash','sections')}
        audit=get(z,tag+'-audit');entries=[]
        for line in audit:
            if not line.startswith('QA_INPUT\t'):continue
            _,ns,h,path=line.split('\t');n=int(ns);assert re.fullmatch('[0-9a-f]{64}',h)and n>=0 and os.path.isabs(path)and path.isascii();entries.append([path,n,h])
            assert payload.setdefault(path,[n,h])==[n,h],('two actual native generations',path)
        root=next(v for v in audit if v.startswith('QA_CUT\t')).split('\t')[2:]
        assert [len(entries),sum(n for _,n,_ in entries),root[2]]==[int(root[0]),int(root[1]),r['input_root']]
        assert hasher()(b''.join(struct.pack('<Q',n)+bytes.fromhex(h)for _,n,h in entries))==root[2]
        assert r['input_entries']==len(entries)and r['input_bytes']==int(root[1])and any(x[0]==r['symbols']for x in entries)
        for mode in ('paths','hash','sections'):
            ends=[v.split('\t')for v in get(z,tag+'-'+mode)if v.startswith('QA_CUT\t')];assert len(ends)==1 and ends[0][1]==mode
            if mode=='hash':assert ends[0][2:]==root
        assert not any(v.startswith('QA_CUT\t')for v in get(z,tag+'-complete'))
        allpaths.extend(row[0]for row in entries);per.append({'name':Path(o).name,'output':o,'output_bytes':r['bytes'],'full_sha_equal':i in hit,'input_count':len(entries),'input_bytes':sum(x[1]for x in entries),'cuts':steps,'ordinary_epochs':nrows[o]})
        if i==primary:primary_paths=[v[0]for v in entries]
    assert len(hit)==gate['exact_complete_outputs']and primary in hit and len(primary_paths)==409
    unique=sorted(set(allpaths));outputs=[r['output']for r in roles];assert len(unique)==gate['unique']and len(allpaths)==gate['source_occurrences']and sum(payload[p][0]for p in unique)==gate['payload_bytes_unique']
    labels={'e2e-positive':primary_paths,'e2e-positive-reverse':primary_paths,'e2e-output':[outputs[primary]],'e2e-output-reverse':[outputs[primary]],'all-occurrences':allpaths,'unique-held':unique,'unique-held-reverse':unique,'all-outputs':outputs,'all-outputs-reverse':outputs,'compact-held-0':unique,'compact-held-1':unique}
    scans={};all_read={};held=None;outbytes={r['output']:[r['bytes'],r['output_sha']]for r in roles}
    for label,paths in labels.items():
        cost,rows=scan(z,label,paths,label.startswith('compact'));scans[label]={'instructions':cost,'count':len(rows),'bytes':sum(r[1]for r in rows),'lease_errno':dict(Counter(r[2]for r in rows))}
        for p,n,_,d,ino,h in rows:
            if p in payload:assert n==payload[p][0]
            if p in outbytes:assert outbytes[p]==[n,h]
            assert all_read.setdefault(p,[d,ino,n,h])==[d,ino,n,h]
        if label=='unique-held':held=rows
        if label=='unique-held-reverse'or label.startswith('compact'):assert rows==held
    ids={p:i for i,p in enumerate(unique)};digest=sha(b''.join(struct.pack('<I',ids[p])for p in allpaths))
    assert digest==gate['index_sha256']
    for label in ('compact-held-0','compact-held-1'):
        h=get(z,label)[0].split();assert h[:4]==['QA_INDEX',str(len(allpaths)),str(len(unique)),str(4*len(allpaths))]and h[5]==digest;assert int(h[4])==sum(len(os.fsencode(p))+1 for p in unique)
    assert sum(r['bytes']for r in roles)==gate['output_bytes']
    for role in roles:assert all_read[role['symbols']][3]==role['symbols_sha']
    rawsym=z.read('native-capture/symbols.o');assert hasher()(rawsym)==payload[roles[primary]['symbols']][1]and sha(rawsym)==roles[primary]['symbols_sha']

    primary_costs=per[primary]['cuts'];rev={mode:hw(z,'e2e-reverse-'+mode)for mode in ('hash','sections','paths')}
    sp=per[primary]['ordinary_epochs'];assert all(n>0 and e==t and e>0 for n,e,t in (r['counters']for r in sp))
    wc=sum(r['counters'][0]for r in sp if r['image']=='ld.bfd');ec=sum(r['counters'][0]for r in sp);ow=outer[0];non=ow-swild;en=ec-wc
    costs={m:sum(r['cuts'][m]for r in per)for m in ('complete','paths','hash','sections')};ccost=max(scans[l]['instructions']for l in ('compact-held-0','compact-held-1'));ocost=max(scans[l]['instructions']for l in ('all-outputs','all-outputs-reverse'));scost=max(scans[l]['instructions']for l in ('e2e-positive','e2e-positive-reverse'));o1=max(scans[l]['instructions']for l in ('e2e-output','e2e-output-reverse'))
    def scenarios(ordinary,other,values,outprice):
        return {k:{'component_sum':other+n,'headroom_to_2x':ordinary/2-other-n,'with_output_hash_sum':other+n+outprice,'with_output_hash_headroom':ordinary/2-other-n-outprice}for k,n in values.items()}
    S=scenarios(ow,non,{'load_compact_sha':costs['paths']+ccost,'sections_compact_sha':costs['sections']+ccost,'load_mapped_blake3_every':costs['hash'],'load_sha_every':costs['paths']+scans['all-occurrences']['instructions']},ocost)
    M=scenarios(ec,en,{'load_sha':max(rev['paths'],primary_costs['paths'])+scost,'sections_sha':max(rev['sections'],primary_costs['sections'])+scost,'load_mapped_blake3':max(rev['hash'],primary_costs['hash'])},o1)
    def end(k):return next(x for x in get(z,k)if x.startswith('QA_CUT\t')).split('\t')
    assert end('challenge-shadow')[4]!=end('challenge-four')[4]and end('challenge-shadow')[2:4]==end('challenge-four')[2:4]and end('challenge-repair')[4]==roles[primary]['input_root']
    for label in ('challenge-malformed-paths','challenge-malformed-sections'):
        messages=get(z,label);assert not any(l.startswith('QA_CUT\t')for l in messages)and any('libutil.a'in l or 'DELIBERATELY'in l or 'MALFORMED'in l for l in messages)
    result={'run':run,'head':head,'zip_sha256':expected,'boot':orig['boot'],'source':source,'admitted_complete_output_indices':hit,'all50_full_source_transfer':len(hit)==50,'unscaled_ordinary_wild':swild,'ordinary_census_outer':outer,'ordinary_census_conservation':conservation,'workspace_component_budgets_admitted':conservation['conserved']and len(hit)==50,'ordinary_other_budget':non,'ordinary_unusable_nonwild_epoch':refused,'single_e2e_chain':ec,'single_e2e_wild':wc,'matching_e2e_index':primary,'source_cut_sums':costs,'e2e_source_cut_reversal':rev,'scans':scans,'gate':gate,'workspace_component_sums':S,'e2e_component_sums':M,'e2e_output_validation':o1,'all_output_validation':ocost,'per_target':per}
    f=Path(output);f.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');print(sha(f.read_bytes()),'outputs',len(hit),len(per),'inputs',len(allpaths),len(unique))
if __name__=='__main__':main(sys.argv[1],sys.argv[2],sys.argv[3],int(sys.argv[4]),sys.argv[5])
