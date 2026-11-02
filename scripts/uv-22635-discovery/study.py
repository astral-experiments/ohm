"""Compare authentic ordinary uv checks using disjoint observations of each saved parent."""
import gzip,hashlib,json,os,re,shutil,subprocess,sys,time,traceback
from collections import Counter
from urllib.parse import unquote
from pathlib import Path
here=Path(__file__).resolve().parent;sys.path.insert(0,str(here))
import bridge
G=bridge.guard;P=bridge.P;REF=bridge.R
def init():
    global W,T,M,O,N,OUT,PANEL,KERNEL,PER,POOL,META,SEED,IDX
    W,T,M,sd=bridge.load();PANEL=M.load('qualified_bare_observer',M.HERE/'run.py')
    KERNEL=M.load('qualified_kernel_trace',M.HERE/'compiler_observer.py');PER=M.load('qualified_target_pmu',here/'per_rustc.py')
    sys.path.insert(0,str(sd));O=M.load('real_22635_opening',sd/'opening.py');N=O.native
    G(O.PLAIN==M.ARGS and O.SDK==M.SDK and 'RUSTC_WRAPPER'not in O.ENV and 'RUSTC_WORKSPACE_WRAPPER'not in O.ENV,'ordinary signed Cargo command and source')
    # Only the timed runner uses this inherited environment. The signed opening fixes its complete contents.
    M.ENV=O.ENV;OUT=W/'trait-results';POOL=O.ROOT/'bank';SEED=POOL/'22635-frozen';IDX=M.read(OUT/'intake.json')
    G(IDX['sdk_lock_sha256']==P['production_lock_sha256']and IDX['build_run']==P['build_run']and IDX['installed'].keys()==P['roles'].keys(),'effective SDK set')
def snapshot(path,workspace):
    form={}
    files={Path(f)for row in workspace for f in row[-1]}
    G(len(files)==99 and sum(p.suffix=='.rmeta'for p in files)==96,'registered 99 products and 96 metadata members')
    side=sorted(O.TARGET.glob('debug/build/*/*/fingerprint/*.public-api-hash'));G(len(side)>400,'missing Cargo public sidecars')
    for f in sorted(files|set(side)):
        G(f.resolve(strict=True)==f and f.is_relative_to(O.TARGET)and f.is_file()and f.stat().st_size<200<<20,'unexpected output')
        size=f.stat().st_size;h=M.filesha(f);rel=str(f.relative_to(O.TARGET));form[rel]=[size,h];dest=OUT/'blobs'/(h+'.gz')
        if f in files and not dest.exists():
            with f.open('rb')as a,dest.open('xb')as b,gzip.GzipFile(filename='',mode='wb',compresslevel=2,fileobj=b,mtime=0)as g:shutil.copyfileobj(a,g,1<<20)
        if f in side:
            raw=f.read_bytes();G(0<len(raw)<=1024,'invalid public hash')
            if not dest.exists():dest.write_bytes(gzip.compress(raw,mtime=0))
    receipt=path/'all-products.json'
    if receipt.exists():G(M.read(receipt)==form,'actual products changed since initial capture')
    else:M.save(receipt,form)
    return form
def cargo_stream(raw):
    counts=Counter();owners=Counter();executed=set();tail=False
    for line in raw.decode('utf-8').splitlines():
        G(not tail,'data after native build-finished')
        if not line.startswith('{'):
            match=re.fullmatch(r'\[([^\s\]]+) ([^\s\]]+)\](?: .*)?',line)
            G(match is not None,'untagged stdout in Cargo stream');owners[match.groups()]+=1;continue
        row=json.loads(line);reason=row['reason']
        G(reason in ('compiler-artifact','build-script-executed','build-finished'),'unexpected signed Cargo event')
        counts[reason]+=1
        if reason=='build-script-executed':
            base,frag=row['package_id'].rsplit('#',1)
            executed.add(tuple(frag.rsplit('@',1))if '@'in frag else(unquote(base.rsplit('/',1)[1]),frag))
        if reason=='build-finished':
            G(row=={'reason':'build-finished','success':True},'failed or malformed final event');tail=True
    G(tail and counts=={'compiler-artifact':649,'build-script-executed':54,'build-finished':1} and set(owners)<=executed,'incomplete or foreign signed Cargo stream')
    return {'counts':dict(counts),'script_stdout':sorted([*k,v]for k,v in owners.items())}
def typed(path,verbose=False):
    form=O.typed(path,O.TYPED+(['-vv']if verbose else[]),META)
    G(form['workspace']==REF['workspace']and form['roster_sha256']==REF['signed_roster'],'signed Cargo target, feature or file roster')
    # Save the real outputs before applying additional diagnostic interpretation.
    snapshot(path,form['workspace']);M.save(path/'events.json',cargo_stream((path/'stdout').read_bytes()))
    if verbose:
        args=N.commands((path/'stderr').read_text(),str(M.RUSTC));G(args and len({tuple(a)for a in args})==len(args),'typed compile roster')
        M.save(path/'actual-rustc.json',args)
    return form
def fresh(state):
    O.remove_state();O.copy_many([POOL/'uv',POOL/'cargo',POOL/'home'],O.ROOT);O.verify_tree('A')
    G(not O.TARGET.exists(),'independent cold target');O.apply_edit(DELTA)if state=='B'else None
def save_seed(path,role):
    G(not path.exists(),'independent seed destination');path.mkdir()
    for src in (O.SRC,O.TARGET,O.CARGO_HOME,O.USER_HOME):src.rename(path/src.name)
    return M.seed_state(path,role)
def restore(path,stamp,role,state,edit=False):
    O.remove_state();O.copy_many([path/n for n in ('uv','target','cargo','home')],O.ROOT)
    G(M.seed_state(O.ROOT,role)==stamp,'source, target, registry or home differs from frozen bytes and times');O.verify_tree(state)
    if edit:O.apply_edit(DELTA)
def selectors(args):
    out={}
    for label in P['selectors']:
        seq=[a for a in args if a[a.index('--crate-name')+1]==label and '--crate-type'in a and a[a.index('--crate-type')+1]=='lib'
             and any(v.endswith('/crates/'+label.replace('_','-')+'/src/lib.rs')or v=='crates/'+label.replace('_','-')+'/src/lib.rs'for v in a)]
        G(len(seq)==1,('expected one enrolled real library',label,seq));out[label]=seq[0]
    used={tuple(v)for v in out.values()}
    for a in args:
        if tuple(a)in used:continue
        crate=a[a.index('--crate-name')+1];kind=a[a.index('--crate-type')+1]
        sources=[t for t in a if t.endswith('.rs')];G(len(sources)==1,('source selector',crate,sources))
        # Complete argv remains the selector. This display label identifies an ordinal-free actual target.
        source=sources[0].removeprefix('/tmp/uv-workflow-search/uv/')
        h=hashlib.sha256(source.encode()).hexdigest()[:12]
        label=f'extra-{crate}-{kind}-{h}'
        G(re.fullmatch('[A-Za-z0-9_-]{1,80}',label)and label not in out,('duplicate actual source target',label))
        out[label]=a;used.add(tuple(a))
    G(len(out)==len(args)==len(used)<=128,'one-to-one scores for all actual compiler processes')
    return out
def record_link_origins(path,tree):
    def file(p):
        st=p.stat();return {'bytes':st.st_size,'sha256':M.filesha(p),'mtime_ns':st.st_mtime_ns,'stat_ctime_ns':st.st_ctime_ns}
    markers=(b'/dev/null/ohm-recheck-dependent-links:',b'/dev/null/ohm-recheck-dependent-links-v2:')
    root=O.TARGET/'debug';rows=[];positive={};dest=path/'native-marker-inputs';dest.mkdir();total=0
    for f in sorted(root.rglob('*.d')):
        G(f.resolve(strict=True)==f and f.is_relative_to(root)and f.stat().st_size<=16<<20,'unsafe or excessive dependency file')
        data=f.read_bytes();total+=len(data);G(total<=512<<20 and len(rows)<8000,'bounded dep-info diagnostic')
        found=[m.decode()for m in markers if any(line.strip()==m for line in data.splitlines())]
        # Exact Makefile phony definitions distinguish these markers from incidental string/file matches.
        key=str(f.relative_to(O.TARGET));h=M.digest(data);rows.append([key,len(data),h,found])
        if found:
            positive[key]=found;blob=dest/(h+'.gz')
            if not blob.exists():blob.write_bytes(gzip.compress(data,compresslevel=2,mtime=0))
    fp=O.SRC/'crates/uv-python-managed';generated=sorted((root/'build/uv-python-managed').glob('*/out/download-metadata.json.zst'))
    exes={Path(e['exe'])for e in tree['images']if '/build/uv-python-managed/'in e['exe']and Path(e['exe']).is_relative_to(O.TARGET)}
    objects={str(f):file(f)for f in [fp/'build.rs',fp/'download-metadata.json',*generated,*sorted(exes)]if f.is_file()}
    M.save(path/'link-origins.json',{'diagnostic_only':True,'raw_dep_info':rows,'native_marker_inputs':positive,'script_source_executables_and_generated':objects,'all_kernel_target_images':sorted(map(str,exes))})
def same_kernel(path,expected,with_logs,role,measured=False):
    env=O.ENV|({'CARGO_LOG':'cargo::core::compiler::fingerprint=trace'}if with_logs else{})
    if measured:
        path.mkdir();req={'command':O.PLAIN,'environment':env,'cwd':str(O.SRC),'compiler_path':str(M.RUSTC),'selectors':selectors(expected)}
        M.save(path.parent/'per-rustc-request.json',req)
        subprocess.run([sys.executable,'-ISB',here/'per_rustc.py','capture',path.parent/'per-rustc-request.json',path,T/'libohm_pmu.so'],check=True,timeout=1800)
        report=M.read(path/'per-rustc.json');G(set(report['targets'])==set(req['selectors']),'missing PMU process')
    else:KERNEL.capture(path,O.PLAIN,env,O.SRC,M.RUSTC,role,IDX['installed'][role]['runtime'])
    raw=M.read(path/'kernel-events.json');tree=KERNEL.k.decode(raw)
    G(tree['images'][0]['argv']==O.PLAIN and tree['images'][0]['file']==KERNEL.k.file_id(Path(O.PLAIN[0]))and tree['exits'][tree['root']]==0,'actual successful bare Cargo process')
    ident=KERNEL.k.file_id(M.RUSTC);seen=[]
    for im in tree['images']:
        a=im.get('argv',[])
        if im['file']==ident or Path(im['exe']).name=='rustc' or a and Path(a[0]).name=='rustc':
            G(im['file']==ident and a[0]==im['exe']==str(M.RUSTC)and tree['exits'].get(im['pid'])==0,'rustc identity/exit')
            seen.append((im['pid'],a))
    G(sorted(a for _,a in seen)==sorted(expected),'all real rustc arg vectors across Cargo and kernel')
    if with_logs:
        G(b'cargo::core::compiler::fingerprint'in(path/'stderr').read_bytes(),'missing requested Cargo fingerprint trace')
        # The native outputs and kernel visit have already completed. Diagnostics never alter Cargo's environment or files.
        try:record_link_origins(path,tree)
        except (OSError,ValueError)as err:M.save(path/'link-origin-unavailable.json',{'diagnostic_only':True,'failure':str(err)})
    if measured:
        by=dict(seen)
        for k,v in report['targets'].items():
            G(by[v['pid']]==req['selectors'][k]and v['argv']==by[v['pid']]and v['instructions']>0,'actual process PMU argv/positive result')
    M.save(path/'verified-kernel.json',{'compilers':seen,'kernel_sha256':M.filesha(path/'kernel-events.json'),'fingerprints':with_logs,'measured_threads':measured})
    return [a for _,a in seen]
def qualify(hold,role):
    D=OUT/f'hold{hold}-{role}';D.mkdir();path=SEED/f'hold{hold}-{role}';Q=D/'qualification';Q.mkdir()
    O.capacity(Q/'before-cold.json',48<<30);fresh('B');cold=typed(Q/'independent-cold-B');G(len(cold['dirty'])>400,'independent cold B not built');snapshot(Q/'independent-cold-B',cold['workspace']);O.witness('B','clean-child',Q/'independent-cold-B',Q)
    fresh('A');coldA=O.plain(Q/'cold-A');G(len(coldA['progress'])>400,'independent A not built')
    a=typed(Q/'parent-typed');G(a['dirty']==REF['states']['A']['dirty'],'signed recurring A unit selection');snapshot(Q/'parent-typed',a['workspace'])
    stamp=save_seed(path,role);M.save(Q/'parent-snapshot.json',stamp)
    def back(edit=False):restore(path,stamp,role,'A',edit)
    back();ap=typed(Q/'A-unchanged-vv',True);G(ap['dirty']==a['dirty'],'changed unchanged A roster');aa=M.read(Q/'A-unchanged-vv/actual-rustc.json');a0=snapshot(Q/'A-unchanged-vv',a['workspace'])
    back();same_kernel(Q/'A-unchanged-kernel-fingerprint',aa,True,role);G(snapshot(Q/'A-unchanged-kernel-fingerprint',a['workspace'])==a0,'noedit A diagnostic raw');back()
    O.witness('A','parent',Q/'parent-typed',Q)
    back(True);plain=O.plain(Q/'first-B-ordinary');target=snapshot(Q/'first-B-ordinary',a['workspace'])
    back(True);b=typed(Q/'first-B-typed');G(b['progress']==plain['progress']and snapshot(Q/'first-B-typed',b['workspace'])==target,'same-history ordinary/typed raw')
    O.witness('B','edited',Q/'first-B-typed',Q)
    back(True);v=typed(Q/'first-B-vv',True);vectors=M.read(Q/'first-B-vv/actual-rustc.json')
    G(v['dirty']==b['dirty']and snapshot(Q/'first-B-vv',b['workspace'])==target,'same-history all 99+sidecar verbose raw');selectors(vectors)
    back(True);seen=same_kernel(Q/'first-B-kernel',vectors,False,role);G(snapshot(Q/'first-B-kernel',b['workspace'])==target,'same-history first B kernel raw')
    late=SEED/f'hold{hold}-{role}-B';ss=save_seed(late,role)
    restore(late,ss,role,'B');bsteady=typed(Q/'B-unchanged-vv',True);bv=M.read(Q/'B-unchanged-vv/actual-rustc.json')
    G(bsteady['dirty']==a['dirty'],'unchanged B unit selection');b0=snapshot(Q/'B-unchanged-vv',b['workspace'])
    restore(late,ss,role,'B');same_kernel(Q/'B-unchanged-kernel-fingerprint',bv,True,role);G(snapshot(Q/'B-unchanged-kernel-fingerprint',b['workspace'])==b0,'noedit B diagnostic raw')
    subprocess.run([sys.executable,'-ISB',here/'canonical.py',Q/'first-B-ordinary/all-products.json',Q/'independent-cold-B/all-products.json',Q/'canonical.json'],check=True,timeout=750)
    G(late.parent==SEED and not late.is_symlink(),'bounded warm seed');shutil.rmtree(late)
    M.save(Q/'passed.json',{'role':role,'hold':hold,'actual_dirty_first':b['dirty'],'actual_dirty_unchanged':a['dirty'],'fully_verified_kernel_rustcs':len(seen),'rmeta':96,'all_outputs':len(target),'positive_behavior':True,'original_signed_raw_veto':True})
    return D,path,stamp,target,seen
def trial(role,order,q,cal,meter):
    D,path,stamp,target,vectors=q;vals={};ready=cal['ready']
    for mode in order['modes']:
        restore(path,stamp,role,'A',True);where=D/mode;PANEL.command(where,O.PLAIN,mode,Path(ready['plain']))
        r=M.read(where/'ordinary.json');G(r['boot']==ready['boot']and r['cpus']==ready['affinity']and r['env']==O.ENV and r['argv']==O.PLAIN,'bare visit command, host or environment')
        G(snapshot(where,REF['workspace'])==target,'same-seed '+mode+' raw divergence')
        if mode=='pmu':
            clock=meter.clock(where/'whole-clock.json',0);G(clock['enabled']==clock['running']>0 and clock['instructions']>0,'whole inherited PMU refused');vals['whole_cargo_userspace_instructions']=clock['instructions']
        else:vals['uninstrumented_elapsed_ns']=r['ns']
    M.save(D/'ordinary-accepted.json',{'values':vals,'order':order,'role':role,'discovery_only':True})
def target_trial(role,order,q):
    D,path,stamp,target,vectors=q
    vals=M.read(D/'ordinary-accepted.json')['values']
    restore(path,stamp,role,'A',True);where=D/'targeted-rustc';same_kernel(where,vectors,False,role,True)
    G(snapshot(where,REF['workspace'])==target,'separate target-specific gather changed native products')
    raw=M.read(where/'per-rustc.json')['targets']
    vals['selected_rustc_instructions']={k:raw[k]['instructions']for k in P['selectors']}
    vals['exploratory_other_rustc_instructions']={k:v['instructions']for k,v in raw.items()if k not in P['selectors']}
    M.save(D/'observed.json',{'values':vals,'role':role,'order':order,'discovery_only':True})
    G(path.parent==SEED and not path.is_symlink(),'bounded A seed');shutil.rmtree(path)
def run():
    global META,DELTA
    init();cal=M.read(OUT/'calibration.json');old,meter=M.pmu(W,T);host=old.cpu_receipt(OUT)
    G(cal['unmultiplexed_calibration_clocks']==28 and cal['ready']['boot']==host['boot'] and cal['ready']['affinity']==host['cpus'],'whole-Cargo calibration')
    targetcal=M.read(OUT/'target-calibration/calibration.json');G(targetcal['reexec_rejected'] and set(targetcal['known_two_instruction_loop'])=={'serial','threads','fork'},'target-only hardware calibration required')
    O.capacity(OUT/'initial-space.json',P['minimum_initial_free_gib']<<30)
    G(not O.ROOT.exists(),'fresh canonical path');O.ROOT.mkdir(mode=0o700);POOL.mkdir();SEED.mkdir();(OUT/'blobs').mkdir()
    for role in P['roles']:(T/'ctfe22-root-sdks'/role).rename(POOL/('sdk-'+role))
    M.choose('stock_ctfe318',POOL,IDX['installed']);O.USER_HOME.mkdir();O.CARGO_HOME.mkdir()
    subprocess.run(['git','clone','--no-checkout',(W/'uv-source').as_uri(),str(O.SRC)],env=O.ENV,check=True);O.source('checkout','-q','--detach',O.A)
    DELTA=O.history();O.verify_tree('A');(OUT/'A-B.patch').write_bytes(DELTA)
    O.raw(OUT/'fetch',[O.PLAIN[0],'fetch','--locked'],O.ENV|{'CARGO_NET_OFFLINE':'false'});M.save(OUT/'registry.json',O.registry())
    meta,_=O.raw(OUT/'metadata',[O.PLAIN[0],'metadata','--locked','--offline','--format-version','1']);META=json.loads(meta)
    G(META['workspace_root']==str(O.SRC)and META['target_directory']==str(O.TARGET),'honest root metadata')
    O.copy_many([O.SRC,O.CARGO_HOME,O.USER_HOME],POOL)
    failures={}
    for order in P['order']:
        qual={}
        for role in order['roles']:
            M.choose(role,POOL,IDX['installed'])
            try:qual[role]=qualify(order['hold'],role)
            except Exception:
                failures[f"hold{order['hold']}-qualification-{role}"]=traceback.format_exc()
        if set(qual)!=set(P['roles']):
            M.save(OUT/f"hold{order['hold']}-qualification-refusals.json",failures)
            raise ValueError('both independent roles must qualify before bare timing')
        for role in order['roles']:
            M.choose(role,POOL,IDX['installed']);trial(role,order,qual[role],cal,meter)
        # These restores never separate the ordinary measurements for the two roles.
        for role in order['roles']:
            M.choose(role,POOL,IDX['installed'])
            try:target_trial(role,order,qual[role])
            except Exception:
                text=traceback.format_exc();failures[f"hold{order['hold']}-target-{role}"]=text
                M.save(qual[role][0]/'target-refusal.json',{'score':False,'traceback':text})
    final={}
    for role in P['roles']:
        M.choose(role,POOL,IDX['installed']);final[role]=PANEL.final_sdk(role,IDX['installed'],O.SDK,OUT)
    M.save(OUT/'final-sdk.json',final)
    if failures:
        M.save(OUT/'measurement-refusals.json',failures);raise ValueError('separate process attribution unavailable; bare original clocks retained')
    M.save(OUT/'discovery-complete.json',{'pairs':2,'ordinary_command':O.PLAIN,'roles':P['roles'],'repeatability_claim':False,'signed_opening_strict_raw_gate':False})
if __name__=='__main__':run()
