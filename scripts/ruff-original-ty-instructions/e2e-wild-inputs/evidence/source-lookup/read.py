"""Compare diagnostic source events with the separate signed link's actual kernel file timeline."""
from collections import Counter,defaultdict
import gzip,hashlib,json,os,re,stat,sys,zipfile
from pathlib import Path
D=Path(__file__).resolve().parent
sys.path.insert(0,str(D.parent if (D.parent/'reopen.py').is_file()else D.parent.parent/'ty-server-e2e-wild-29697-01'));import reopen as kernel
def read(z,k):return json.loads(z.read(k))
def hashf(p):
    with open(p,'rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def option(s):return None if s=='None'else json.loads(re.fullmatch(r'Some\((.*)\)',s)[1])
def open_rows(data):
    live={};requests=[];opens=[];probes=[];miss=[];unknown=[]
    for line in data.decode().splitlines():
        if not line.startswith('OHMLOOK\t'):continue
        fields=line.split('\t');kind,pid,thread=fields[1:4];key=pid,thread;vec=fields[4:]
        if kind in ('B','A'):
            assert key not in live
            if kind=='B':
                match=re.fullmatch(r'(File|Lib|Search|Framework)\((.*)\)',vec[0]);spec=[match[1],json.loads(match[2])];parent=option(vec[1]);first=option(vec[2]);mod=vec[3]
            else:spec=['Auxiliary',json.loads(vec[0])];parent=first=None;mod=''
            position=int(vec[4])if kind=='B'else None
            r={'spec':spec,'referrer':parent,'source_position':position,'search_first':first,'modifiers':mod,'probes':[]};live[key]=r;requests.append(r)
        elif kind=='P':
            p,e,mode=json.loads(vec[0]),int(vec[1]),int(vec[2]);assert e>=0
            assert (mode==0 if e else stat.S_ISREG(mode)),(p,e,mode)
            probes.append([p,e])
            if key in live:live[key]['probes'].append([p,e])
            else:unknown.append([p,e])
        elif kind=='E':
            r=live.pop(key);r['resolved']=option(vec[0])
        elif kind=='O':
            p=json.loads(vec[0]);dev,ino,n=map(int,vec[1:]);assert dev>=0 and ino>0 and n>=0;opens.append([p,dev,ino,n])
        elif kind=='X':miss.append([json.loads(vec[0]),option(vec[1])])
        else:raise AssertionError(kind)
    assert not live
    assert all(path.isascii() and "\0" not in path for path,_ in probes) and all(path.isascii()for path, *_ in opens)
    return requests,opens,probes,miss,unknown
def original_trace(z,stage):
    tids={};opened=set();negative=[];sizes=defaultdict(set);accepted=defaultdict(set)
    for k in z.namelist():
        if not(k.startswith(stage+'/syscalls/task.')and k.endswith('.gz')):continue
        tid=k.split('.')[-2];rows=[]
        raw=gzip.decompress(z.read(k)).decode();assert '<unfinished ...>'not in raw
        for no,s in enumerate(raw.splitlines()):
            fd=re.search(r' statx\(\d+<([^<>]+)>, "", [^\n]*?stx_mode=(S_IF[A-Z]+)\|[0-7]+, stx_size=(\d+)',s)
            if fd:sizes[fd[1]].add((fd[2],int(fd[3])))
            q=re.search(r' (statx|openat|openat2)\(AT_FDCWD(?:<[^>]*>)?, "([^"\\]*)"',s)
            if not q:continue
            fun,path=q.groups();m=re.search(r'\)\s+=\s+([^\n]*)$',s);assert m
            result=m[1]
            if fun=='statx':
                if result=='0':
                    e=0;mode=re.search(r'stx_mode=(S_IF[A-Z]+)\|',s);assert mode;accepted[path].add(mode[1])
                elif result.startswith('-1 ENOENT'):e=2;negative.append(path)
                elif result.startswith('-1 ENOTDIR'):e=20;negative.append(path)
                else:raise AssertionError((fun,path,result))
                rows.append([path,e,no])
            elif re.match(r'\d+',result):opened.add(path)
        tids[tid]=rows
    assert tids
    return tids,opened,negative,sizes,accepted
def match(q,tids):
    hits=[]
    for tid,rows in tids.items():
        raw=[v[:2]for v in rows]
        hits.extend([[tid,rows[i][2],rows[i+len(q)-1][2]]for i in range(len(rows)-len(q)+1)if raw[i:i+len(q)]==q])
    return hits
def role(z,src,stock,a,malformed=False):
    req,opens,probes,fail,stray=open_rows(z.read(src+'/stderr'));assert req and opens
    tids,kopened,allneg,sizes,kinds=original_trace(z,stock)
    target=a[a.index('-o')+1];assert stray==([] if malformed else [[target,2]]),(src,stray)
    literal=kernel.doc(z,'native-capture/all-literal-inputs.json.gz');expected=[['Lib',x[2:]]if x.startswith('-l')else ['File',x]for i,x in enumerate(a)if x.startswith('-l')or x in literal and a[i-1]!='-plugin']
    roots=sorted((r for r in req if r['referrer']is None),key=lambda r:r['source_position'])
    assert len(roots)==402 and [r['source_position']for r in roots]==list(range(len(roots))) and [r['spec']for r in roots]==expected
    scripts=defaultdict(list)
    for row in req:
        if row['referrer'] is not None:scripts[row['referrer']].append(row)
    for name,items in scripts.items():
        assert name in {r['resolved']for r in roots}
        assert sorted(r['source_position']for r in items)==list(range(len(items)))
    if not malformed:assert Counter(r['resolved']for r in req)==Counter(o[0]for o in opens)
    for r in req:
        if any(e==0 for _,e in r['probes']):assert r['probes'][-1]==[r['resolved'],0],(src,r)

    output_misses=[path for path in allneg if path==target];allneg=[path for path in allneg if path!=target];assert len(output_misses)==(0 if malformed else 1), (src,output_misses);nonzero=[p for p,e in probes if e and p!=target];assert Counter(nonzero)==Counter(allneg),(src,len(nonzero),len(allneg),(Counter(nonzero)-Counter(allneg)).most_common(3),(Counter(allneg)-Counter(nonzero)).most_common(3))
    assert all(kinds[p]=={'S_IFREG'} for p,e in probes if e==0 and p!=target),{p:sorted(kinds[p]) for p,e in probes if e==0 and p!=target and kinds[p]!={'S_IFREG'}}
    matched=[]
    for r in req:
        if not r['probes']:continue
        hits=match(r['probes'],tids)
        assert hits,(src,r['spec'],r['probes'][:2],r['probes'][-2:])
        row={**r,'signed_kernel_exact_per_request_sequences':hits};matched.append(row)
    lp=[r for r in matched if r['referrer']is None and r['spec'][0]=='Lib'];assert Counter(r['spec'][1]for r in lp)==Counter(kernel.LIBS),(src,[r['spec']for r in lp])
    children=[r for r in matched if r['referrer']is not None]
    gc=next(r['resolved']for r in lp if r['spec']==['Lib','gcc_s'])
    gcc=[r for r in children if r['referrer']==gc];assert {tuple(r['spec'])for r in gcc}=={('File','libgcc_s.so.1'),('Lib','gcc')},(gc,[r['spec']for r in children])
    assert sum(bool(e)for r in gcc for _,e in r['probes'])==8
    direct=sum(bool(e)for r in lp for _,e in r['probes']);assert direct==(86 if src=='src-observer'else 74)
    sym,=[p for p in a if p.endswith('/symbols.o')];raw=a[next(i for i,v in enumerate(a)if v.startswith('-L'))][2:]
    if malformed:
        assert any(r['referrer']==raw+'/libutil.a'and r['spec']==['File','DELIBERATELY']for r in req)
        assert any(p.endswith('/DELIBERATELY')and err==2 for p,err in fail)
        assert read(z,src+'/link-result.json')['returncode']!=0
    else:
        assert not fail
        dp='stock-depfile-trace'if src=='src-observer'else ('earlier-library'if src=='src-shadow'else'four-byte-symbol')
        positives=set(z.read(dp+'/stdout').decode().splitlines());source_open={p for p,*_ in opens}
        assert source_open==positives,(src,source_open-positives,positives-source_open)
        sure=kernel.parse(z,stock,a);maps=set(sure['mmap_paths']);real=sure['opened_realpaths']
        for p,_,_,n in opens:
            assert p in kopened and set(real[p])&maps,(src,p)
            assert any(('S_IFREG',n)in sizes[v]for v in real[p]),(src,p,n)
        sy,=[o for o in opens if o[0]==sym];assert sy[-1]==39760
    canonical=sorted(req,key=lambda r:((r['referrer']or ''),r['source_position']));request_sha=hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':')).encode()).hexdigest();descriptor_sha=hashlib.sha256(json.dumps(sorted(opens),separators=(',',':')).encode()).hexdigest()
    return dict(all_typed_requests_sha256=request_sha,all_descriptor_rows_sha256=descriptor_sha,exact_top_level_argv_inputs=len(roots),exact_script_source_positions={p:sorted([[r['source_position'],r['spec']]for r in items])for p,items in scripts.items()},actual_descriptor_sizes_joined_to_signed_kernel=not malformed,successful_searches_all_regular=True,direct_misses=direct,gcc_script_misses=8,complete_source_probe_count=len(probes),complete_failed_source_probe_count=len(nonzero),signed_kernel_failed_paths=len(allneg),excluded_prior_output_probe=len(output_misses),resolution_requests=len(req),input_descriptors=opens,failed_opens=fail,lookups=matched,all_source_reported_open_names=len({o[0]for o in opens}),kernel_open_names_outside_source=sorted(kopened-{o[0]for o in opens}))
def loader_boundaries(z,a):
    events=[];first=[]
    direct_first=next(v[2:]for v in a if v.startswith('-L'))+'/libgcc_s.so'
    for k in z.namelist():
        if not(k.startswith('syscall-observer/syscalls/task.')and k.endswith('.gz')):continue
        tid=int(k.split('.')[-2])
        for seq,line in enumerate(gzip.decompress(z.read(k)).decode().splitlines()):
            m=re.match(r'^(\d+\.\d+) (\w+)\((.*)',line)
            if not m:continue
            ts,call,tail=m.groups();path=re.search(r'"([^"\\]*)"',tail);result=re.search(r'\)\s+=\s+(.+)$',tail)
            if not path or not result:continue
            path=path[1]
            if call=='statx'and path==direct_first:first.append(float(ts))
            if call in ('openat','newfstatat','access')and (path=='/etc/ld.so.preload'or path=='/etc/ld.so.cache'or '/glibc-hwcaps/'in path or path.endswith(('/libc.so.6','/libgcc_s.so.1'))):
                events.append([float(ts),tid,seq,call,path,result[1].split(' ',2)[:2]])
    assert first;boundary=min(first);pre=sorted(row for row in events if row[0]<boundary)
    neg=[r for r in pre if r[5][:2]==['-1','ENOENT']]
    assert Counter(r[3]for r in neg)=={'openat':5,'newfstatat':3,'access':1}
    assert [r[4]for r in neg if r[3]=='access']==['/etc/ld.so.preload']
    assert Counter(os.path.basename(r[4])for r in neg if r[3]=='openat')=={'libc.so.6':4,'libgcc_s.so.1':1}
    assert any(r[3]=='openat'and r[4]=='/etc/ld.so.cache'and r[5][0]!='-1'for r in pre)
    return {'kernel_events_before_first_linker_candidate':pre,'outside_source_failed_lookup_count':len(neg)}
def control_rows(z,a):
    name='src-observer/stderr';raw=z.read(name).decode().splitlines()
    cases={}
    def once(pred):
        ids=[i for i,line in enumerate(raw)if pred(line.split('\t'))];assert len(ids)==1,ids;return ids[0]
    def field(i,num,value):
        lines=raw.copy();fields=lines[i].split('\t');fields[num]=value;lines[i]='\t'.join(fields);return lines
    def tag(f,s):return len(f)>4 and f[0]=='OHMLOOK'and f[1]==s
    p=once(lambda f:tag(f,'P')and f[4].endswith('/raw-dylibs/libutil.so"')and f[5]=='2');cases['one real ENOENT omitted']=raw[:p]+raw[p+1:]
    p=once(lambda f:tag(f,'B')and f[4]=='File("libgcc_s.so.1")');cases['child bound to other real linker script']=field(p,5,raw[p].split('\t')[5].replace('libgcc_s.so','libm.so'))
    p=once(lambda f:tag(f,'B')and f[4]=='Lib("util")'and f[5]=='None');cases['duplicate top-level source position']=field(p,8,'0')
    state=raw[p].split('\t')[2:4];e=next(i for i in range(p+1,len(raw))if raw[i].split('\t')[1:4]==['E',*state]);cases['later root reported as winner']=field(e,4,'Some("/deliberately-other/libutil.a")')
    p=once(lambda f:tag(f,'O')and f[4].endswith('/symbols.o"'));cases['generated object descriptor size changed']=field(p,7,'39761')
    p=once(lambda f:tag(f,'P')and f[4].endswith('/libutil.a"')and f[5]=='0');cases['non-regular file reported at winner']=field(p,6,str(stat.S_IFDIR|0o755))
    class Replace:
        def __init__(self,body):self.body=body
        def read(self,k):return self.body if k==name else z.read(k)
        def namelist(self):return z.namelist()
    checks=[]
    for label,lines in cases.items():
        try:role(Replace(('\n'.join(lines)+'\n').encode()),'src-observer','syscall-observer',a)
        except AssertionError:checks.append(label)
        else:raise AssertionError('invalid observation accepted: '+label)
    return checks
def main(p,expected,head,output):
    assert hashf(p)==expected
    with zipfile.ZipFile(p)as z:
        assert z.testzip()is None and len(z.namelist())==len(set(z.namelist()))
        reg=read(z,'registration.json');assert reg['head']==head and reg['run']=='41671338175'
        a=kernel.argv(z.read('native-capture/argv.nul'));ids=read(z,'source-wild/identities.json');assert ids['revision']=='e856d81f6683cad80b9fe0ebf1a0c3c403c6fe11'and ids['patch']=='bf024b0804e796e1f0eb7c643fd0c265e027061907c10115d50b19d39eb41ed7'
        enrolled=json.loads((D/'source-ids.json').read_bytes());assert all(ids[k]==enrolled[k]for k in ('revision','tree','patch','lock'))
        assert set(ids['source_arms'])=={'stock','observer'} and all(ids['source_arms'][arm]['source_sha256']==enrolled[arm+'_sources']for arm in ids['source_arms'])
        assert ids['source_arms']['stock']['sha256']!=ids['source_arms']['observer']['sha256']
        assert reg['reference']==dict(run=41617756983,old=kernel.OLD,edited=kernel.NEW,independent_clean=kernel.NEW,test_inventory=kernel.LIST)
        for stage,sha in [('ordinary-old',kernel.OLD),('ordinary-edit',kernel.NEW),('current-observed',kernel.NEW)]:
            inv=kernel.doc(z,stage+'/inventory.json.gz');assert len(inv['executables'])==102 and inv['executables'][inv['binary']]['elf']['sha256']==sha
        for stage in ('old','old-on-new','edit','observed'):
            assert kernel.sha(z.read(stage+'-verdict/test-list'))==kernel.LIST
            stdout=z.read(stage+'-verdict/stdout');assert (b'1 failed;'if stage=='old-on-new'else b'1 passed;')in stdout
            if stage=='old-on-new':assert b'script_tag'in stdout and b'source_text'in stdout

        sym=z.read('native-capture/symbols.o');bad=z.read('native-capture/four-byte-symbols.o');assert sym.count(b'\0main\0')==1 and sym.replace(b'\0main\0',b'\0zzQA\0')==bad and sum(x!=y for x,y in zip(sym,bad))==4;assert len(sym)==len(bad)==39760
        assert read(z,'native-capture/identity.json')['executable']['sha256']==kernel.WILD and len(a)==446 and not any(v.startswith('@')for v in a)

        clean=kernel.NEW;phases={}
        for k in ('stock','src-stock','src-observer','earlier-library','src-shadow','four-byte-symbol','src-four-byte','malformed-shadow','src-malformed','src-final-repair'):
            phases[k]=read(z,k+'/link-result.json')
            if 'malformed'in k:assert phases[k]['returncode']!=0 and phases[k]['elf']is None
            elif 'four-byte'in k:assert read(z,k+'/runtime.json')['returncode']==83 and phases[k]['elf']['sha256']!=clean
            else:assert phases[k]['returncode']==0 and phases[k]['elf']['sha256']==clean and hashlib.sha256(z.read(k+'-verdict/test-list')).hexdigest()==kernel.LIST
        assert phases['four-byte-symbol']['elf']==phases['src-four-byte']['elf']
        variants={k:role(z,k,trace,a,'malformed'in k)for k,trace in [('src-observer','syscall-observer'),('src-shadow','earlier-library'),('src-four-byte','four-byte-symbol'),('src-malformed','malformed-shadow')]}
        assert all(variants['src-shadow'][k]==variants['src-four-byte'][k]for k in ('all_typed_requests_sha256','all_descriptor_rows_sha256'))
        descriptors=[{p:[d,i,n]for p,d,i,n in row['input_descriptors']}for row in variants.values()]
        for p,s in descriptors[0].items():
            for ds in descriptors[1:]:
                if p in ds:assert s==ds[p],(p,s,ds[p])
        actual=kernel.doc(z,'native-capture/all-literal-inputs.json.gz');assert len(actual)==396
        extern={k:next(p for p in a if p.endswith('/'+k))for k in kernel.SYS}
        assert {k for k,p in extern.items()if p in descriptors[0]}==set(kernel.SYS)-{'liblto_plugin.so'}
        for p,s in descriptors[0].items():
            if p in actual:assert actual[p]['bytes']==s[2]
        result={'loader_before_first_wild_request':loader_boundaries(z,a),'independent_tamper_refusals':control_rows(z,a),'registered_source_controls':reg['reference'],'temporary_symbols':{'original':kernel.sha(sym),'mutation':kernel.sha(bad),'changed_offsets':[j for j,(x,y)in enumerate(zip(sym,bad))if x!=y]},'explicit_driver_system_inputs_seen':{k:p in descriptors[0]for k,p in extern.items()},'github_zip_sha256':expected,'head':head,'source_arms':ids,'native':phases,'cases':variants}
    out=Path(output);out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');print(hashf(out))
if __name__=='__main__':main(*sys.argv[1:])
