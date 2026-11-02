"""Compare ordinary and separate diagnostic visits on one enrolled compiler. No clocks are scored."""
from pathlib import Path
from collections import Counter
import contextlib, gzip, json, os, re, shutil, signal, subprocess, sys, time
sys.path.insert(0,str(Path(__file__).resolve().parent))
import intake as i, observe, solve
import screen as s, products as products
m=i.m;c=i.c;h=i.h;P=i.P;HERE=i.HERE
def safe_cmd(argv,env,cwd,out):
    before={};low={};where=(out,m.ROOT)
    for p in where:before[str(p)]=low[str(p)]=shutil.disk_usage(p).free
    h.guard_space(*where)
    with(out/'cargo.stdout').open('xb')as a,(out/'cargo.stderr').open('xb')as b:
        pr=subprocess.Popen(argv,cwd=cwd,env=env,stdout=a,stderr=b,start_new_session=True);limit=time.monotonic()+1800;bad=None
        try:
            while pr.poll() is None:
                for p in where:low[str(p)]=min(low[str(p)],shutil.disk_usage(p).free)
                if min(low.values())<80<<30:bad='80 GiB reserve crossed';break
                if time.monotonic()>limit:bad='command timeout';break
                time.sleep(.25)
        finally:
            if pr.poll() is None:
                os.killpg(pr.pid,signal.SIGTERM)
                try:pr.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(pr.pid,signal.SIGKILL);pr.wait(timeout=10)
    m.save(out/'command.json',{'argv':argv,'cwd':str(cwd),'exit':pr.returncode,'observer_env_keys':[x for x in env if x in ('RUSTC_WRAPPER','OHM_22874_CLIENT_TRACE',observe.FLAG)],'failure':bad,'before_free_bytes':before,'minimum_free_bytes':low})
    assert pr.returncode==0 and bad is None
def selected_form(a):
    return {'crate':a[a.index('--crate-name')+1], 'cfg':sorted(a[j+1]for j,x in enumerate(a)if x=='--cfg'),
            'source':[x for x in a if x.startswith('crates/')and x.endswith('.rs')],
            'crate_type':a[a.index('--crate-type')+1], 'edition':[x for x in a if x.startswith('--edition=')],
            'emit':[x for x in a if x.startswith('--emit=')], 'test':'--test' in a, 'target':[a[j+1]for j,x in enumerate(a)if x=='--target']}
def direct_witness(phase,rev,row,prod):
    a=row['argv'];args=[part for j,x in enumerate(a) if x=='-L' for part in ('-L',a[j+1])]
    rel=prod['relative_paths']['uv_pypi_types'];lib=m.TARGET/rel
    assert m.filesha(lib)==prod['raw']['uv_pypi_types'][1]
    byte,line=((10707,375)if rev=='A'else(9994,344));text=(m.SRC/c.P['file']).read_bytes();assert text[byte:byte+5]==b'&self' and text.count(b'\n',0,byte)+1==line
    root=phase/'downstream';root.mkdir();out=[]
    for name,lifetime,code in [('inferred','',0),('explicit',"::<'static>",1)]:
        rs=root/(name+'.rs');rs.write_text('use uv_pypi_types::Yanked;\npub fn witness() -> fn(&Yanked) -> bool { Yanked::is_yanked'+lifetime+' }\n')
        argv=[str(m.RUSTC),'--edition=2024','--crate-name','yank_witness','--crate-type','lib','--emit=metadata','--error-format=json','-o',str(root/(name+'.rmeta')),'--extern','uv_pypi_types='+str(lib),*args,str(rs)]
        p=subprocess.run(argv,cwd=m.SRC,env=m.ENV,capture_output=True,timeout=120);(root/(name+'.stderr')).write_bytes(p.stderr);(root/(name+'.stdout')).write_bytes(p.stdout)
        vals=[json.loads(q)for q in p.stderr.splitlines() if q.startswith(b'{')];errs=[q for q in vals if q.get('code')]
        notes=[v for q in errs for n in q['children']if n['message']=='the late bound lifetime parameter is introduced here' for v in n['spans']]
        m.save(root/(name+'.json'),{'argv':argv,'exit':p.returncode,'diagnostics':[(z['code']['code'])for z in errs],'note':notes,'rmeta_relative':rel,'rmeta_sha256':m.filesha(lib)})
        assert p.returncode==code and (not errs and not notes if not code else len(errs)==len(notes)==1 and errs[0]['code']['code']=='E0794' and (notes[0]['file_name'],notes[0]['byte_start'],notes[0]['byte_end'],notes[0]['line_start'],notes[0]['column_start'])==(c.P['file'],byte,byte+1,line,22))
def decode_visits(target_rows,reader,store,out):
    entries={};failures=[]
    for label,(folder,product,rev)in target_rows.items():
        trace=folder/'observed';records=[m.read(x)for x in trace.glob('*.json')];traces={q['crate']:q for q in records if q['marked']}
        if len([q for q in records if q['marked']])!=len(traces) or set(traces)!=observe.NAMES:failures.append([label,'actual selected rustc roster',sorted(traces)])
        if rev=='B'and label=='marked-warm-B':
            compiled=Counter(q['crate']for q in records if any(x.startswith('--emit=')for x in q['argv']))
            if compiled!=Counter({n:1 for n in observe.NAMES}):failures.append([label,'all actual first B Cargo rustcs',dict(compiled)])
        for name,rec in sorted(traces.items()):
            meta_path=product['relative_paths'][name];meta_sha=product['raw'][name][1];bucket=trace/name
            rows={'pid':rec['pid'],'meta_relative':meta_path,'meta_sha256':meta_sha,'argv':rec['argv'],'source_units':selected_form(rec['argv']),'graphs':[]}
            entries[label+'/'+name]=rows
            try:
                assert rec['cwd']==str(m.SRC) and rec['argv'][0]==str(m.RUSTC) and rows['source_units']==P['workspace_forms'][name]
                assert Path(rec['argv'][rec['argv'].index('--out-dir')+1])==m.TARGET/Path(meta_path).parent
                suffix,=[a.split('=',1)[1]for a in rec['argv']if a.startswith('extra-filename=')];assert Path(meta_path).name=='lib'+name+suffix+'.rmeta'
                files=sorted(bucket.glob('*.rdr'));assert len(files)==1 and re.fullmatch(str(rec['pid'])+r'-\d+\.rdr',files[0].name),('missing, repeated or foreign genuine graph on actual rustc',rec['pid'],[z.name for z in files])
                graph=files[0];g=solve.read_graph(graph);p=solve.product(store/(meta_sha+'.gz'),reader,name);owners=solve.join(g,p);assert p['sha256']==meta_sha
                # This is an original-graph readback only. Projected/counterfactual costs are analyzed offline.
                native,values=solve.run(g,'native')
                assert len(values)==len(g.nodes) and all(v.value==z for v,z in zip(g.nodes,values,strict=True))
                rows['graphs'].append({'relative':str(graph.relative_to(out)), 'bytes':graph.stat().st_size,'sha256':m.filesha(graph),'nodes':len(g.nodes),'sccs':g.nscc,'native_recomputed':native,'owners':len(owners),'root_list_hash':format(g.roots_hash,'032x'),'metadata':p['head']})
            except (AssertionError,ValueError,KeyError,OSError)as e:failures.append([label,name,str(e),repr(e)])
    m.save(out/'graph-index.json',{'entries':entries,'failures':failures,'scope':'actual compiler PID, argv, graph, and complete original metadata; no projected hash is treated as observed'});return failures
def main():
    work,tmp=i.scope();out=work/'trait-results';h.guard_space(out,tmp);panel=out/'uv-client-rdr';panel.mkdir();store=out/'rmeta-by-content';store.mkdir()
    admitted=m.read(out/'intake/admitted.json');sdk=tmp/'rdr-22874-admitted-sdk'
    assert admitted['sdk']==str(sdk) and i.inventory(sdk)==admitted['sdk_inventory']
    parser=s.parser(work,tmp);reader=tmp/'uv22874-readers/uv-workflow-search/rdr_snapshot.py';assert m.filesha(reader)==P['rdr_reader_sha256']
    bank=m.ROOT/'bank';start=h.open_source(work,bank);m.save(panel/'real-A.json',start);mtime=start['source_mtime_ns']
    shutil.move(str(sdk),str(m.SDK));assert i.inventory(m.SDK)==admitted['sdk_inventory']
    h.guard_space(work,tmp,m.ROOT)
    with(panel/'fetch.stdout').open('xb')as so,(panel/'fetch.stderr').open('xb')as se:subprocess.run([c.CHECK[0],'fetch','--locked'],cwd=m.SRC,env=m.ENV|{'CARGO_NET_OFFLINE':'false'},stdout=so,stderr=se,check=True,timeout=1200)
    m.save(panel/'registry.json',h.verify_registry());m.save(panel/'plan-A.json',h.graph());assert h.state('A')==start
    native={};marked={};fail=[]
    def visit(label,rev,watch):
        d=panel/label;d.mkdir();state=h.state(rev);m.save(d/'source.json',state);env=m.ENV.copy()
        if watch:
            trace=d/'observed';trace.mkdir();env['RUSTC_WRAPPER']=str(HERE/'observe.py');env['OHM_22874_CLIENT_TRACE']=str(trace)
        safe_cmd(c.CHECK,env,m.SRC,d);q=products.aggregate(m.TARGET,d,store,parser,products.identities)
        assert state==h.state(rev)
        if watch:
            marked[label]=(d,q,rev);observed=[m.read(p)for p in (d/'observed').glob('*.json')]
            target=[z for z in observed if z['marked']and z['crate']=='uv_pypi_types']
            if len(target)==1:direct_witness(d,rev,target[0],q)
            else:fail.append([label,'missing actual provider argv for source-derived E0794 witness'])
        else:native[label]=(d,q,rev)
        return q
    def cmp(label,left,right,same_seed):
        if not products.compare(panel/(label+'.json'),left,right,same_seed):fail.append([label,'product comparison failed'])
    a=visit('native-A','A',False);a0=visit('native-settled-A','A',False);cmp('same-unmodified-A',a,a0,True)
    s.behavior(panel/'behavior-A','A');h.clean(m.ROOT/'behavior')
    seed,seal=h.checkpoint('fd02',0,bank);rel=a['relative_paths']['uv_pypi_types'];m.save(panel/'checkpoint.json',seal)
    h.restore(seed,seal,rel,mtime);b=visit('native-warm-B','B',False);m.save(panel/'plan-B.json',h.graph());m.save(panel/'five-receivers.json',products.movement(c.ROLES[1],a['provider'],b['provider']))
    h.clean(m.TARGET);fresh=visit('native-cold-B','B',False);cmp('native-independent-B',b,fresh,False)
    s.behavior(panel/'behavior-B','B');h.clean(m.ROOT/'behavior')
    h.clean(m.TARGET);h.write('A',mtime);ma=visit('marked-A','A',True);cmp('ordinary-vs-marked-independent-A',a,ma,False)
    h.restore(seed,seal,rel,mtime);mb=visit('marked-warm-B','B',True);cmp('ordinary-vs-marked-same-checkpoint-B',b,mb,True)
    h.clean(m.TARGET);mc=visit('marked-cold-B','B',True);cmp('ordinary-vs-marked-independent-cold-B',fresh,mc,False);cmp('marked-independent-B',mb,mc,False)
    for (x,y)in [('native-A','marked-A'),('native-warm-B','marked-warm-B'),('native-cold-B','marked-cold-B')]:
        n=s.output_controls(native[x][0]);o=s.output_controls(marked[y][0]);m.save(panel/(x+'-vs-'+y+'-ordinary-output.json'),{'native':n,'marked':o,'equal':n==o})
        if n!=o:fail.append([x,y,'ordinary Cargo stdout, rendered diagnostics or progress differ'])
        if x=='native-warm-B'and n['progress']!=P['first_edit_progress']:fail.append([x,'real first-edit unit progress differs'])
    fail.extend(decode_visits(marked,reader,store,out))
    h.guard_space(work,tmp,m.ROOT);assert i.inventory(m.SDK)==admitted['sdk_inventory']
    m.save(out/'complete.json',{'source':P['rustc'],'all_27_graphs_and_full_38_rmeta_gates_pass':not fail,'failures':fail,'command':c.CHECK,'selected':sorted(observe.NAMES),'no_performance_score':True})
    if fail:raise RuntimeError(fail)
if __name__=='__main__':main()
