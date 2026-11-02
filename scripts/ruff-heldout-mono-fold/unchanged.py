"""Rehearse the actual first two unchanged Cargo commands, with physical output pins."""
from contextlib import ExitStack
from pathlib import Path
import hashlib,json,os,subprocess,sys
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE));import hardware as hw
m=hw.checked;need,save,sha=m.need,m.save,m.sha;BASE=m.OUT;MODES=('interleaved','adjacent','observed')


def setup():
    m.setup();cpu=hw.cpu_binding();exe=m.W/'observe-exec';subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',HERE/'observe_exec.c','-o',exe],check=True);probe=BASE/'observer-control';probe.mkdir();cmd=[str(exe),str(probe),'/bin/sh','-c','/bin/true; /bin/false'];s=subprocess.run(cmd,env={'PATH':'/usr/bin:/bin'});need(s.returncode==1,'observer return mismatch');ex=[Path(row['exe']).name for row in trace(probe)];need(len(ex)==3 and set(ex)>={'true','false'},'incomplete physical child observer');save(BASE/'rehearsal.json',dict(boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),cpu=cpu,observer=sha(exe),signed_cargo=m.old.CMD,source_qa=os.environ['REVIEWED_HEAD'],rejected_counted_run=41437663932,observer_control=ex,mode='unscored'))


def trace(folder):
    roster=[]
    for path in sorted(folder.glob('*.nul')):
        words=path.read_bytes().split(b'\0');need(words.pop()==b'' and len(words)>=5,'truncated exec');pid,dev,ino,exe,*argv=words;roster.append(dict(sequence=int(path.stem),pid=int(pid),exe=os.fsdecode(exe),identity=[int(dev),int(ino)],argv=[os.fsdecode(a) for a in argv]))
    return roster


def records(case):return [json.loads(l)for l in (case/'cargo.stdout').read_bytes().splitlines()]

def files(rows):
    test,=[v for v in rows if v.get('reason')=='compiler-artifact' and v['target']['name']=='ruff_db' and v['target']['kind']==['lib'] and v['profile']['test']];render,=[v for v in rows if v.get('reason')=='compiler-artifact' and v['target']['name']=='annotate_snippets' and v['target']['kind']==['lib'] and v['features']==['default','simd','std']];rlib,=[Path(p)for p in render['filenames']if p.endswith('.rlib')];return dict(test=Path(test['executable']),renderer=rlib)

def identity(p):
    st=p.stat();return [st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,sha(p)]

def session_candidates():return sorted(m.sessions(),key=lambda s:(s/'dep-graph.bin').stat().st_mtime_ns)

def before_units(session,stack):
    paths={p.name:p for p in session.glob('*.o')};need(len(paths)==216,'different real ruff_db donor count');files={k:(stack.enter_context(p.open('rb')),identity(p))for k,p in paths.items()};return files

def pin_products(rows,stack):return {k:(stack.enter_context(p.open('rb')),identity(p))for k,p in files(rows).items()}

def inventory(rows):
    arcs=[r for r in rows if r.get('reason')=='compiler-artifact'];need(rows[-1]=={'reason':'build-finished','success':True} and len(arcs)==171 and m.roster(rows)==hw.PROTOCOL['expected']['new']['native_roster'],'different source closure');return sorted([[r['package_id'],r['target']['name'],r['target']['kind'],r['profile']['test']]for r in arcs if not r['fresh']])

def check_pinned(prior,current):
    out={}
    for n,(fd,old)in prior.items():
        fd.seek(0);st=os.fstat(fd.fileno());need([st.st_dev,st.st_ino]==old[:2],'lost live physical descriptor');snapshot=[st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,hashlib.file_digest(fd,'sha256').hexdigest()];now=current[n];out[n]=dict(old=old,live_old_descriptor=snapshot,current=now,retained=old[:2]==now[:2],unchanged_bytes=old[-1]==now[-1],unchanged_mtime=old[3]==now[3]);
    return out

def actual(role,mode):
    hw.cpu_binding();b=json.loads((BASE/'rehearsal.json').read_bytes());need(sha(m.W/'observe-exec')==b['observer'] and b['boot']==Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'changed rehearsal');env,sdk=m.role(role);name=role+'-'+mode;m.OUT=BASE/name;m.OUT.mkdir();m.fresh(name+'-before-old');old,_,_=hw.checked_visit(role,'old','old',env,set(),hw.PROTOCOL['different_broad_row']['old']['key']);m.switch('new');case=m.OUT/'edit';case.mkdir();planenv=dict(env,CARGO_TARGET_DIR=str(m.W/'plan-target'),CARGO_BUILD_BUILD_DIR=str(m.W/'plan-build'));need(m.old.plan_id(subprocess.check_output(m.old.CMD+['-Zunstable-options','--unit-graph'],cwd=m.SRC,env=planenv))==m.old.PLAN,'different historical plan');m.old.command(m.old.CMD,env,m.SRC,case,m.STATE);rows=records(case);initial=inventory(rows);edited,new=m.safe_session({old});need(new,'real renderer edit did not produce a consumer session');m.normal_registry.capture(rows,m.STATE,True)
    if mode!='adjacent':
        n=m.native('new',rows,case,env);hw.check_native(role,'new',case,rows,dict(native=n),None);save(case/'native.json',n)
    outcome=[]
    with ExitStack()as stack:
        pins=before_units(edited,stack);products=pin_products(rows,stack);need(products['test'][1][-1]==hw.PROTOCOL['expected']['new']['elf_sha256'],'first actual edited test executable differs');previous=set(m.sessions());last=edited
        for stage in ('first','second'):
            folder=m.OUT/stage;folder.mkdir();command=m.old.CMD
            if mode=='observed':
                traceout=folder/'exec';traceout.mkdir();command=[str(m.W/'observe-exec'),str(traceout),*command]
            m.old.command(command,env,m.SRC,folder,m.STATE);current=records(folder);nonfresh=inventory(current);placement=m.normal_registry.capture(current,m.STATE,True);need((placement['sha256'],placement['products'],placement['shared'])==(m.CFG['registry']['sha256'],123,114),'normal registry layout changed');save(folder/'registry.json',placement);present=set(m.sessions());added=present-previous;need(len(added)<=1 and (added or last in present),'ambiguous consumer session');last=next(iter(added))if added else last;previous=present;physical=check_pinned(pins,{p.name:identity(p)for p in last.glob('*.o')});current_files=check_pinned(products,{k:identity(v)for k,v in files(current).items()});need(all(v['unchanged_bytes']for v in physical.values()) and current_files['test']['unchanged_bytes'],'changed native output on unchanged source');eb=trace(traceout) if mode=='observed' else [];save(folder/'exec.json',eb);save(folder/'physical.json',dict(edit_session=edited.name,current_session=last.name,new_session=bool(added),cgus=physical,products=current_files));outcome.append(dict(stage=stage,nonfresh=nonfresh,session_changed=bool(added),retained=sum(s['retained'] for s in physical.values()),cgus=len(physical),products=current_files,exec_count=len(eb),driver=[e for e in eb if e['identity']==[ (sdk/'bin/rustc').stat().st_dev,(sdk/'bin/rustc').stat().st_ino]],exec_programs=[Path(e['exe']).name for e in eb]))
    # All diagnostics and libtest execution follow the immediate pair in the adjacent control.
    # The previous test and renderer bytes are explicitly checked before reusing their paths.
    for stage in ('edit','first','second'):
        folder=m.OUT/stage;events=records(folder)
        if (folder/'native.json').exists():continue
        for k,p in files(events).items():need(sha(p)==products[k][1][-1],'a verdict would use different source-native bytes')
        n=m.native('new',events,folder,env);hw.check_native(role,'new',folder,events,dict(native=n),None);save(folder/'native.json',n)
    save(m.OUT/'redelivery.json',dict(role=role,mode=mode,boot=b['boot'],old_elf=hw.PROTOCOL['expected']['old']['elf_sha256'],edited=initial,observations=outcome));print(name,[(x['stage'],[t[1]for t in x['nonfresh']],x['retained'],x['session_changed'],x['exec_programs'])for x in outcome],flush=True)


def finish():
    allrows={}
    for role in 'PC':
        for mode in MODES:
            name=role+'-'+mode;r=json.loads((BASE/name/'redelivery.json').read_bytes());need(r['role']==role and r['mode']==mode and len(r['observations'])==2,'missing rehearsal');allrows[name]=r
    save(BASE/'terminal.json',dict(unscored=True,observations=allrows))

if __name__=='__main__':
    cmd=sys.argv[1];m.governance()
    if cmd=='host':m.host('Rehearse ordinary unchanged Ruff library tests')
    elif cmd=='setup':setup()
    elif cmd in ('P','C'):
        mode=sys.argv[2];need(mode in MODES,'unknown rehearsal');actual(cmd,mode)
    elif cmd=='finish':finish()
    elif cmd=='pack':m.OUT=BASE;m.pack()
    else:raise ValueError(cmd)
