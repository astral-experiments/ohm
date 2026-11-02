"""Collect plain and separately marked real #20988 root products across native and fresh histories."""
from pathlib import Path
from zipfile import ZipFile
import gzip, json, os, re, shutil, subprocess, sys, traceback
sys.path.insert(0,str(Path(__file__).resolve().parent))
import common as c
import cold
m=c.m
sys.path.insert(0,str(c.PANEL))
import compiler_observer as kernel
panel=m.load('frozen_root_panel',c.PANEL/'run.py')
ROLE='fa7a_stack_ctfe318_handwritten_rdr_observer'
EPOCH_ROLE='fa7a_stack_ctfe318_handwritten'

def attempt(out,name,fun):
    try:
        value=fun()
        m.save(out/(name+'.json'),{'pass':True,'evidence':value})
        return True
    except Exception:
        m.save(out/(name+'.json'),{'pass':False,'traceback':traceback.format_exc()})
        return False

def gzip_file(src,dest):
    m.guard(not dest.exists(),'existing compressed evidence')
    with src.open('rb')as a,dest.open('xb')as b,gzip.GzipFile(filename='',fileobj=b,mode='wb',compresslevel=4,mtime=0)as z:shutil.copyfileobj(a,z,1<<20)
    return {'name':dest.name,'bytes':src.stat().st_size,'sha256':m.filesha(src),'gzip_bytes':dest.stat().st_size,'gzip_sha256':m.filesha(dest)}

def lifetime(path,state,shape,refs):
    folder=path/'lifetime';folder.mkdir()
    crate,=[m.TARGET/k for k,v in shape[1].items()if v['name']=='uv_workspace']
    source=m.SRC/'crates/uv-workspace/src/workspace.rs';s=source.read_bytes()
    tag=b'pub fn install_path(&self) -> &PathBuf';m.guard(s.count(tag)==1,'getter source');offset=s.index(tag)+tag.index(b'&');line=s.count(b'\n',0,offset)+1
    m.guard(line=={'A':889,'B':890}[state],'wrong genuine getter line')
    name=folder/'client.rs';argv=refs['uv']
    search=[v for ix,v in enumerate(argv[:-1])if v=='-L']
    dirs=[q for ix,v in enumerate(argv[:-1])if v=='-L'for q in ('-L',argv[ix+1])]
    m.guard(len(search)>100,'actual root -L namespace')
    common=[str(m.RUSTC),'--crate-name','rdr_lifetime_consumer','--crate-type','lib','--edition=2024','--emit=metadata','--error-format=json','--out-dir',str(folder),'--extern','uv_workspace='+str(crate),*dirs,str(name)]
    reports={}
    for label,code in [('inferred','pub fn use_getter(w: &uv_workspace::Workspace) -> &std::path::PathBuf { w.install_path() }'),('explicit',"pub fn use_getter() { let _ = uv_workspace::Workspace::install_path::<'static>; }")]:
        name.write_text(code+'\n');(folder/(label+'.rs')).write_bytes(name.read_bytes());x=subprocess.run(common,cwd=m.SRC,env=m.ENV,capture_output=True,timeout=120)
        (folder/(label+'.stdout')).write_bytes(x.stdout);(folder/(label+'.stderr')).write_bytes(x.stderr)
        ds=[json.loads(v)for v in x.stderr.splitlines()];m.guard(not x.stdout,'rustc stdout')
        if label=='inferred':m.guard(x.returncode==0 and not ds,'ordinary getter failed')
        else:
            errs=[d for d in ds if d.get('code',{}) and d['code'].get('code')=='E0794'];m.guard(x.returncode==1 and len(errs)==1,'wrong explicit lifetime diagnostic')
            spans=[a for d in errs for child in d['children'] for a in child['spans']if a['file_name'].endswith('crates/uv-workspace/src/workspace.rs')]
            m.guard(any(i['byte_start']==offset and i['line_start']==line and i['byte_end']>=offset+1 for i in spans),'late-bound source note did not identify the moved ampersand')
            reports['definition_spans']=spans
        reports[label]=x.returncode
    m.save(folder/'argv.json',common);return {'source_sha256':m.filesha(source),'upstream_rmeta':m.filesha(crate),'line':line,'offset':offset,'reports':reports}

def collect_graphs(path,reference):
    processes=[m.read(f)for f in sorted((path/'processes').glob('*.json'))]
    complete=sorted(v['argv']for v in processes);marks=[v for v in processes if v['marked']]
    m.guard(len(marks)==2 and set(v['name']for v in marks)==set(c.P['targets']) and len(set(v['pid']for v in processes))==len(processes),'compiler process scope')
    result={}
    for v in marks:
        n=v['name'];folder=path/'traces'/n;raw=sorted(folder.iterdir());m.guard(all(re.fullmatch(str(v['pid'])+r'-[0-9]+\.rdr',f.name) for f in raw),'foreign trace output')
        roster=[]
        for f in raw:
            proof=gzip_file(f,f.with_suffix('.rdr.gz'));roster.append(proof);f.unlink()
        result[n]={'pid':v['pid'],'argv_sha256':m.digest(m.canon(v['argv'])),'trace':roster}
    with (path/'all-compiler-processes.json.gz').open('xb')as f,gzip.GzipFile(filename='',mode='wb',fileobj=f,mtime=0)as zz:zz.write(m.canon(processes))
    shutil.rmtree(path/'processes')
    return {'compilers':len(complete),'full_18_same':complete==sorted(reference),'selected':result,'each_has_one_graph':all(len(v['trace'])==1 for v in result.values())}

def main():
    ws,tmp,out=c.only_scope();sdk_tmp=tmp/'enrolled-rdr-sdk';receipt=m.read(out/'intake.json');m.guard(receipt['source']==c.P['source'] and receipt['effective_inventory_sha256']==c.inventory(sdk_tmp),'unauthenticated SDK')
    m.guard(m.P['roles'][EPOCH_ROLE]['epoch']==c.P['source']['epoch']==43311,'epoch guard')
    full,refs=c.references();m.save(out/'registered-selected-argv.json',refs);shape=m.shape()
    opening=c.REPO/'scripts/uv-root-20991-opening';o,api,parser,_=m.readers(opening,tmp)
    bank,delta=m.initial(ws,tmp,out);shutil.move(str(sdk_tmp),str(m.SDK));c.runtime_receipt(m.SDK,m.read(out/'intake/identity.json'));m.provision(o,bank,out)
    recorded={};status={}
    def visit(label,state,marked=False):
        src,_=m.history();m.guard(src==m.CASE[state+'_tree'],'source tree before '+label)
        path=out/label;path.mkdir();c.capacity(path,'begin',c.P['capacity_after_gib'])
        env=dict(m.ENV)
        if marked:
            (path/'processes').mkdir();(path/'traces').mkdir()
            for n in c.P['targets']:(path/'traces'/n).mkdir()
            m.save(path/'selected-argv.json',refs)
            env.update(RUSTC_WRAPPER=str(c.HERE/'tap.py'),OHM_RDR_CAPTURE_PHASE=str(path))
        m.save(path/'invocation.json',{'argv':m.ARGS,'cwd':str(m.SRC),'env':env,'source':src,'signed_Cargo':m.filesha(m.SDK/'bin/cargo'),'compiler':c.P['source'],'mode':'marked'if marked else'unwrapped','score':False})
        with (path/'cargo.stdout').open('xb')as so,(path/'cargo.stderr').open('xb')as se:
            x=subprocess.run(m.ARGS,cwd=m.SRC,env=env,stdout=so,stderr=se,timeout=1800)
        m.save(path/'ordinary.json',dict(m.read(path/'invocation.json'),exit=x.returncode));m.save(path/'exit.json',{'exit':x.returncode});m.guard(x.returncode==0 and m.history()==(src,delta),'actual Cargo compilation or source failed')
        # Write the full unchanged native bytes first. Independent interpretation follows separately.
        shape_names=shape[1];rawmap=panel.inventory(path,shape)
        (path/'workspace-products.json').rename(path/'raw-inventory.json')
        with ZipFile(path/'selected.zip','x',compression=8,compresslevel=2)as z:
            for rel,info in shape_names.items():
                if info['name'] in c.P['targets']:z.write(m.TARGET/rel,rel)
        if marked:status[label+'/graphs']=attempt(path,'graph-proof',lambda:collect_graphs(path,full))
        status[label+'/products']=attempt(path,'all-products',lambda:panel.capture(path,shape,o,api)['surfaces'])
        status[label+'/lifetime']=attempt(path,'getter-proof',lambda:lifetime(path,state,shape,refs))
        recorded[label]=rawmap
        return path
    m.reset(bank,'A',delta);a=visit('ordinary-A','A')
    status['real-fixture-A']=attempt(out,'official-A',lambda:panel.witness(out/'fixture-A','A',o))
    seed=m.freeze();stamp=m.seed_state(seed,EPOCH_ROLE);m.save(out/'native-A-seed.json',stamp)
    m.restore(seed,delta,EPOCH_ROLE,stamp);b=visit('ordinary-warm-B','B')
    status['real-fixture-B']=attempt(out,'official-B',lambda:panel.witness(out/'fixture-B','B',o))
    m.restore(seed,delta,EPOCH_ROLE,stamp);visit('marked-from-native-A-B','B',True)
    m.restore(seed,delta,EPOCH_ROLE,stamp)
    def native_processes():
        path=out/'native-kernel-B';ident=m.read(out/'intake/identity.json')
        runtime={'bin/rustc':ident['rustc_sha256'],'bin/cargo':c.P['signed_cargo_sha256'],'lib/'+ident['driver']:ident['driver_sha256']}
        kernel.capture(path,m.ARGS,m.ENV,m.SRC,m.RUSTC,ROLE,runtime);tree,launch=kernel.kernel_result(path);selected=[]
        for im in tree['images']:
            av=im.get('argv',[])
            if im['file']==launch['compiler_file'] or Path(im['exe']).name=='rustc' or av and Path(av[0]).name=='rustc':
                m.guard(av and av[0]==im['exe']==str(m.RUSTC) and im['file']==launch['compiler_file'] and tree['exits'].get(im['pid'])==0,'native exec identity/exit')
                selected.append({'pid':im['pid'],'argv':av})
        m.guard(sorted(v['argv']for v in selected)==sorted(full),'actual 18 native root argv')
        recorded['native-kernel-B']=panel.inventory(path,shape);return {'compiler_processes':selected,'all_18':True}
    status['native-kernel']=attempt(out,'native-kernel-proof',native_processes);m.erase(seed)
    m.reset(bank,'A',delta);visit('marked-A','A',True);m.edit(delta);visit('marked-own-warm-B','B',True)
    m.reset(bank,'B',delta);cold=visit('ordinary-cold-B','B')
    m.reset(bank,'B',delta);visit('marked-cold-B','B',True)
    # Complete all marked histories first, then authenticate their original cold Cargo argv.
    for state,label in (('A','marked-A'),('B','marked-cold-B')):
        m.reset(bank,state,delta)
        status['cold-native-kernel-'+state]=attempt(out,'cold-native-kernel-'+state,
            lambda state=state,label=label:cold.prove(out,state,label,shape,panel,ROLE))
    eqs={}
    def compare(x,y):
        lo,hi=recorded[x],recorded[y];m.guard(lo.keys()==hi.keys()==shape[1].keys(),'physical product roster')
        raw=[k for k in sorted(lo)if lo[k]!=hi[k]]
        name=x+'-vs-'+y
        semantic=attempt(out,name+'-semantic',lambda:panel.compared(out/x,out/y,shape,api,parser))
        eqs[name]={'all_70_raw_identical':not raw,'raw_differences':raw,'independent_deep_equal':semantic}
    for x,y in [('ordinary-A','marked-A'),('ordinary-warm-B','marked-from-native-A-B'),('ordinary-warm-B','ordinary-cold-B'),('ordinary-warm-B','marked-own-warm-B'),('ordinary-cold-B','marked-cold-B')]:
        compare(x,y)
    if 'native-kernel-B'in recorded:
        eqs['native-kernel-all-70-raw']=(recorded['native-kernel-B']==recorded['ordinary-warm-B'])
    checks={l:m.read(out/l/'graph-proof.json') for l in recorded if l.startswith('marked')}
    m.save(out/'completed.json',{'score':False,'source':c.P['source'],'results':status,'comparisons':eqs,'observed_graphs':checks,'final_sdk':c.inventory(m.SDK),'registered_ordinary_argv':m.ARGS,'cpu':sorted(os.sched_getaffinity(0))})
    m.erase(m.TARGET,m.SRC,m.CARGO_HOME,m.HOME,m.SDK)
    m.guard(all(status.values()) and all(g['evidence']['each_has_one_graph']for g in checks.values()) and
            all(checks[l]['evidence']['full_18_same']for l in ('marked-from-native-A-B','marked-own-warm-B')) and
            eqs['ordinary-warm-B-vs-ordinary-cold-B']['independent_deep_equal'],'diagnostic capture incomplete; all available native evidence retained')
if __name__=='__main__':
    try:main()
    except Exception:
        out=Path(os.environ['GITHUB_WORKSPACE'])/'trait-results';(out/'refusal.txt').write_text(traceback.format_exc());raise
