"""Open uv #22635 on the signed compiler and retain raw ordinary/typed/independent-cold inputs."""
from pathlib import Path
import gzip,hashlib,json,os,shutil,subprocess,sys,tempfile,time,tomllib
from zipfile import ZipFile,ZIP_DEFLATED
H=Path(__file__).resolve().parent;sys.path.insert(0,str(H))
import sdk,native
C=sdk.CFG;A=C['A'];B=C['B'];DETAIL=C['source_details'];ENV=C['workload_environment']
ROOT=Path('/tmp/uv-workflow-search');SRC=ROOT/'uv';TARGET=ROOT/'target';CARGO_HOME=ROOT/'cargo';USER_HOME=ROOT/'home'
SDK=ROOT/'sdk';PLAIN=C['native_argv'];TYPED=PLAIN+['--message-format=json-render-diagnostics']
def require(condition,reason):
    if not condition:raise ValueError(reason)
def digest(b):return hashlib.sha256(b).hexdigest()
def write(path,value):
    with path.open('x')as f:json.dump(value,f,indent=2,sort_keys=True);f.write('\n')
def source(*args,env=None):
    return subprocess.check_output(['git','-C',SRC,*args],env=env or ENV)
def capacity(path,minimum):
    free=shutil.disk_usage(ROOT.parent).free
    write(path,{'available':free,'required':minimum});require(free>=minimum,'workspace capacity')
def history():
    tag='refs/tags/'+DETAIL['tag'];chain=source('rev-list','--parents','--topo-order',tag+'..'+B)
    require(source('rev-parse',B+'^',tag).decode().splitlines()==[A,DETAIL['tag_commit']]and digest(chain)==C['chain_sha256']and len(chain.splitlines())==DETAIL['distance_from_tag'],'real commit history')
    require(source('rev-parse',A+'^{tree}',B+'^{tree}').decode().splitlines()==DETAIL['trees'],'historical tree mismatch')
    require(source('diff','--name-only',A,B).decode().splitlines()==C['case']['changed_paths'],'unexpected source paths')
    for label,rev in [('A',A),('B',B)]:
        log=source('log','-1','--date=short','--abbrev=9','--format=%H %h %cd %(describe:tags)',rev).decode().strip()
        require(log==DETAIL['descriptions'][label],'actual input to uv-cli Git build metadata')
    patch=source('diff','--binary','--full-index',A,B)
    require(digest(patch)==DETAIL['git_patch_sha256'],'wrong one-file patch')
    return patch
def verify_tree(label):
    require(source('rev-parse','HEAD').decode().strip()==A and sdk.sha(SRC/'Cargo.lock')==DETAIL['lock_sha256'],'same parent HEAD and lock')
    with tempfile.TemporaryDirectory(dir=ROOT)as tmp:
        env=ENV|{'GIT_INDEX_FILE':str(Path(tmp)/'index')}
        source('read-tree',A,env=env);source('add','-u',env=env);tree=source('write-tree',env=env).decode().strip()
    require(tree==C['case'][label+'_tree'],'live source tree differs from real '+label)
    return tree
def apply_edit(patch):
    verify_tree('A');subprocess.run(['git','-C',SRC,'apply','--check'],env=ENV,input=patch,check=True)
    subprocess.run(['git','-C',SRC,'apply'],env=ENV,input=patch,check=True);verify_tree('B')
def raw(path,argv,env=ENV):
    path.mkdir()
    start=time.monotonic_ns()
    with (path/'stdout').open('xb')as so,(path/'stderr').open('xb')as se:
        r=subprocess.run(argv,cwd=SRC,env=env,stdout=so,stderr=se)
    write(path/'command.json',{'argv':list(map(str,argv)),'exit':r.returncode,'elapsed_ns':time.monotonic_ns()-start,'scored':False})
    if r.returncode:raise ValueError((str(argv[0]),r.returncode,(path/'stderr').read_bytes()[-2200:]))
    return (path/'stdout').read_bytes(),(path/'stderr').read_bytes()
def copy_many(srcs,dest):
    subprocess.run(['cp','-a','--reflink=auto','--',*srcs,dest],check=True)
def remove_state():
    for p in (SRC,TARGET,USER_HOME,CARGO_HOME):
        require(p.parent==ROOT and not p.is_symlink(),'unexpected state path')
        if p.exists():shutil.rmtree(p)
def registry():
    data=tomllib.loads((SRC/'Cargo.lock').read_text());packages=[]
    cache,=(CARGO_HOME/'registry/cache').iterdir();idx,=(CARGO_HOME/'registry/index').iterdir()
    for row in data['package']:
        if 'source'not in row:continue
        require(row['source']=='registry+https://github.com/rust-lang/crates.io-index','unexpected dependency source')
        n=row['name'];v=row['version'];k=n.lower();pre=str(len(k))if len(k)<=2 else ('3/'+k[0]if len(k)==3 else k[:2]+'/'+k[2:4])
        matches=[q for rawrow in (idx/'.cache'/pre/k).read_bytes().split(b'\0')if rawrow.startswith(b'{')and(q:=json.loads(rawrow))['vers']==v]
        require(len(matches)==1 and matches[0]['name']==n and matches[0]['cksum']==sdk.sha(cache/(n+'-'+v+'.crate'))==row['checksum'],'actual registry package or sparse index diverged')
        packages.append([n,v,row['checksum']])
    require(len(packages)==C['registry_entries']and digest(json.dumps(sorted(packages),separators=(',',':')).encode())==C['registry_sha256'],'all locked packages')
    return packages
def typed(dest,argv,meta):
    out,err=raw(dest,argv);rows=[json.loads(line)for line in out.splitlines()if line.startswith(b'{')]
    require(rows and rows[-1]=={'reason':'build-finished','success':True},'missing live Cargo tail')
    art=[r for r in rows if r['reason']=='compiler-artifact']
    # At -vv build scripts can interleave their tagged stdout with records. Keep the full original.
    allowed={p['id']:p for p in meta['packages']if p['id']in meta['workspace_default_members']}
    def shape(r):
        t=r['target'];return [r['package_id'],t['name'],t['kind'],t['src_path'],sorted(r['features']),sorted(r['filenames'])]
    roster=sorted(shape(r)for r in art)
    require(len(roster)>400,'complete ordinary Cargo workspace roster')
    workspace=sorted(shape(r)for r in art if r['package_id']in allowed and 'custom-build'not in r['target']['kind'])
    active=[r for r in workspace if r[1]=='uv' and r[2]==['bin']];require(active and len(allowed)>50,'ordinary uv workspace and executable')
    for pid,p in allowed.items():
        actual=[r for r in workspace if r[0]==pid];features=[set(r[4])for r in actual]or[set()]
        for t in p['targets']:
            if t['kind'][0]not in ('lib','bin','proc-macro','cdylib','staticlib','dylib','rlib'):continue
            selected=any(r[1:4]==[t['name'],t['kind'],t['src_path']]for r in actual)
            require(selected==any(set(t.get('required-features',[]))<=values for values in features),'ordinary Cargo target selection')
    provider=sorted({f for r in workspace if allowed[r[0]]['name']=='uv-workspace'and r[2]==['lib']for f in r[-1]if f.endswith('.rmeta')})
    require(provider and all(Path(f).resolve().is_relative_to(TARGET)and not Path(f).is_symlink()for f in provider),'actual checked provider')
    res={'roster_sha256':digest(json.dumps(roster).encode()),'workspace':workspace,'dirty':sorted(shape(r)for r in art if not r['fresh']),'progress':native.package_lines(err),'provider':{str(Path(f).relative_to(TARGET)):sdk.sha(Path(f))for f in provider}}
    write(dest/'roster.json',roster);write(dest/'state.json',res);return res
def plain(dest,paths=None):
    out,err=raw(dest,PLAIN);require(not out,'ordinary Cargo stdout');res={'progress':native.package_lines(err)}
    if paths:res['provider']={p:sdk.sha(TARGET/p)for p in paths}
    write(dest/'ordinary.json',res);return res
def keep_outputs(path,form):
    all_paths={Path(f)for r in form['workspace']for f in r[-1]if f.endswith('.rmeta')}
    with ZipFile(path,'x',compression=ZIP_DEFLATED,compresslevel=2)as z:
        for p in sorted(all_paths):
            require(p.resolve().is_relative_to(TARGET)and not p.is_symlink(),'unsafe workspace product');z.write(p,str(p.relative_to(TARGET)))
def unchanged(label,meta,out,reference=None):
    values=[]
    for i in range(1,6):
        ordinary=plain(out/(label+'-'+str(i)+'-ordinary'))
        form=typed(out/(label+'-'+str(i)+'-typed'),TYPED,meta)
        require(ordinary['progress']==form['progress'],'ordinary/typed unchanged progress')
        values.append(form)
    require(all(v==values[0]for v in values),'five identical unchanged visits')
    if reference:
        for k in ('dirty','progress','roster_sha256','workspace'):require(values[-1][k]==reference[k],'changed unchanged-selection: '+k)
    return values[-1]
def witness(phase,label,fromdir,out):
    rawfile=fromdir/'stdout';gz=out/(label+'-cargo.jsonl.gz')
    with rawfile.open('rb')as source_stream,gzip.open(gz,'xb',compresslevel=2)as dst:shutil.copyfileobj(source_stream,dst)
    require(sdk.sha(H/'witness.py')==C['witness_sha256'],'original native fixture')
    result,_=raw(out/(label+'-native-witness'),[sys.executable,'-ISB',str(H/'witness.py'),phase,str(SRC),str(TARGET),str(SDK)],ENV|{'OHM_WITNESS_CARGO_JSONL':str(gz)})
    got=json.loads(result);expected={'edit':22635,'member':'seeds','virtual_root_reuses_cache':True,'member_reuses_cache':True,'cache_value_stores_project_name':phase=='B'}
    require(got==expected,'actual discovery and populated-cache fixture');return got
def prepare():
    sdk.configure();w=sdk.workspace();out=w/'results';out.mkdir(exist_ok=False)
    capacity(out/'capacity-before.json',C['minimum_initial_free_gib']<<30)
    require(not ROOT.exists()and ROOT.parent==Path('/tmp'),'fresh designated root required')
    media=w/'sdk-media';media.mkdir();sdk.ORIGINAL.released(media,out)
    installed=w/'installed';installed.mkdir();signed,=(media/'signed').glob('*.tar.gz')
    subject=sdk.one('signed',signed,sdk.P['signed']['assets'][signed.name]['digest'][7:],installed,out)
    ROOT.mkdir(mode=0o700);subject.rename(SDK)
    require(Path(subprocess.check_output([SDK/'bin/rustc','--print','sysroot'],text=True).strip()).resolve()==SDK,'relocated signed sysroot')
    print('authenticated signed release ready',flush=True)
def run():
    sdk.configure();w=sdk.workspace();out=w/'results'
    for p in (USER_HOME,CARGO_HOME):p.mkdir()
    subprocess.run(['git','clone','--no-checkout',(w/'uv-source').as_uri(),str(SRC)],env=ENV,check=True);source('checkout','-q','--detach',A)
    patch=history();verify_tree('A');(out/'A-B.patch').write_bytes(patch)
    raw(out/'fetch',[PLAIN[0],'fetch','--locked'],ENV|{'CARGO_NET_OFFLINE':'false'})
    write(out/'registry.json',registry());pristine=w/'fresh-inputs';pristine.mkdir();copy_many([SRC,CARGO_HOME,USER_HOME],pristine)
    outputs,_=raw(out/'metadata',[PLAIN[0],'metadata','--locked','--offline','--format-version','1']);meta=json.loads(outputs)
    require(meta['workspace_root']==str(SRC)and meta['target_directory']==str(TARGET),'canonical native paths')
    require(len(plain(out/'cold-A')['progress'])>400,'independent cold-A compile');a=unchanged('A',meta,out)
    keep_outputs(out/'parent-workspace.zip',a);seed=w/'seed';seed.mkdir()
    for p in (SRC,TARGET,CARGO_HOME,USER_HOME):p.rename(seed/p.name)
    def restore():
        remove_state();copy_many([seed/s for s in ('uv','target','cargo','home')],ROOT);verify_tree('A')
    restore();aw=witness('A','parent',out/'A-5-typed',out)
    restore();apply_edit(patch);first=plain(out/'first-edit-ordinary',a['provider']);require('uv-workspace'in first['progress'],'provider actually rebuilt')
    restore();apply_edit(patch);first_typed=typed(out/'first-edit-verbose',TYPED+['-vv'],meta);verify_tree('B')
    require(first_typed['progress']==first['progress']and first_typed['provider']==first['provider'],'first ordinary-vs-diagnostic from the same parent')
    b=unchanged('B',meta,out,a);require(b['provider']==first['provider'],'late provider outputs')
    keep_outputs(out/'edited-workspace.zip',b);bw=witness('B','edited',out/'B-5-typed',out);verify_tree('B')
    remove_state();copy_many([pristine/s for s in ('uv','cargo','home')],ROOT);apply_edit(patch)
    clean=typed(out/'cold-B',TYPED,meta);require(len(clean['dirty'])>400 and clean['roster_sha256']==b['roster_sha256']and clean['workspace']==b['workspace'],'independent B workload')
    keep_outputs(out/'cold-B-workspace.zip',clean);cw=witness('B','clean-child',out/'cold-B',out);verify_tree('B')
    observed={'scored':False,'A_witness':aw,'B_witness':bw,'cold_B_witness':cw,'first_ordinary_progress':first['progress'],'unchanged_progress':a['progress'],'dirty_first':first_typed['dirty'],'dirty_unchanged':a['dirty'],'provider_warm':b['provider'],'provider_cold':clean['provider']}
    write(out/'observation.json',observed);require(b['provider']==clean['provider']and cw==bw and aw!=bw,'independent B raw provider or native behavior')
    write(out/'opening.json',{'eligible_for_subsequent_design':True,'scored':False,'root_artifacts':len(json.loads((out/'cold-B/roster.json').read_bytes())),'workspace_targets':len(b['workspace']),'provider_equal':True})
if __name__=='__main__':
    require(__debug__,'assertions must be active')
    if sys.argv[1:]==['prepare']:prepare()
    elif sys.argv[1:]==['run']:run()
    else:raise SystemExit('prepare or run')
