"""Open the current signed Wild/e2e native role directly from its authenticated QA original."""
import argparse,collections,gzip,hashlib,json,os,re,sys,zipfile
from pathlib import Path
P=Path(__file__).resolve().parent
LIBS=['gcc_s','util','rt','pthread','m','dl','c']
OLD='f203086dc58594dc33899d25dcbdcd5ec86d04e3dfb493efe7c7a59f6abd97e2';NEW='86b94323a752a316a501f542a846408648ca8b74c56bc60298690b671b7b0563';LIST='76d24b892727ff181fdf019636ef5e928d741eb8df4f58f06dcc626d0bf67c52';WILD='0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5'
CONTROL=['stock','syscall-observer','stock-depfile-trace','earlier-library','four-byte-symbol','symbol-repair','malformed-shadow','remove-shadow-repair']
SYS=['Scrt1.o','crti.o','crtn.o','crtbeginS.o','crtendS.o','liblto_plugin.so']
def sha(b):return hashlib.sha256(b).hexdigest()
def digest(p):
    with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(z,f):
    d=z.read(f);return gzip.decompress(d)if f.endswith('.gz')else d
def doc(z,f):return json.loads(read(z,f))
def argv(d):
    a=d.decode().split('\0');assert a[-1]==''and all(x.isdigit()for x in a[:3])and a[3]==a[4];return a[4:-1]
def normarg(arg):return re.sub(r'/rustc[A-Za-z0-9]+/(?=(?:symbols\.o|raw-dylibs)$)','/rustc@/',re.sub(r'/tmp/cc[A-Za-z0-9]+\.res$','/tmp/cc@.res',arg))
def parse(z,stage,args):
    roots=[s[2:]for s in args if s.startswith('-L')];assert len(roots)==13
    lookup={f'{p}/lib{l}.{x}':(l,i,x)for l in LIBS for i,p in enumerate(roots)for x in ('so','a')};wanted=set(lookup)
    symbols,=[a for a in args if a.endswith('/symbols.o')]
    sysfiles={s:next(a for a in args if a.endswith('/'+s))for s in SYS}
    picks=collections.defaultdict(list);nested=[];opens=[];maps=[];files={};statuses=collections.Counter()
    for f in sorted(k for k in z.namelist()if k.startswith(stage+'/syscalls/task.')and k.endswith('.gz')):
        tid=int(f.split('.')[-2]);raw=read(z,f);files[str(tid)]={'bytes':len(raw),'sha256':sha(raw)}
        assert not b'<unfinished ...>' in raw and not re.search(rb'<\.\.\. \w+ resumed>',raw),f
        for seq,line in enumerate(raw.decode(errors='strict').splitlines()):
            m=re.match(r'^(\d+\.\d+) (\w+)\((.*)',line)
            if not m:continue
            ts,call,tail=m.groups();statuses[call]+=1;result=tail.rpartition(' = ')[2]
            if not result:
                # strace pads the result field on short syscalls.
                m2=re.search(r'\)\s+=\s+(.*)$',tail);result=m2[1]if m2 else ''
            q=re.search(r'"([^"\\]*)"',tail)
            if call=='statx'and q:
                p=q[1];event={'tid':tid,'seq':seq,'path':p,'result':result}
                if p in wanted:picks[lookup[p][0]].append(event)
                elif (p.endswith('/libgcc.so')or p.endswith('/libgcc_s.so.1')):nested.append(event)
            elif call in ('open','openat','openat2')and q and re.match(r'\d+',result):
                opens.append({'tid':tid,'seq':seq,'path':q[1],'fd':result.split()[0]})
            elif call=='mmap' and not result.startswith('-1'):
                mm=re.search(r', (-?\d+)<([^>]+)>, (0x[\da-f]+|\d+)\)',tail)
                if mm:
                    fields=tail.split(', ');maps.append(dict(tid=tid,seq=seq,fd=int(mm[1]),path=mm[2],offset=int(mm[3],0),bytes=int(fields[1],0)))
    assert files and statuses['statx']and statuses['mmap']
    # Exact search order is per source argument and TID, never time-sorted globally.
    winners={};negatives=[]
    for lib in LIBS:
        events=picks[lib];assert events,(stage,lib)
        assert len({r['tid']for r in events})==1,(stage,lib,'interleaved users',events)
        end=next(i for i,r in enumerate(events)if r['result']=='0');prefix_events=events[:end+1];win=prefix_events[-1]
        rechecked=events[end+1:];assert len(rechecked)==1 and [(r['path'],r['result'])for r in rechecked]==[(win['path'],'0')]
        seq=[lookup[r['path']][1:]for r in prefix_events];prefix=[(i,suff)for i in range(len(roots))for suff in ('so','a')]
        assert seq==prefix[:len(seq)]and all(r['result'].startswith('-1 ENOENT')for r in prefix_events[:-1])and win['result']=='0',(stage,lib,seq,win)
        assert any(r['path']==win['path']or os.path.normpath(r['path'])==os.path.normpath(win['path'])for r in opens),(stage,'no open of winner',win)
        winners[lib]={'examined':prefix_events,'later_restated_winner':rechecked,'winner':win['path'],'root_index':seq[-1][0],'suffix':seq[-1][1]};negatives.extend(e['path']for e in prefix_events[:-1])
    def actual(p):
        op=[r for r in opens if os.path.normpath(r['path'])==os.path.normpath(p)]
        canonical={r['fd'].partition('<')[2].rstrip('>')for r in op}
        mapped=[r for r in maps if r['path']in canonical or os.path.normpath(r['path'])==os.path.normpath(p)]
        return {'path':p,'opens':op,'maps':mapped}
    sy=actual(symbols);assert sy['opens']and sy['maps']
    real=collections.defaultdict(set)
    for op in opens:
        if '<'in op['fd']:real[op['path']].add(op['fd'].partition('<')[2].rstrip('>'))
    return dict(opened_realpaths={k:sorted(v)for k,v in real.items()},threads=files,syscalls=dict(statuses),winners=winners,negative_paths=negatives,nested_script_path_probes=nested,actual_symbols=sy,original_six={k:actual(v)for k,v in sysfiles.items()},opened_paths=sorted({r['path']for r in opens}),mmap_paths=sorted({r['path']for r in maps}))
def main(zname,ziphash,run,head,historical_zip):
    zpath=Path(zname);assert digest(zpath)==ziphash;result={'run':run,'qa_head':head,'original':{'bytes':zpath.stat().st_size,'sha256':ziphash}}
    with zipfile.ZipFile(zpath)as z:
        assert z.testzip()is None and len(z.namelist())==len(set(z.namelist()))
        reg=doc(z,'registration.json');assert reg['run']==str(run) and reg['head']==head and reg['reference']['independent_clean']==NEW
        for stage,sh in [('ordinary-old',OLD),('ordinary-edit',NEW),('current-observed',NEW)]:
            d=doc(z,stage+'/inventory.json.gz');p=d['binary'];assert len(d['executables'])==102 and d['executables'][p]['elf']['sha256']==sh
        for g in ('old','old-on-new','edit','observed'):
            assert sha(read(z,g+'-verdict/test-list'))==LIST
        identity=doc(z,'native-capture/identity.json');assert identity['executable']['sha256']==WILD
        a=argv(read(z,'native-capture/argv.nul'));assert [s[2:]for s in a if s.startswith('-l')]==LIBS
        oldzip=Path(historical_zip);assert digest(oldzip)=='9c5a3ac75da6e79b13042be19228a37418f46fc356cc40e5f77cddd2147ecf57'
        with zipfile.ZipFile(oldzip)as old:
            historical=argv(read(old,'actual-link-argv/tasks/00337.nul'));assert len(historical)==len(a)==446
            orig=read(old,'held-union-1/paths.nul').split(b'\0');assert orig.pop()==b'';rows=read(old,'held-union-1/observed.txt').splitlines();assert len(orig)==len(rows)==3402
            held={}
            for i,(p,row)in enumerate(zip(orig,rows)):
                j,n,err,dev,ino,h=row.split();assert int(j)==i;held[os.fsdecode(p)]={'bytes':int(n),'sha256':h.decode()}
        # Preserve the literal cross-boot refusal. Separately admit the same real semantic argument roles after proving every difference is in these concrete path components.
        hostns=lambda role:next(iter({m.group()for arg in role for m in re.finditer(r'/v2-[0-9a-f]{16}/',arg)}))
        assert hostns(a)=='/v2-6d0f8e47c2abf95c/'and hostns(historical)=='/v2-23a763fc91c791a4/'
        def role(x,ns):
            y=normarg(x).replace(ns,'/v2@/')
            return re.sub(r'\.[0-9a-z]{7}\.rcgu\.o$','.@.rcgu.o',y)if '.rlink-objects/'in y else y
        assert all(role(x,hostns(historical))==role(y,hostns(a))for x,y in zip(historical,a))
        physical=doc(z,'native-capture/all-literal-inputs.json.gz');pair_inputs=[(x,y,held[x]==physical[y])for x,y in zip(historical,a)if y in physical and not y.endswith('/symbols.o')];assert len(pair_inputs)==395
        result['historical_argv']={'strict_equality':a==historical,'changed_positions':sum(x!=y for x,y in zip(historical,a)),'semantic_role_equivalence':'two actual v2 directories, each rlink CGU session suffix, symbols/raw temporary directory, GCC resolution temp','all_395_earlier_current_sha256_equal':all(ok for x,y,ok in pair_inputs),'unequal_prior_and_current_bytes':[[x,held[x],y,physical[y]]for x,y,ok in pair_inputs if not ok]}
        inputs=doc(z,'native-capture/all-literal-inputs.json.gz');sym,=[s for s in a if s.endswith('/symbols.o')];assert inputs[sym]==identity['symbol'];assert len(inputs)==396
        captured=read(z,'native-capture/symbols.o');mutated=read(z,'native-capture/four-byte-symbols.o')
        assert captured.count(b'\0main\0')==1 and captured.replace(b'\0main\0',b'\0zzQA\0')==mutated and len(captured)==identity['symbol']['bytes'] and sha(captured)==identity['symbol']['sha256']
        result.update(registration=reg,identity=identity,complete_symbols_byte_diffs=[[i,x,y]for i,(x,y)in enumerate(zip(captured,mutated))if x!=y],inputs_count=len(inputs),inputs_bytes=sum(r['bytes']for r in inputs.values()))
        plans={stage:doc(z,stage+'/link-result.json')for stage in CONTROL};result['stages']=plans
        for tag,info in plans.items():
            if tag=='malformed-shadow':assert info['returncode']!=0;continue
            assert info['returncode']==0
            if tag=='four-byte-symbol':assert doc(z,tag+'/runtime.json')['returncode']==83;continue
            assert sha(read(z,tag+'-verdict/test-list'))==LIST
            if tag not in ('earlier-library','symbol-repair'):assert info['elf']['sha256']==NEW
        assert plans['earlier-library']['elf']==plans['symbol-repair']['elf'] and plans['four-byte-symbol']['elf']!=plans['earlier-library']['elf']
        out={phase:parse(z,phase,a)for phase in ('syscall-observer','earlier-library','four-byte-symbol')}
        target=out['syscall-observer'];shadow=out['earlier-library']
        assert sum(target['winners'][k]['winner']!=shadow['winners'][k]['winner']for k in LIBS)==1 and shadow['winners']['util']['root_index']==0 and shadow['winners']['util']['suffix']=='a'
        assert shadow['winners']['util']['winner']in target['negative_paths']
        dep=read(z,'stock-depfile-trace/stock.d').decode();stdout=read(z,'stock-depfile-trace/stdout').decode();lines=dep.splitlines();target_path,a_deps=lines[0].split(': ',1);assert target_path==a[a.index('-o')+1];positive=a_deps.split();assert len(positive)==len(set(positive))and lines[1:]==[v for x in positive for v in ('',x+':')];reported=set(stdout.splitlines())|set(positive);result['stock_report']={'dep_bytes':len(dep),'trace_bytes':len(stdout),'dep_sha256':sha(dep.encode()),'trace_sha256':sha(stdout.encode()),'winners_in_dep':{lib:(row['winner']in positive)for lib,row in target['winners'].items()},'reported_negative_paths':[p for p in target['negative_paths']if p in reported],'symbols_in_dep':sym in positive,'positive_record_count':len(positive),'reported_by_trace':len(set(stdout.splitlines()))}
        assert not result['stock_report']['reported_negative_paths'];result['kernel']=out
    (P/'verified.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');print('verified',run,digest(P/'verified.json'))
if __name__=='__main__':main(sys.argv[1],sys.argv[2],int(sys.argv[3]),sys.argv[4],sys.argv[5])
