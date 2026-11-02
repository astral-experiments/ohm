"""Collect genuine scoped Cargo products in two corrected production compilers. No scored samples."""
import collections,gzip,hashlib,json,os,shutil,subprocess,sys,traceback
from pathlib import Path
H=Path(__file__).resolve().parent;sys.path.insert(0,str(H))
import bridge
from model import common,digest,dump,events,graph,require
def save(p,obj):
    with p.open('x')as f: json.dump(obj,f,sort_keys=True,separators=(',',':'));f.write('\n')
def load(p):return json.loads(p.read_bytes())
def hashfile(p):
    with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def custody(fn):
    s=fn.stat().st_size;require(0<=s<270<<20 and fn.is_file(),'unsupported declared artifact')
    return [s,hashfile(fn)]
def spool(p,sha):
    f=OUT/'blobs'/(sha+'.gz')
    if f.exists():return
    with p.open('rb')as a,f.open('xb')as b,gzip.GzipFile(filename='',mode='wb',compresslevel=2,fileobj=b,mtime=0)as out:shutil.copyfileobj(a,out,1<<20)
def primary(argv,hint=None):
    rows=[]
    for a in argv:
        if '--crate-name'not in a or a[a.index('--crate-name')+1]!='uv_resolver' or '--crate-type'not in a:continue
        if a[a.index('--crate-type')+1]!='lib':continue
        suffix,=[v.split('=',1)[1]for v in a if v.startswith('extra-filename=')]
        f=Path(a[a.index('--out-dir')+1])/('libuv_resolver'+suffix+'.rmeta')
        require(f.is_file()and f.stat().st_size>0 and f.resolve().is_relative_to(O.TARGET),'missing actual terminal output')
        rows.append(str(f.relative_to(O.TARGET)))
    if not rows and hint is not None:
        require((O.TARGET/hint).is_file(),'fresh terminal artifact absent');return hint
    require(len(rows)==1,'selected resolver is absent or repeated');return rows[0]
def snapshot(path,workspace,registry,direct):
    groups={'workspace-products':workspace,'registry-products':registry,'terminal-extern-inputs':direct}
    side={str(p.relative_to(O.TARGET))for p in O.TARGET.glob('debug/build/*/*/fingerprint/*.public-api-hash')}
    require(len(side)>100,'missing dependency/public sidecars');groups['public-sidecars']=side
    vals={}
    for name,paths in groups.items():
        rows={}
        for k in sorted(set(paths)):
            f=O.TARGET/k
            require(f.is_absolute()and f.resolve(strict=True).is_relative_to(O.TARGET)and f.is_file(),'outside package output')
            rows[k]=custody(f)
            if name!='registry-products':spool(f,rows[k][1])
        save(path/(name+'.json'),rows);vals[name]=rows
    return vals
def quiet(path,args):
    so,se=O.raw(path,args);require(not so,'ordinary command unexpectedly produced stdout');return se
def package_plan(path,phase):
    raw,_=O.raw(path,ARG+['--unit-graph','-Zunstable-options'],O.ENV|{'CARGO_TARGET_DIR':str(O.ROOT/'plan-target'),'RUSTC_BOOTSTRAP':'1'})
    x=graph(json.loads(raw));expected=load(H/'plan.json')
    require(all(x[k]==expected[k]for k in ('portable','units','modes','root')),'outside signed local source unit plan')
    save(path/'model.json',x);return x
def typed(path,state,plan,previous=None):
    raw,err=O.raw(path,ARG+['--message-format=json-render-diagnostics','-vv'])
    rows,msgs=events(raw,plan,True);save(path/'messages.json',msgs)
    args=O.native.commands(err.decode(),str(M.RUSTC));require(len({tuple(a)for a in args})==len(args),'duplicate actual compiler argv')
    root=primary(args,previous['root']if previous else None);declared={'workspace':set(),'registry':set()};producer=[];roster=[];dirty=[]
    for row in rows:
        k=common(row['package_id'],row['target'],row['features'])
        files=sorted({*row['filenames'],*([row['executable']]if row.get('executable')else[])})
        relative=[str(Path(f).relative_to(O.TARGET))for f in files];declared[k[0]].update(relative)
        if k[1]=='uv-workspace'and k[3]=='uv_workspace'and k[4]==['lib']:producer.extend(f for f in relative if f.endswith('.rmeta')and Path(f).name.startswith('libuv_workspace-'))
        roster.append([k,row['profile'],relative]);dirty.append([k,row['fresh']])
    require(producer and root in declared['workspace']or producer and any(Path(p).name=='libuv_resolver.rmeta'for p in declared['workspace']),'declared package, provider or actual terminal missing')
    declared['workspace'].add(root);save(path/'roster.json',sorted(roster,key=dump));save(path/'fresh.json',sorted(dirty,key=dump));save(path/'actual-argv.json',args)
    terminal_args=[a for a in args if a[a.index('--crate-name')+1]=='uv_resolver']
    if terminal_args:
        active,=terminal_args
        values=[active[i+1] for i,k in enumerate(active[:-1]) if k=='--extern']+[k.partition('=')[2] for k in active if k.startswith('--extern=')]
        direct=sorted({str(Path(v.partition('=')[2]).relative_to(O.TARGET))for v in values if '=' in v})
    else:direct=previous['direct']
    require(direct and all((O.TARGET/n).is_file()for n in direct),'missing actual selected external inputs')
    mats=snapshot(path,declared['workspace'],declared['registry'],direct)
    owners=sorted(set(producer))
    if previous is not None and not any(a[a.index('--crate-name')+1]=='uv_resolver'for a in args if '--crate-name'in a):
        prior,=[a for a in previous['argv']if a[a.index('--crate-name')+1]=='uv_resolver'];save(path/'fresh-terminal-fallback.json',{'kind':'prior cold compiler options for consumer of unchanged-on-disk metadata','argv':prior,'not_first_B_rustc':True})
    save(path/'witness-inputs.json',{'phase':state,'terminal':'uv_resolver','uv-resolver':[root],'uv-workspace':owners})
    # Only authenticated Cargo JSON events go to the witness; the original verbose stream is retained unchanged.
    with gzip.open(path/'cargo-events.jsonl.gz','xb')as f:
        for line in raw.splitlines(keepends=True):
            if line.startswith(b'{'):f.write(line)
    return {'ws':sorted(declared['workspace']),'reg':sorted(declared['registry']),'direct':direct,'root':root,'owners':owners,'argv':args,'mats':mats}
def source(state):
    O.remove_state();O.copy_many([POOL/'uv',POOL/'cargo',POOL/'home'],O.ROOT)
    O.verify_tree('A');require(not O.TARGET.exists(),'not independently cold')
    if state=='B':O.apply_edit(DELTA)
def freeze(path,role):
    path.mkdir()
    for f in (O.SRC,O.TARGET,O.CARGO_HOME,O.USER_HOME):f.rename(path/f.name)
    d=M.seed_state(path,role);return d
def restore(path,stamp,role):
    O.remove_state();O.copy_many([path/n for n in ('uv','target','cargo','home')],O.ROOT)
    require(M.seed_state(O.ROOT,role)==stamp,'seed bytes, metadata, or times differ');O.verify_tree('A');O.apply_edit(DELTA)
def witness(state,label,visit,d):
    O.verify_tree(state);gz=d/(label+'-cargo.jsonl.gz')
    shutil.copyfile(visit/'cargo-events.jsonl.gz',gz)
    out,_=O.raw(d/(label+'-witness'),[sys.executable,'-ISB',str(H/'witness.py'),state,str(O.SRC),str(O.TARGET),str(O.SDK)],O.ENV|{'OHM_WITNESS_CARGO_JSONL':str(gz),'OHM_22635_PACKAGE_VISIT':str(visit)})
    v=json.loads(out);require(v=={'edit':22635,'member':'seeds','virtual_root_reuses_cache':True,'member_reuses_cache':True,'cache_value_stores_project_name':state=='B'},'wrong linked native cache behavior')
    return v
def kernel(path,oracle,role):
    K.capture(path,ARG,O.ENV,O.SRC,M.RUSTC,role,IDX['installed'][role]['runtime'])
    tr=K.k.decode(load(path/'kernel-events.json'));root=tr['images'][0];require(root['argv']==ARG and root['file']==K.k.file_id(Path(ARG[0]))and tr['exits'][tr['root']]==0,'not the unwrapped native Cargo command')
    sha=K.k.file_id(M.RUSTC);rr=[]
    for im in tr['images']:
        a=im.get('argv',[])
        if im['file']==sha or Path(im['exe']).name=='rustc' or a and Path(a[0]).name=='rustc':
            require(im['file']==sha and a[0]==im['exe']==str(M.RUSTC)and tr['exits'].get(im['pid'])==0,'foreign or failing compiler')
            rr.append([im['pid'],a])
    save(path/'kernel-compilers.json',rr)
    require(sorted(a for _,a in rr)==sorted(oracle),'verbose pool differs from ordinary kernel pool')
def one(role):
    d=OUT/role;d.mkdir();seed=POOL/('resolver-frozen-'+role);gates={};attempts={}
    source('A');gA=package_plan(d/'A-plan','A');a=typed(d/'A-cold-typed','A',gA)
    def w(state,l,folder):
        try:attempts[l]=witness(state,l,d/folder,d)
        except Exception:attempts[l]={'error':traceback.format_exc()}
    w('A','parent','A-cold-typed')
    source('A');quiet(d/'A-cold-ordinary',ARG);snapshot(d/'A-cold-ordinary',a['ws'],a['reg'],a['direct']);stamp=freeze(seed,role);save(d/'A-seed.json',stamp)
    source('B');gB=package_plan(d/'B-plan','B');gates['same_actual_native_graph']=gA==gB
    c=typed(d/'B-cold-typed','B',gB);w('B','clean-child','B-cold-typed')
    source('B');quiet(d/'B-cold-ordinary',ARG);snapshot(d/'B-cold-ordinary',c['ws'],c['reg'],c['direct'])
    restore(seed,stamp,role);quiet(d/'B-first-ordinary',ARG);snapshot(d/'B-first-ordinary',c['ws'],c['reg'],c['direct'])
    restore(seed,stamp,role);b=typed(d/'B-first-typed','B',gB,c);w('B','edited','B-first-typed')
    restore(seed,stamp,role);kernel(d/'B-first-kernel',b['argv'],role);snapshot(d/'B-first-kernel',b['ws'],b['reg'],b['direct'])
    gates['all_visits_same_declared_package_products']=all(x['ws']==b['ws']and x['reg']==b['reg']and x['direct']==b['direct']and x['root']==b['root']and x['owners']==b['owners']for x in(a,c))
    gates['actual_ordinary_terminal_and_changed_provider']=all(any(v[v.index('--crate-name')+1]==name for v in b['argv'] if '--crate-name'in v) for name in('uv_resolver','uv_workspace'))
    save(d/'witnesses.json',attempts);save(d/'observed.json',{'role':role,'terminal':b['root'],'providers':b['owners'],'gates':gates,'native_scored':False})
    O.remove_state();require(seed.parent==POOL and not seed.is_symlink(),'unexpected seed');shutil.rmtree(seed)
def main():
    global W,T,M,O,K,IDX,OUT,POOL,ARG,DELTA
    W,T,M,sd=bridge.base.load();sys.path.insert(0,str(sd));O=M.load('original_scoped_history',sd/'opening.py');K=M.load('auth_package_kernel',M.HERE/'compiler_observer.py')
    ARG=[*O.PLAIN,'-p','uv-resolver','--lib'];require(ARG==[str(M.SDK/'bin/cargo'),'check','--locked','--offline','-j8','-p','uv-resolver','--lib']and all(q not in O.ENV for q in('RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','CARGO_LOG')),'wrong ordinary package command')
    M.ENV=O.ENV;OUT=W/'trait-results';POOL=O.ROOT/'bank';IDX=load(OUT/'intake.json')
    require(IDX['sdk_lock_sha256']==bridge.base.P['production_lock_sha256'] and IDX['build_run']==bridge.base.P['build_run'] and set(IDX['installed'])==set(bridge.base.P['roles']),'both authenticated SDKs')
    O.capacity(OUT/'free-at-start.json',126<<30);require(not O.ROOT.exists(),'fixed package path in use');O.ROOT.mkdir(mode=0o700);POOL.mkdir();(OUT/'blobs').mkdir()
    for role in bridge.base.P['roles']:(T/'ctfe22-root-sdks'/role).rename(POOL/('sdk-'+role))
    M.choose('stock_ctfe318',POOL,IDX['installed']);O.USER_HOME.mkdir();O.CARGO_HOME.mkdir()
    subprocess.run(['git','clone','--no-checkout',(W/'uv-source').as_uri(),str(O.SRC)],env=O.ENV,check=True);O.source('checkout','-q','--detach',O.A)
    DELTA=O.history();O.verify_tree('A');(OUT/'A-B.patch').write_bytes(DELTA)
    O.raw(OUT/'fetch',[str(M.SDK/'bin/cargo'),'fetch','--locked'],O.ENV|{'CARGO_NET_OFFLINE':'false'});save(OUT/'registry.json',O.registry())
    O.copy_many([O.SRC,O.CARGO_HOME,O.USER_HOME],POOL);fail={}
    for role in('stock_ctfe318','fa7a_stack_ctfe318'):
        M.choose(role,POOL,IDX['installed'])
        try:one(role)
        except Exception:fail[role]=traceback.format_exc()
    final={};panel=M.load('qualified_postrun_sdk',M.HERE/'run.py')
    for role in('stock_ctfe318','fa7a_stack_ctfe318'):
        M.choose(role,POOL,IDX['installed']);final[role]=panel.final_sdk(role,IDX['installed'],O.SDK,OUT)
    save(OUT/'final-sdk.json',final)
    save(OUT/'collection.json',{'source':bridge.base.P['source'],'roles':list(bridge.base.P['roles']),'errors':fail,'scored':False});require(not fail,'incomplete package collection')
if __name__=='__main__':main()
