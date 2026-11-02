"""One unscored candidate-only instruction profile of the native-qualified Ruff #27470 edit."""
from bisect import bisect_right
from collections import Counter, defaultdict
from contextlib import ExitStack
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hardware as h
import unchanged as u

m = h.checked
need, save, sha = h.need, h.save, h.sha
B = m.OUT
KITS = HERE / 'residual'
PERIOD = 200003
NORMAL_NONFRESH = [('annotate_snippets',('lib',),False), ('ruff_db',('lib',),True)]

def clean_subprocess():
    return {'HOME':str(m.W/'home'), 'PATH':'/usr/bin:/bin', 'LC_ALL':'C', 'PYTHONHOME':'/usr', 'PYTHONNOUSERSITE':'1', 'PYTHONDONTWRITEBYTECODE':'1'}

def private_argv(path):
    libraries=m.ROOT/'perf-tools/usr/lib/x86_64-linux-gnu'
    if libraries.is_dir() and Path(path).is_relative_to(m.ROOT/'perf-tools'):
        return ['/lib64/ld-linux-x86-64.so.2','--library-path',str(libraries),str(path)]
    return [str(path)]

def locate_perf():
    roots=[Path('/usr/lib'),m.ROOT/'perf-tools/usr/lib']
    candidates=[Path('/usr/bin/perf'),*(p for root in roots for pattern in ('linux-tools-*/perf','linux-tools/*/perf')for p in sorted(root.glob(pattern),reverse=True))]
    for path in candidates:
        if path.is_file():
            result=subprocess.run([*private_argv(path),'version','--build-options'],env=clean_subprocess(),capture_output=True)
            if result.returncode==0 and re.search(rb'libpython:\s*\[\s*on\s*\]',result.stdout):return path.resolve(),result.stdout.decode()
    return None,None

def prepare_perf():
    path,version=locate_perf();packages={}
    if path is None:
        # The base package contains the executable. The generic-flavour package supplies only a symlink.
        directory=m.ROOT/'perf-tools';directory.mkdir();perf_package='linux-tools-6.8.0-147=6.8.0-147.147'
        def extract(package,expected=None):
            known=set(directory.glob('*.deb'));subprocess.run(['apt-get','download',package],cwd=directory,check=True);deb,=set(directory.glob('*.deb'))-known;digest=sha(deb);need(expected is None or digest==expected,'wrong signed distribution package');subprocess.run(['dpkg-deb','-x',deb,directory],check=True);packages[deb.name]=digest
        digest='7bf31034e1914ff171c2b82c48e1f17b5123b7e63e1d4ef0582877c45cc17cd0'
        try:extract(perf_package,digest)
        except subprocess.CalledProcessError:
            subprocess.run(['sudo','-n','apt-get','-qq','update'],check=True,timeout=180);extract(perf_package,digest)
        real=directory/'usr/lib/linux-tools-6.8.0-147/perf';need(sha(real)=='2927eb0973fd937bdd417622531c95f1e6e19307a29c3e05a2c6198e12af6e56','different underlying distribution perf');ldd=subprocess.check_output(['ldd',real],text=True);(B/'perf-dynamic-libraries.txt').write_text(ldd)
        libraries={'libtraceevent.so.1':'libtraceevent1','libnuma.so.1':'libnuma1','libunwind.so.8':'libunwind8','libunwind-x86_64.so.8':'libunwind8','libslang.so.2':'libslang2','libpython3.12.so.1.0':'libpython3.12t64','libdw.so.1':'libdw1t64','libelf.so.1':'libelf1t64','libexpat.so.1':'libexpat1','libcap.so.2':'libcap2'}
        missing=re.findall(r'(\S+) => not found',ldd);need(set(missing)<=set(libraries),'unknown runtime dependency '+str(missing))
        for package in sorted({libraries[lib]for lib in missing}):extract(package)
        path,version=locate_perf()
    need(path is not None,'no usable distribution perf with its Python symbol reader')
    save(B/'perf-tool.json',dict(path=str(path),sha256=sha(path),version=version,packages=packages,hook=sha(KITS/'perf_hook.py'),event='instructions:u',period=PERIOD,clock='monotonic',callchain='frame pointers, 48 entries'))
    return path

def record(perf, out, command, period):
    return [*private_argv(perf),'record','--period','--no-buildid-cache','--clockid','mono','--call-graph','fp,48','-m','128','-e','instructions:u','-c',str(period),'-o',str(out), '--',*map(str,command)]

def decode(perf, source, case):
    env = clean_subprocess() | {'OHM_PERF_ROWS':str(case/'samples.ndjson.gz')}
    with (case/'symbolizer.stderr').open('wb') as err:
        subprocess.run([*private_argv(perf),'script','--no-demangle','-i',source,'-s',KITS/'perf_hook.py'],env=env,stdout=subprocess.DEVNULL,stderr=err,check=True,timeout=180)
    events=Counter()
    with (case/'raw-reader.stderr').open('wb')as e,subprocess.Popen([*private_argv(perf),'script','-D','-i',source],env=env,stdout=subprocess.PIPE,stderr=e)as proc:
        for line in proc.stdout:
            match=re.search(rb'\]: (PERF_RECORD_[A-Z_]+)',line)
            if match:events[match[1].decode()]+=1
        need(proc.wait(timeout=60)==0,'incomplete raw perf records')
    with (case/'event-header.txt').open('wb')as f:
        subprocess.run([*private_argv(perf),'report','--header-only','--stdio','-i',source],env=env,stdout=f,check=True)
    save(case/'record-counts.json',events)
    need(events['PERF_RECORD_SAMPLE']>0 and not any(events[k]for k in ('PERF_RECORD_LOST','PERF_RECORD_LOST_SAMPLES','PERF_RECORD_THROTTLE','PERF_RECORD_UNTHROTTLE')),'lost or throttled instruction samples')
    return events['PERF_RECORD_SAMPLE']

def sample_rows(case):
    frames,rows={},[]
    with gzip.open(case/'samples.ndjson.gz','rt')as src:
        for line in src:
            x=json.loads(line)
            if x[0]=='f':
                _,index,dso,symbol=x;need(index not in frames,'duplicate frame');frames[index]=(dso,symbol)
            else:
                mark,event,pid,tid,at,period,leaf,stack=x
                need(mark=='s' and event.startswith('instructions:u') and all(f[0]in frames for f in [leaf,*stack]),'different event or unknown symbol')
                rows.append((pid,tid,at,period,leaf,stack))
    return frames, rows

def setup():
    h.setup();perf=prepare_perf();observer=m.W/'count-exec';subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',KITS/'exec_count.c','-o',observer],check=True)
    env,_=m.role('C');case=B/'source-control';case.mkdir();(case/'exec').mkdir();cmd=[str(observer),str(case/'exec'),str(h.meter.WORK/'watch'),str(case/'clock.json'),str(h.meter.WORK/'loop'),'1','4000001','2']
    with (case/'stderr').open('wb')as e:
        subprocess.run(record(perf,case/'perf.data',cmd,5003),env=env,stdout=subprocess.DEVNULL,stderr=e,check=True,timeout=60)
    n=decode(perf,case/'perf.data',case);frames,rows=sample_rows(case);need(n==len(rows) and n>1000 and all(r[3]==5003 for r in rows),'native sampler fixture failed')
    events=u.trace(case/'exec');by_image={r['sequence']:r for r in events};clock=json.loads((case/'clock.json').read_bytes());parts=Counter()
    for line in (case/'exec/epochs.tsv').read_text().splitlines():
        cells=line.split()
        if cells[0]=='C':
            _,image,group,tid,cnt,enabled,running=map_or_tag(cells);need(enabled==running,'calibration multiplexed');parts[Path(by_image[image]['exe']).name]+=cnt
    loop_pids={r['pid']for r in events if Path(r['exe']).name=='loop' and r['argv'][1:] == ['0','4000001','1']};sampled=Counter(pid for pid,tid,at,period,leaf,stack in rows if Path(frames[leaf[0]][0]).name=='loop');need(len(loop_pids)==2 and loop_pids<=set(sampled) and min(sampled[p]for p in loop_pids)>100 and abs(parts['loop']/clock['instructions']-1)<.015 and abs(sum(sampled.values())*5003/parts['loop']-1)<.12,'child self-count/sampling did not independently reproduce inherited loop')
    save(case/'terminal.json',dict(exact=parts,pmu=clock['instructions'],sampled=sampled,all_samples=n,observer=sha(observer),perf=sha(perf)))

def map_or_tag(cells):
    return [cells[0],*(int(x)for x in cells[1:])]

def classify(r,sdk):
    exe=Path(r['exe']);argv=r['argv'];name=exe.name
    if exe.samefile(sdk/'bin/rustc'):
        if '--crate-name' in argv:
            crate=argv[argv.index('--crate-name')+1]
            return 'rustc:'+crate
        return 'rustc:other'
    if exe.samefile(sdk/'bin/cargo'):return 'cargo'
    if exe == sdk/'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd':
        need(sha(exe)=='0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5','different signed Wild binary');return 'Wild'
    if name in ('cc','gcc','collect2','ld') or re.fullmatch(r'x86_64-linux-gnu-gcc(-\d+)?',name):return 'link driver'
    if name=='rustup':return 'rustup'
    if name in ('count-exec','watch'):return 'instrumentation'
    return 'other:'+name

def classify_exact(case,sdk):
    events=u.trace(case/'exec');images={e['sequence']:e for e in events};roles={i:classify(r,sdk) for i,r in images.items()};exact=Counter();history=defaultdict(list);tasks=set();monitor=None
    for line in (case/'exec/epochs.tsv').read_text().splitlines():
        row=line.split()
        if row[0]=='M':
            need(monitor is None,'two profilers');monitor=int(row[1]);continue
        if row[0]=='I':
            _,id,pid,tid,at,trigger=row;id,pid,tid,at=map(int,(id,pid,tid,at));need(images[id]['pid']==pid and trigger in ('first','exec'),'invalid task epoch');history[pid].append((at,id))
        else:
            kind,id,pid,tid,cnt,enabled,running=map_or_tag(row);need(kind=='C' and images[id]['pid']==pid and enabled==running and (enabled>0 or cnt==0),'invalid task self count');exact[roles[id]]+=cnt;tasks.add(tid)
    need(all(stamps==sorted(stamps)for stamps in history.values()),'invalid exec time order');
    need(monitor and monitor not in history,'invalid standalone observation process');return roles,exact,history,images,tasks,monitor

def measure(argv,env,src,case,state):
    need(argv==h.CARGO and src==m.SRC and state==m.STATE,'different entry');perf,version=locate_perf();need(sha(perf)==json.loads((B/'perf-tool.json').read_bytes())['sha256'],'perf changed');trace=case/'exec';trace.mkdir();cmd=[m.W/'count-exec',trace,h.meter.WORK/'watch',case/'clock.json',*argv];raw=case/'perf.data'
    m.old.command(record(perf,raw,cmd,PERIOD),env,src,case,state);need(0<raw.stat().st_size<192<<20,'unbounded profile');decode(perf,raw,case)
    with (case/'perf.data.zst').open('xb')as f:subprocess.run(['zstd','-q','-2','-c',raw],stdout=f,check=True)
    save(case/'perf-data.json',dict(raw_sha256=sha(raw),bytes=raw.stat().st_size,compressed_sha256=sha(case/'perf.data.zst')));raw.unlink()

def build(name,profiled):
    h.resources();env,sdk=m.role('C');need(h.cpu_binding()==json.loads((B/'hardware-binding.json').read_bytes())['cpus'],'different CPU');m.OUT=B/name;m.OUT.mkdir();m.fresh(name+'-before-old');key=h.PROTOCOL['different_broad_row']['old']['key'];old,obj0,v0=h.checked_visit('C','old','old',env,set(),key)
    with ExitStack()as stack:
        pins={n:(stack.enter_context((old/rec['filename']).open('rb')),rec)for n,rec in obj0.items()}
        if profiled:
            folder,obj1,v1=m.visit('C','new','edit',env,key,{old},pinned=pins,run_cargo=measure);case=m.OUT/'C-edit';events=u.records(case);h.check_native('C','new',case,events,v1,obj1)
            for n,rec in obj1.items():need(m.blob(folder/rec['filename'])==rec['sha256'],'profiled output custody failed')
        else:
            folder,obj1,v1=h.checked_visit('C','new','edit',env,{old},key,pins=pins,is_counted=True);case=m.OUT/'C-edit';events=u.records(case)
    dirty=sorted((r['target']['name'],tuple(r['target']['kind']),r['profile']['test'])for r in events if r.get('reason')=='compiler-artifact' and not r['fresh']);need(dirty==NORMAL_NONFRESH and len(obj1)==216 and all(r['same_pinned_donor']for r in obj1.values()),'different compile roster or fewer retained native callers');save(case/'custody.json',dict(dirty=dirty,kept=len(obj1),roster=v1['roster'],elf=v1['native']['elf'],rlib=v1['native']['rlib'],client=v1['native']['client'],renderer=v1['native']['oracle'],test_count=v1['native']['test_count'],objects=h.canonical({n:r['sha256']for n,r in obj1.items()})))
    if profiled:
        m.fresh(name+'-before-clean-new');_,fresh,v2=h.checked_visit('C','new','clean',env,set(),key);need(v2['native']['elf']==v1['native']['elf']and v2['native']['rlib']==v1['native']['rlib']and all(fresh[n]['sha256']==rec['sha256']for n,rec in obj1.items()),'profiled incremental output differs from independent clean')

def summarize():
    normal=B/'ordinary/C-edit';case=B/'profiled/C-edit';need((normal/'custody.json').read_bytes()==(case/'custody.json').read_bytes(),'different unobserved proof');env,sdk=m.role('C');roles,exact,history,images,tasks,monitor=classify_exact(case,sdk);frames,rows=sample_rows(case);raw=json.loads((case/'record-counts.json').read_bytes());need(len(rows)==raw['PERF_RECORD_SAMPLE']and len(rows)>12000,'incomplete raw IP distribution');self_cost=Counter();inclus=Counter();samples=Counter();unassigned=0
    for pid,tid,at,period,leaf,stack in rows:
        need(period==PERIOD,'changed sample period');hist=history.get(pid,[]);cut=bisect_right(hist,(at,2**63-1));role=roles[hist[cut-1][1]] if cut else ('instrumentation' if pid==monitor else 'unattributed startup');unassigned+=(role=='unattributed startup');samples[role]+=1;dso,sym=frames[leaf[0]];self_cost[(role,dso,sym)]+=1
        for dso,sym in {frames[f[0]]for f in [leaf,*stack]}:inclus[(role,dso,sym)]+=1
    watched=json.loads((case/'clock.json').read_bytes());ordinary=json.loads((normal/'clock.json').read_bytes());need(all(e['enabled']==e['running']>0 and not e['event_errno']for e in (watched,ordinary)), 'whole inherited counter not usable');total=sum(v for k,v in exact.items()if k!='instrumentation');actual_samples=sum(v for k,v in samples.items()if k not in ('instrumentation','unattributed startup'));need(abs(total/watched['instructions']-1)<.016 and abs(actual_samples*PERIOD/total-1)<.06 and abs(watched['instructions']/ordinary['instructions']-1)<.06 and unassigned/len(rows)<.01,'profile changed work or sampled costs did not reconcile');need(exact['rustc:annotate_snippets']>0 and exact['rustc:ruff_db']>0 and exact['cargo']>0 and exact['Wild']>0,'missing ordinary compiler/linker process');
    native_rows=sorted({x for kind in (self_cost,inclus)for (_,_,x) in kind if x});demangled={}
    for i in range(0,len(native_rows),1500):
        raw_names=native_rows[i:i+1500];strings=subprocess.check_output(['/usr/bin/c++filt','-n'],input=('\n'.join(raw_names)+'\n').encode()).decode(errors='replace').splitlines();need(len(strings)==len(raw_names),'invalid demangler mapping');demangled.update(zip(raw_names,strings))
    def score(c):return [dict(role=k[0],dso=k[1],symbol=k[2],name=demangled.get(k[2],''),samples=count,estimated=count*PERIOD)for k,count in c.most_common()]
    with gzip.open(case/'symbols.json.gz','wt',compresslevel=2)as f:json.dump(dict(self=score(self_cost),inclusive=score(inclus)),f,separators=(',',':'))
    save(B/'terminal.json',dict(unscored=True,ordinary=ordinary,profiled=watched,exact_disjoint=exact,exact_total=total,sampled=samples,sample_period=PERIOD,samples=len(rows),unassigned=unassigned,threads=len(tasks),custody=json.loads((case/'custody.json').read_bytes()),top_self=score(self_cost)[:40],top_inclusive=score(inclus)[:40]));print('Exact role instructions',dict(exact),flush=True)

if __name__=='__main__':
    m.governance()
    {'host':lambda:m.host('Profile the remaining Ruff library-test edit'),'setup':setup,'ordinary':lambda:build('ordinary',False),'profile':lambda:build('profiled',True),'finish':summarize,'pack':h.pack}[sys.argv[1]]()
