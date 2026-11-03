import collections,json,os,shutil,subprocess as sp,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent));from common import *
import perf_tools as pt
trace=ROOT/'exec_count'
def identity(p):
    s=p.stat();return s.st_dev,s.st_ino
def labels(td):
    ids={};records=[];whole=None;executions=[]
    for line in (td/'epochs.tsv').read_text().splitlines():
        f=line.split()
        if f[0]=='I':
            i,g=int(f[1]),int(f[2]);a=(td/f'{i:05}.nul').read_bytes().split(b'\0')
            need(a.pop()==b'' and int(a[0])==g,'bad exec descriptor')
            key=tuple(map(int,a[1:3]));argv=list(map(os.fsdecode,a[4:]));path=os.fsdecode(a[3]);entry=(g,key,argv,path,f[5]);ids[i]=entry
            if f[5]=='exec':executions.append({'pid':g,'image':i,'identity':key,'argv':argv,'path':path})
        if f[0]=='R':
            i,pid,n,e,r,code=map(int,f[1:]);g,key,argv,path,origin=ids[i]
            need(origin=='exec'and pid==g and n>0 and e==r>0 and code==0,('unqualified task lifetime',i))
            records.append({'pid':pid,'image':i,'argv':argv,'path':path,'identity':key,'instructions':n,'enabled':e,'running':r})
        if f[0]=='W':
            whole,e,r,code=map(int,f[1:]);need(whole>0 and e==r>0 and code==0,'unqualified whole observed command')
    need(whole is not None,'truncated lifetime observation');return records,whole,executions
def calibrate():
    exe=ROOT/'thread_meter';stats={}
    for n,mode in ((1000000,'alone'),(4000000,'alone'),(1000000,'spawn')):
        d=DIAG/(str(n)+mode);d.mkdir();sp.run([trace,'--lifetime',exe,d,exe,str(n),mode],check=True)
        rows,total,_=labels(d);by={a['argv'][-1]:a['instructions']for a in rows}
        need(len(rows)==len(by) and set(by)==({mode,'child'}if mode=='spawn'else {mode})and abs(sum(by.values())/total-1)<.02,'failed scope calibration');stats[(n,mode)]=by
    first=stats[(1000000,'alone')]['alone']
    need(3.8<stats[(4000000,'alone')]['alone']/first<4.2 and abs(stats[(1000000,'spawn')]['spawn']/first-1)<.03 and stats[(1000000,'spawn')]['child']>7*first,'failed lifetime calibration')
    put(DIAG/'calibration.json',{str(k):v for k,v in stats.items()})
def observed(tag,state,perf=None):
    select(state);guard();td=DIAG/tag;tasks=DIAG/(tag+'-actual-execs');tasks.mkdir()
    invoked=[trace,'--lifetime',SDK/'bin/rustc','--also',SDK/WILD,tasks,*CMD]
    raw=td/'kernel.perf'
    if perf:invoked=pt.record(perf,raw,invoked,pt.PERIOD)
    command(td,invoked);r,total,images=labels(tasks)
    products=observe_products(td,state);put(td/'products.json',products)
    compare=json.loads((PUB/('old'if state==OLD else 'edit')/'products.json').read_bytes())
    need(products==compare,('normal and observed output differ',tag))
    rust=identity(SDK/'bin/rustc');wild=identity(SDK/WILD);selected=[]
    for row in r:
        a=row['argv'];k=tuple(row['identity'])
        if k==rust:
            if '--crate-name'in a:
                name=a[a.index('--crate-name')+1];target=a[a.index('--crate-type')+1]if '--crate-type'in a else 'test'
                row['owner']='rustc:'+name+':'+target
            else:row['owner']='rustc:tool-query'
        else:need(k==wild,'selected unknown executable');row['owner']='wild'
        selected.append(row['owner'])
    put(td/'owners.json',{'lifetimes':r,'whole_observed':total,'all_execs':images,'selected':selected})
    if perf:
        count=pt.decode(perf,raw,td);frames,rows=pt.sample_rows(td);need(len(rows)==count,'sample decoder lost rows')
        known={x['pid']:x['owner']for x in r};seen=collections.Counter();each=collections.defaultdict(collections.Counter);macro_paths={}
        for pid,tid,at,period,leaf,stack in rows:
            key=known.get(pid,'other-tasks');dso,sym=frames[leaf[0]];seen[key]+=1
            image=Path(dso).name if dso not in ('None','[unknown]') else 'unknown'
            each[key][image]+=1
            if image.startswith('libclap_derive-') and image.endswith('.so')and dso not in macro_paths:
                names=[Path(dso)]if Path(dso).is_file()else [p for base in (BUILD,TARGET)for p in base.rglob(image)if p.is_file()]
                need(bool(names) and len({hf(p)for p in names})==1,('unbound real macro DSO',image))
                macro_paths[dso]={'sha256':hf(names[0]),'bytes':names[0].stat().st_size,'build_id':sp.check_output(['readelf','-n',str(names[0])],text=True)}
        put(td/'samples-by-image.json',{'sample_period':pt.PERIOD,'records':count,'owners':seen,'per_owner':each,'clap_images':macro_paths})
        sp.run(['zstd','-q','-3','--rm',raw],check=True)
    return selected
need((PUB/'admission.json').is_file(),'ordinary run unavailable')
calibrate()
old=observed('reverse',OLD)
# Terminal exact task lifetimes and bytes survive even if the independent perf tooling refuses the sample.
edit=observed('true-edit',NEW);unch=observed('unchanged',NEW)
put(DIAG/'lifetimes-complete.json',{'old':old,'edit':edit,'unchanged':unch})
p=pt.prepare_perf()
observed('before-sample',OLD)
sample=observed('sampled-edit',NEW,p)
need(sample==edit or sorted(sample)==sorted(edit),'different profiled compiler/link roster')
put(DIAG/'accepted.json',{'same_native_and_library_bytes':True,'ordinary_clean':json.loads((PUB/'admission.json').read_bytes())['strict_product_match'],'roster':sample})
