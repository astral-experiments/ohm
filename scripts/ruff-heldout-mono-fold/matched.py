"""A single unmetered real Rust P/C old→new→independent-new calibration on Ruff #27470."""
from contextlib import ExitStack
import gzip,hashlib,json,os,platform,re,shutil,struct,subprocess,sys,tarfile,tomllib
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE));import old_probe as old,role_graph as rg
CFG=json.loads((HERE/'matched.json').read_bytes());need,sha,save=old.need,old.sha,old.store
WS=Path(os.environ['GITHUB_WORKSPACE']).resolve();ROOT=Path(os.environ['RUNNER_TEMP']).resolve()/'upstream-mono-study';OUT=ROOT/'heldout-proof';W=ROOT/'heldout-private';SRC=WS/'ruff';STATE=W/'state';CHANGED=['crates/ruff_annotate_snippets/src/renderer/source_map.rs','crates/ruff_annotate_snippets/tests/ruff.rs']
NATIVE=OUT/'native'
FACTORY=WS/'factory';QUERY=WS/'dictionary';sys.path.insert(0,str(QUERY/'scripts/ruff-query-dictionary'));import resolve
sys.path.insert(0,str(FACTORY/'scripts/ruff-upstream-mono-pilot'));import normal_registry
SCHEMA_FILE=FACTORY/'scripts/ruff-upstream-mono-pilot/graph-kinds.json';need(sha(SCHEMA_FILE)==CFG['schema_sha256'],'schema source changed');SCHEMA=json.loads(SCHEMA_FILE.read_bytes())
RNAME='core::iter::adapters::map::{{impl}}[2]::fold'
TYPED={'upstream_monomorphizations_for','optimized_mir','generics_of','predicates_of','type_of','codegen_fn_attrs','fn_sig','is_mir_available'}
INPUT=b'''#[inline(never)]
fn project(values: &[usize], x: usize) -> usize {
    Iterator::fold(Iterator::map(values.iter(), |v| *v ^ x), 0usize, |a,b| a.wrapping_add(b))
}
fn main() {
    let r=project(std::hint::black_box(&[2,8,15]),std::hint::black_box(1));
    assert_eq!(r,26); assert_eq!(project(std::hint::black_box(&[]),7),0); println!("{r}");
}
'''

def git(*args):return subprocess.check_output(['git','-C',SRC,*args],text=True).strip()

def switch(rev):
    commit=CFG[rev+'_commit'];tree=CFG[rev+'_tree'];need(not git('status','--porcelain','--untracked-files=all'),'dirty historical tree');subprocess.run(['git','-C',SRC,'checkout','-q','--detach',commit],check=True);need(git('rev-parse','HEAD')==commit and git('rev-parse','HEAD^{tree}')==tree and sha(SRC/'Cargo.lock')==old.LOCK,'different Ruff inputs')

def gz(path,out):
    with path.open('rb')as f,out.open('xb')as raw,gzip.GzipFile(filename='',mode='wb',fileobj=raw,compresslevel=1,mtime=0)as z:shutil.copyfileobj(f,z,1<<20)
    return sha(path)

def blob(path):
    key=sha(path);out=NATIVE/f'{key}.zst'
    if not out.exists():
        need(0<path.stat().st_size<512<<20 and shutil.disk_usage(OUT).free>15*old.GB+path.stat().st_size,'insufficient archive scope')
        with out.open('xb')as f:subprocess.run(['zstd','-q','-2','-c',path],stdout=f,check=True,timeout=120)
    return key

def role(role):
    target=ROOT/'reopened'/({'P':'normal','C':'defer'}[role]);alias=W/'rustup/toolchains/ohm'
    if alias.is_symlink():alias.unlink()
    alias.symlink_to(target);env={'HOME':str(W/'home'),'TMPDIR':str(W/'temp'),'RUSTUP_HOME':str(W/'rustup'),'RUSTUP_AUTO_INSTALL':'0','CARGO_HOME':str(W/'cargo-home'),'CARGO_TARGET_DIR':str(STATE/'target'),'CARGO_BUILD_BUILD_DIR':str(STATE/'build'),'CARGO_NET_OFFLINE':'true','CARGO_CACHE_AUTO_CLEAN_FREQUENCY':'never','LC_ALL':'C','CARGO_TERM_COLOR':'never','PATH':str(W/'proxies')+':/usr/bin:/bin','LD_LIBRARY_PATH':str(target/'lib'),'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','SSL_CERT_FILE':'/etc/ssl/certs/ca-certificates.crt'}
    record=CFG['roles'][role];need(next(v for k,v in record['files'].items() if k.startswith('lib/librustc_driver-'))==CFG['earlier_driver_sha256'][role],'different previous pilot driver');p=ROOT/'capsule'/(role+'.json');need(sha(p)==record['manifest_sha256'] and json.loads(p.read_bytes())['commit']==record['commit'],'wrong factory role manifest');need(all(sha(target/k)==v for k,v in record['files'].items()) and sha(target/'bin/cargo')=='3ce4e300d4463dfc769b6c18e138d1c951b02dfb15416a39cb5301303d168871','role-specific binaries/metadata changed')
    for tool in ('cargo','rustc','rustdoc'):need((target/'bin'/tool).samefile(subprocess.check_output(['rustup','which','--toolchain','ohm',tool],env=env,text=True).strip()),'wrong resolved '+tool)
    vv=subprocess.check_output(['rustc','+ohm','-vV'],env=env,text=True).splitlines();doc=subprocess.check_output(['rustdoc','+ohm','-V'],env=env,text=True).strip();need('commit-hash: unknown' in vv and 'LLVM version: 23.1.1' in vv and doc.startswith('rustdoc 1.99.0-dev'),'wrong source-built tools');return env,target

def setup():
    OUT.mkdir();W.mkdir();(OUT/'native').mkdir();need(shutil.disk_usage(ROOT).free>27*old.GB and old.available()>9*old.GB,'worker admission guard');need(git('rev-parse',CFG['new_commit']+'^')==CFG['old_commit'] and git('diff','--name-only','--no-renames',CFG['old_commit'],CFG['new_commit']).splitlines()==CHANGED,'different real edit')
    for p in ('rustup/toolchains','home','proxies','temp','cargo-home','state'):(W/p).mkdir(parents=True)
    rustup=Path(shutil.which('rustup')).resolve(strict=True)
    for n in ('rustup','cargo','rustc','rustdoc'):(W/'proxies'/n).symlink_to(rustup)
    (W/'rustup/settings.toml').write_text('version = "12"\nprofile = "minimal"\n');switch('old');env,sdk=role('P');online=dict(env);del online['CARGO_NET_OFFLINE'];argv=[k for k in old.CMD if k!='--offline']+['-Zunstable-options','--unit-graph']
    with (OUT/'plan.json').open('xb')as f,(OUT/'prefetch.stderr').open('xb')as e:subprocess.run(argv,cwd=SRC,env=online,stdout=f,stderr=e,check=True,timeout=900)
    need(old.plan_id((OUT/'plan.json').read_bytes())==old.PLAN,'different frozen Cargo test graph');lock=tomllib.loads((SRC/'Cargo.lock').read_text());expected={x['name']+'-'+x['version']+'.crate':x['checksum'] for x in lock['package']if x.get('source','').startswith('registry+')};archives={f.name:sha(f) for f in (W/'cargo-home/registry/cache/index.crates.io-1949cf8c6b5b557f').glob('*.crate')};need(100<len(archives)<350 and all(expected.get(k)==v for k,v in archives.items()),'unverified source archive');save(OUT/'archives.json',archives);save(OUT/'setup.json',dict(qa=os.environ['REVIEWED_HEAD'],run=os.environ['GITHUB_RUN_ID'],boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),fact=json.loads((ROOT/'logs/factory.json').read_bytes()),normal=old.CMD,study='off-clock',state=str(STATE),source=str(SRC),plan=old.PLAN,registration=sha(HERE/'matched.json')))

def calibrate(which):
    env,sdk=role(which);schema=SCHEMA[CFG['roles'][which]['commit']];out=OUT/('profile-'+which);out.mkdir();root=W/('profile-'+which);root.mkdir();inc=root/'incremental';outprof=root/'prof';outprof.mkdir();source=root/'owner_key.rs';source.write_bytes(INPUT);core=old.core_identity(sdk,env);meta,=(sdk/'lib/rustlib/x86_64-unknown-linux-gnu/lib').glob('libcore-*.rmeta');raw_meta=subprocess.check_output(['rustc','+ohm','-Zls=root',meta],env=env);(out/'core-root.txt').write_bytes(raw_meta)
    cmd=['rustc','+ohm','--edition=2024','--crate-name','actual_owner_key','--crate-type=bin',str(source),'-Copt-level=0','-Ccodegen-units=8','-Cincremental='+str(inc),'-Zself-profile='+str(outprof),'-Zself-profile-events=default,query-keys','-o',str(root/'actual')]
    with (out/'stderr').open('xb') as err:
        p=subprocess.Popen(cmd,cwd=root,env=env,stdout=subprocess.PIPE,stderr=err);_,_=p.communicate(timeout=120);need(p.returncode==0,'key probe compilation failed')
    verdict=subprocess.check_output([root/'actual'],env=env);need(verdict==b'26\n','wrong key calibration executable');profile,=outprof.glob('*.mm_profdata');graph,=inc.glob('actual_owner_key-*/s-*/dep-graph.bin');need(profile.stat().st_size<64<<20 and graph.stat().st_size<32<<20 and not graph.parent.name.endswith('-working'),'ambiguous owner profile');cg=gz(graph,out/'graph.gz');cp=gz(profile,out/'profile.gz');pid=int(profile.stem.rsplit('-',1)[1]);metadata,mapping,events=resolve.parse_profile(out/'profile.gz');exe,sep,arguments=metadata['cmd'].partition(' ');actual=metadata['cmd'];need(metadata['process_id']==pid and sep and arguments==' '.join(cmd[2:])+' ' and (exe=='rustc' or Path(exe).samefile(sdk/'bin/rustc')),'profile embedded command/PID differs');sought={}
    for i,name in mapping.items():
        k,sep,term=name.partition('\x1e')
        if sep and term==RNAME and k in TYPED:sought[i]=k
    g=rg.graph(graph,schema['format'],schema['names'],chosen_indices=sought);joined=[]
    for idx,k in sought.items():
        row=g['rows'].get(idx);need(row and row['kind']==k and row['key'][:16]==f'{core:016x}','profile/input query mismatch');joined.append(row|{'item':RNAME,'events':events.get(idx,{})})
    keys={r['key']for r in joined};need(len(keys)==1 and any(r['events']for r in joined),'no unique process-local complete definition key');key,=keys
    save(out/'key.json',dict(role=which,key=key,full_input=schema['format'],core=f'{core:016x}',core_rmeta=sha(meta),argv=cmd,profile_command=actual,launcher=p.pid,pid=pid,graph_sha256=cg,profile_sha256=cp,profile_name=profile.name,source=INPUT.decode(),joined=joined,returncode=p.returncode,verdict='26'));print(which,'physically named',key,len(joined),flush=True);return key

def elf(path):
    import mmap
    with path.open('rb')as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)as b:
        need(b[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<H',b,18)[0]==62,'not x86_64 ELF');off=struct.unpack_from('<Q',b,40)[0];size,num,ns=struct.unpack_from('<HHH',b,58);need(size==64 and 0<ns<num<65535,'bad ELF section table')
        sec=[struct.unpack_from('<IIQQQQIIQQ',b,off+i*size)for i in range(num)];names=b[sec[ns][4]:sec[ns][4]+sec[ns][5]];rows=[];ids=[]
        for name,typ,flags,addr,start,n,_,_,align,entsz in sec:
            if not flags&2:continue
            end=names.index(0,name);label=names[name:end].decode();v=[label,typ,flags,addr,n,align,entsz,None if typ==8 else hashlib.sha256(b[start:start+n]).hexdigest()]
            (ids if label=='.note.gnu.build-id' else rows).append(v)
    return dict(allocated=hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest(),sections=rows,build_id_sections=ids)

def exports(rlib):
    raw=subprocess.check_output(['/usr/bin/nm','--extern-only','--defined-only','--format=posix',rlib],stderr=subprocess.DEVNULL);symbols=sorted(set(l.split(None,1)[0]for l in raw.splitlines()if l.startswith(b'_R') and b' T 'in l));pretty=subprocess.check_output(['/usr/bin/c++filt','-s','rust'],input=b'\n'.join(symbols)+b'\n').splitlines();results=[]
    for sym,name in zip(symbols,pretty,strict=True):
        if not re.match(rb'^<core\[[a-f0-9]+\]::iter::adapters::map::Map<',name):continue
        depth=0
        for end,byte in enumerate(name):
            depth+=(byte==ord('<'))-(byte==ord('>'))
            if depth==0:break
        receiver=name[:end+1]
        if name[end+1:].startswith(b'::fold::<') and b'::snippet::Patch' in receiver and b'::splice_lines::{closure' in receiver and (b'::min_by' in name or b'::max_by' in name):results.append({'symbol':sym.decode(),'demangled':name.decode()})
    return results

FRAMES={'snippet_with_cell':[('8107245c9b6484aa48b669385796eb7b9a2bf02b0d876eba38a5bae63a7eafc4',57),('7562ecc7c13f70e1350ae8638a3de4c6825d9a21ec5f689d0712d3fefc6db72a',77)],'multiple_insertions':[('56824e6c67c6f3b4802441380dfc6e5beb0714b2858c03aa229630541291f0c5',250),('bf44f50ffcfa9baccbc13b19bcaecec6c755e17cbdd351146db0a16a14156c93',300)]}

def native(rev,rows,case,env):
    arts=[r for r in rows if r.get('reason')=='compiler-artifact'];test,=[r for r in arts if r['target']['name']=='ruff_db' and r['target']['kind']==['lib'] and r['profile']['test']];provider,=[r for r in arts if r['target']['name']=='annotate_snippets' and r['target']['kind']==['lib'] and r['features']==['default','simd','std']];exe=Path(test['executable']);lib,=(Path(f) for f in provider['filenames'] if f.endswith('.rlib'));need(all(p.resolve(strict=True).is_relative_to(STATE)for p in (exe,lib)) and sha(HERE/'oracle.rs')==CFG['oracle_sha256'],'wrong native product');cwd=SRC/'crates/ruff_db';inv=subprocess.check_output([exe,'--list','--format','terse'],cwd=cwd,env=env,timeout=60);(case/'tests.list').write_bytes(inv);need(hashlib.sha256(inv).hexdigest()==CFG['tests']['sha256'] and len(inv.splitlines())==CFG['tests']['count'],'different signed test inventory')
    tests={}
    for i,name in enumerate(old.TESTS):
        run=subprocess.run([exe,'--exact',name,'--test-threads=1'],cwd=cwd,env=env,capture_output=True,timeout=60);(case/f'test-{i}.stdout').write_bytes(run.stdout);(case/f'test-{i}.stderr').write_bytes(run.stderr);need(run.returncode==0 and f'test {name} ... ok'.encode() in run.stdout and b'test result: ok. 1 passed; 0 failed;' in run.stdout,'renderer snapshot failed');tests[name]=run.returncode
    symbols=exports(lib);need(len(symbols)==(2 if rev=='old' else 4) and all(('::ops::range::Range<usize>' in f['demangled'])==(rev=='new') for f in symbols),'different Old or New exported instantiations');save(case/'provider-folds.json',symbols)
    deps={p.parent for r in arts for s in r['filenames']for p in [Path(s)] if p.is_file()};guard=W/'renderer-client';args=['rustc','+ohm','--edition=2024','--crate-name','ohm_renderer_oracle',str(HERE/'oracle.rs'),'--extern','annotate_snippets='+str(lib),*['-Ldependency='+str(p)for p in sorted(deps)],'-o',str(guard)]
    run=subprocess.run(args,cwd=cwd,env=env,capture_output=True,timeout=90);(case/'oracle-link.stderr').write_bytes(run.stderr);save(case/'oracle-argv.json',args);need(run.returncode==0,'actual renderer caller did not link');verdict={}
    for name,frames in FRAMES.items():
        r=subprocess.run([guard,name],cwd=cwd,env=env,capture_output=True,timeout=15);(case/(name+'.stdout')).write_bytes(r.stdout);(case/(name+'.stderr')).write_bytes(r.stderr)
        if rev=='old' and name=='multiple_insertions':need(r.returncode==101 and not r.stdout and b'index out of bounds: the len is 11 but the index is 11' in r.stderr,'missing real Old behavior');verdict[name]=dict(exit=101,frames=[]);continue
        values=[];data=r.stdout
        while data:
            need(len(data)>=8,'truncated renderer framing');n=struct.unpack_from('<Q',data)[0];need(n<=len(data)-8,'truncated output');values.append((hashlib.sha256(data[8:8+n]).hexdigest(),n));data=data[8+n:]
        need(r.returncode==0 and not r.stderr and values==frames,'wrong genuine renderer output');verdict[name]=dict(exit=0,frames=values)
    return dict(elf=blob(exe),sections=elf(exe),rlib=blob(lib),client=blob(guard),test_count=len(inv.splitlines()),tests=tests,oracle=verdict,fresh={'ruff_db':test['fresh'],'annotate_snippets':provider['fresh']},exports=len(symbols))

def fresh(label):
    if STATE.is_dir():STATE.rename(W/('retained-'+label))
    STATE.mkdir()

def sessions():return {p.parent.resolve() for p in STATE.rglob('dep-graph.bin') if p.parent.parent.name.startswith('ruff_db-') and p.parent.name.startswith('s-') and not p.parent.name.endswith('-working')}

def safe_session(prev):
    current=sessions();new=current-prev
    if new:need(len(new)==1,'ambiguous newly completed consumer session');return next(iter(new)),True
    need(len(current)==1 and set(current)==prev,'ambiguous current Rust session');return next(iter(current)),False

def roster(rows):
    result=[]
    for r in rows:
        if r.get('reason')!='compiler-artifact':continue
        pkg=r['package_id'];pkg='ruff/crates/'+pkg.rsplit('/crates/',1)[-1] if pkg.startswith('path+file://') else pkg
        result.append([pkg,r['target']['name'],r['target']['kind'],r['features'],r['profile']['test']])
    return hashlib.sha256(json.dumps(sorted(result),separators=(',',':')).encode()).hexdigest()

def visit(which,rev,label,env,key,old_paths,pinned=None,focus=(),run_cargo=None):
    schema=SCHEMA[CFG['roles'][which]['commit']];switch(rev);case=OUT/(which+'-'+label);case.mkdir();planenv=dict(env,CARGO_TARGET_DIR=str(W/'plan-target'),CARGO_BUILD_BUILD_DIR=str(W/'plan-build'));plan=subprocess.check_output(old.CMD+['-Zunstable-options','--unit-graph'],cwd=SRC,env=planenv,timeout=75);need(old.plan_id(plan)==old.PLAN,'changed ordinary unit graph');(run_cargo or old.command)(old.CMD,env,SRC,case,STATE);rows=[json.loads(line)for line in (case/'cargo.stdout').read_bytes().splitlines()];need(rows[-1]=={'reason':'build-finished','success':True},'unknown successful Cargo');cold=label in ('old','clean');need(not cold or not any(r['fresh']for r in rows if r.get('reason')=='compiler-artifact'),'independent empty build saw a prebuilt product');placement=normal_registry.capture(rows,STATE,True);want=CFG['registry'];need((placement['sha256'],placement['products'],placement['shared'])==(want['sha256'],want['entries'],want['shared']),'real normal signed registry placement changed');save(case/'registry.json',placement)
    native_result=native(rev,rows,case,env);folder,new=safe_session(old_paths);graph=folder/'dep-graph.bin';work=folder/'work-products.bin';bucket=['upstream_monomorphizations_in'] if 'upstream_monomorphizations_in' in schema['names'] else [];g=rg.graph(graph,schema['format'],schema['names'],query=key if which=='P' else None,observe_kinds=bucket);refs=rg.products(work,schema['format']);need(set(g['roots'])==set(refs),'native CGU/work-product names do not join exactly');phase_focus={refs[k]['name']for k in g['paths']} if which=='P' and label=='old' else set(focus);objects={}
    for ck,entry in sorted(refs.items()):
        fn=entry['files'].get('o');need(fn and Path(fn).name==fn,'missing object donor');obj=folder/fn;stat=obj.stat();rec={'cgukey':ck,'product':entry['product'],'filename':fn,'identity':[stat.st_dev,stat.st_ino,stat.st_size],'sha256':sha(obj)};name=entry['name'];objects[name]=rec
        if name in phase_focus or not key:need(blob(obj)==rec['sha256'],'selected physical object changed while archiving')
        if pinned is not None and name in pinned:
            f,prior=pinned[name];st=os.fstat(f.fileno());need([st.st_dev,st.st_ino,st.st_size]==prior['identity'] and hashlib.file_digest(f,'sha256').hexdigest()==prior['sha256'],'live old object mutated');f.seek(0);rec['same_pinned_donor']=rec['identity']==prior['identity'];need(not rec['same_pinned_donor'] or rec['sha256']==prior['sha256'],'same inode changed')
    digests={'graph':gz(graph,case/'graph.bin.gz'),'work_products':gz(work,case/'work-products.bin.gz')};save(case/'objects.json',objects);save(case/'query.json',{'nodes':g['nodes'],'edges':g['edges'],'owner_count':g['owner_count'],'matches':g['hits'],'paths':{refs[k]['name']:v for k,v in g['paths'].items()},'bucket_rows':[v for v in g['rows'].values() if v['kind'] in bucket],'key':key,'schema':schema['format']});v=dict(role=which,source=CFG[rev+'_commit'],state=str(STATE),session=str(folder),new_session=new,native=native_result,roster=roster(rows),focus=sorted(phase_focus),digests=digests,count=len(objects));save(case/'visit.json',v);print(which,label,'native library test passed;',len(objects),'CGUs,',sum(r.get('same_pinned_donor',False) for r in objects.values()),'physically retained',flush=True);return folder,objects,v

def track(which):
    env,_=role(which);kp=OUT/('profile-'+which)/'key.json';pp=OUT/'profile-P/key.json';key=json.loads(kp.read_bytes())['key'] if kp.exists() else None;pkey=json.loads(pp.read_bytes())['key'] if pp.exists() else None;need(not key or not pkey or key==pkey,'roles disagree on identical core metadata');focus=[] if which=='P' or not (OUT/'P-old/visit.json').exists() else json.loads((OUT/'P-old/visit.json').read_bytes())['focus'];fresh(which+'-before-old');folder,obs,visit0=visit(which,'old','old',env,key,set(),focus=focus)
    if which=='P':focus=visit0['focus']
    with ExitStack() as stack:
        pins={n:(stack.enter_context((folder/v['filename']).open('rb')),v) for n,v in obs.items()};visit(which,'new','edit',env,key,{folder},pinned=pins,focus=focus)
    fresh(which+'-before-fresh-new');visit(which,'new','clean',env,key,set(),focus=focus)

def governance():
    need(os.environ['GITHUB_REPOSITORY']=='astral-experiments/ohm' and os.environ['GITHUB_REF']=='refs/heads/charlie/qa-heldout-test-residual-27470-20261102' and os.environ['GITHUB_RUN_ATTEMPT']=='1' and os.environ['GITHUB_EVENT_NAME']=='workflow_dispatch','wrong hosted event')
    for repo,rev in ((WS/'qa',os.environ['REVIEWED_HEAD']),(FACTORY,CFG['factory_receiver']),(QUERY,CFG['profile_reader'])):
        need(subprocess.check_output(['git','-C',repo,'rev-parse','HEAD'],text=True).strip()==rev and not subprocess.check_output(['git','-C',repo,'status','--porcelain','--untracked-files=all']), 'unregistered diagnostic source')
    need(os.environ['REVIEWED_HEAD']==os.environ['GITHUB_SHA'],'wrong QA commit')

def host(expected_job='Matched real Ruff test calibration'):
    governance();runid=int(os.environ['GITHUB_RUN_ID']);base='repos/astral-experiments/ohm/actions/runs/'+str(runid);r=json.loads(subprocess.check_output(['gh','api',base]));alljobs=json.loads(subprocess.check_output(['gh','api',base+'/attempts/1/jobs?per_page=100']));j,=alljobs['jobs'];need(r['head_sha']==os.environ['REVIEWED_HEAD'] and r['run_attempt']==1 and alljobs['total_count']==1 and j['name']==expected_job and j['runner_name']==os.environ['RUNNER_NAME'] and j['runner_id']>0,'wrong assigned worker');save(ROOT/'logs/heldout-worker.json',dict(run=runid,job=j['id'],runner_id=j['runner_id'],runner=j['runner_name'],head=r['head_sha'],boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()))

def value(q):
    values={r['value'] for r in q['matches']};need(len(values)<=1,'conflicting full-key rows');return next(iter(values),None)

def finish():
    def get(role,stage,file):return json.loads((OUT/(role+'-'+stage)/(file+'.json')).read_bytes())
    visits={r:{s:get(r,s,'visit') for s in ('old','edit','clean')} for r in 'PC'};reason=[];focus=visits['P']['old']['focus'];proof={}
    profiles=[OUT/('profile-'+r)/'key.json' for r in 'PC'];keys=[json.loads(p.read_bytes())['key'] if p.exists() else None for p in profiles]
    if not all(keys) or keys[0]!=keys[1]:reason.append('no matched role-specific named query calibration')
    vals={s:value(get('P',s,'query')) for s in ('old','edit','clean')};reverse=get('P','old','query')['paths'];need(set(reverse)==set(focus),'different caller inventory')
    if not focus:reason.append('P old test CGUs do not read the named owner result')
    if not vals['old'] or not vals['edit'] or not (vals['old']!=vals['edit']==vals['clean']):reason.append('no independently changed P owner result')
    if len({v['roster'] for role in visits.values() for v in role.values()})!=1:reason.append('different build rosters')
    role_native={};objects={};held={}
    for r in 'PC':
        rs=visits[r];wn=rs['edit']['native'];cn=rs['clean']['native'];ok=wn['oracle']==cn['oracle'] and wn['tests']==cn['tests'] and wn['test_count']==cn['test_count']==126;role_native[r]=dict(warm_elf=wn['elf'],fresh_elf=cn['elf'],raw_elf_equal=wn['elf']==cn['elf'],allocated_equal=wn['sections']['allocated']==cn['sections']['allocated'],raw_rlib_equal=wn['rlib']==cn['rlib'],verdicts_equal=ok)
        if not ok or not role_native[r]['allocated_equal'] or not role_native[r]['raw_rlib_equal']:reason.append(r+' warm/fresh native equality needs resolution')
        objects[r]={s:get(r,s,'objects')for s in ('old','edit','clean')};held[r]=sum(v.get('same_pinned_donor',False) for v in objects[r]['edit'].values())
    wins=[]
    for name in focus:
        detail={}
        for r in 'PC':
            if not all(name in objects[r][s] for s in ('old','edit','clean')):continue
            o,w,c=(objects[r][s][name]for s in ('old','edit','clean'));detail[r]=dict(old=o['identity'],edited=w['identity'],cold=c['identity'],old_sha=o['sha256'],edited_sha=w['sha256'],cold_sha=c['sha256'],kept=w.get('same_pinned_donor',False),matches_clean=w['sha256']==c['sha256'],dep_node=o['cgukey'],work_product=o['product'])
        proof[name]=detail
        if set(detail)=={'P','C'} and not detail['P']['kept'] and detail['C']['kept'] and detail['P']['matches_clean'] and detail['C']['matches_clean']:wins.append(name)
    if not wins:reason.append('no matched caller rebuilt by P and physically retained by C with clean bytes')
    if any(visits['P'][s]['native']['oracle']!=visits['C'][s]['native']['oracle'] for s in ('old','edit','clean')):reason.append('role native behavior differs')
    ca,cb=visits['P']['clean']['native'],visits['C']['clean']['native'];cross=dict(raw_elf_equal=ca['elf']==cb['elf'],allocated_equal=ca['sections']['allocated']==cb['sections']['allocated'],raw_rlib_equal=ca['rlib']==cb['rlib']);
    if not cross['allocated_equal'] or not cross['raw_rlib_equal']:reason.append('cross-role independently clean native equality needs resolution')
    res=dict(admitted=not reason,reasons=reason,unmetered=True,old_focus=focus,role_keys=keys,P_values=vals,physical=proof,properly_retained_callers=wins,retained_counts=held,object_counts={k:v['edit']['count']for k,v in visits.items()},role_native=role_native,cross_clean=cross);save(OUT/'terminal.json',res);print(json.dumps({k:v for k,v in res.items()if k not in ('physical','role_native')},sort_keys=True),flush=True)

def pack():
    if not OUT.exists():OUT.mkdir()
    for f in ('heldout-worker.json','factory.json','compiler-installations.json'):
        p=ROOT/'logs'/f
        if p.is_file():shutil.copyfile(p,OUT/f)
    if not (OUT/'terminal.json').exists() and not (OUT/'hardware-pilot.json').exists():save(OUT/'incomplete.json',dict(ref=os.environ['REVIEWED_HEAD'],run=os.environ['GITHUB_RUN_ID']))
    with tarfile.open(ROOT/'matched-heldout-proof.tar','x')as tf:tf.add(OUT,arcname='receipt',recursive=True)

def named_profiles():
    for r in 'PC':
        try:calibrate(r)
        except Exception as e:
            out=OUT/('profile-'+r);out.mkdir(exist_ok=True);save(out/'unresolved.json',dict(error=repr(e)));print(f'{r} profile not admitted; collecting the actual native histories and graph for independent review: {e}',flush=True)

if __name__=='__main__':
    action,=sys.argv[1:]
    if action=='pack':pack()
    else:
        governance();{'host':host,'setup':setup,'keys':named_profiles,'P':lambda:track('P'),'C':lambda:track('C'),'finish':finish}[action]()
