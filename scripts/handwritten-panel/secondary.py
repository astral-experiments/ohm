"""Two preregistered package pairs after the independent workspace panel on the same calibrated host."""
import gzip,inspect,json,os,re,shutil,subprocess,sys
from pathlib import Path
from fractions import Fraction
sys.path.insert(0,str(Path(__file__).resolve().parent))
import material as m, run, score, scope, identity
from enroll import ROLES
PKG=[str(m.SDK/'bin/cargo'),'check','--locked','--offline','-j8','-p','uv','--lib']
ORDERS=[{'hold':1,'pair':1,'roles':list(ROLES),'modes':['native','pmu']},{'hold':1,'pair':2,'roles':list(reversed(ROLES)),'modes':['pmu','native']}]
def replace_function(f,changes):
    s=inspect.getsource(f);ctx=dict(f.__globals__)
    for old,new,n in changes:
        assert s.count(old)==n,(f.__name__,old,s.count(old));s=s.replace(old,new)
    exec(compile(s,str(f.__code__.co_filename),'exec'),ctx);return ctx[f.__name__]
def setup(o,api):
    api.s.inputs=replace_function(api.s.inputs,[('==641','==592',1),('==70','==64',1),("['clap','schemars']","['clap']",1)])
    api.p.capture_plain=replace_function(api.p.capture_plain,[('==641','==592',1),('==70','==64',1),("'workspace_files':70","'workspace_files':64",1),('70 registered','64 registered',1),('641-unit','592-unit',1)])
    run.inventory=replace_function(run.inventory,[('==70','==64',1)])
    run.compared=replace_function(run.compared,[('all_70_roots_and_deps_equal','all_64_roots_and_deps_equal',1)])
def compile_graph(here):
    here.mkdir();argv=[*PKG,'-Z','unstable-options','--unit-graph'];env=m.ENV|{'RUSTC_BOOTSTRAP':'1'}
    with (here/'stdout.json').open('xb')as so,(here/'stderr.txt').open('xb')as se:rc=subprocess.run(argv,cwd=m.SRC,env=env,stdout=so,stderr=se,timeout=300)
    m.save(here/'invoked.json',{'argv':argv,'env':env,'status':rc.returncode,'source_tree':m.history()[0]});assert rc.returncode==0
    graph=m.read(here/'stdout.json');plan=scope.package_scope(scope.structural(graph,m.SRC,m.CARGO_HOME/'registry/src'))
    assert plan['graph_sha256']==scope.EXPECTED and plan['modes']=={'check':451,'build':141,'run-custom-build':50}
    return graph,plan
def typed_observed(so,se,graph,o,api,kind):
    rows,owners=o.native.events(so);args=sorted(o.native.commands(se.decode(),m.RUSTC));art=[r for r in rows if r['reason']=='compiler-artifact'];scripts=[r for r in rows if r['reason']=='build-script-executed']
    assert [r['success']for r in rows if r['reason']=='build-finished']==[True] and not any(r['reason']=='compiler-message'for r in rows)
    shape=api.s.inputs(art);sort=lambda v:sorted(v,key=m.canon)
    detail={'all_artifact_rows':m.digest(m.canon(sort(art))),'all_build_script_rows':m.digest(m.canon(sort(scripts))),'dirty':sort([[r['package_id'],r['target']['name'],r['target']['kind'],r['features'],r['filenames']]for r in art if not r['fresh']]),'argv':args,'progress':sorted(n.decode()for n in re.findall(rb'^\s*(?:Checking|Compiling) ([\w-]+) v',se,re.M))}
    assert (len(art),len(scripts),len(shape[1]))==(592,50,64)
    actual=scope.native_opening(graph,m.SRC,m.CARGO_HOME/'registry/src',args,require_root=kind=='edit') if args else {'graph_sha256':scope.EXPECTED,'observations':[],'dirty_unit_ids':[]}
    assert actual['observations'] or (kind=='background' and not detail['dirty'])
    return shape,{'kind':kind,'details':detail,'actual':actual,'rows':len(art),'build_scripts':len(scripts),'workspace':len(shape[1]),'build_script_plaintext':owners}
def visit(path,graph,o,api,kind):
    so,se=run.command(path,[*PKG,'--timings','--message-format=json-render-diagnostics','-vv'],'unscored-typed')
    shape,rec=typed_observed(so,se,graph,o,api,kind);m.save(path/'observed.json',rec)
    for fn in ['cargo.stdout','cargo.stderr']:o.native.gzip_file(path/fn)
    return shape,rec
def discover(role,out,bank,delta,o,api):
    q=out/('opening-'+role);q.mkdir();m.reset(bank,'A',delta);ga,plan=compile_graph(q/'graph-A')
    run.command(q/'ordinary-A',PKG,'unscored-opening-A');shape,bg=visit(q/'A-background',ga,o,api,'background')
    seed=m.freeze();stamp=m.seed_state(seed,role);m.restore(seed,delta,role,stamp)
    run.command(q/'B-native',PKG,'unscored-opening-B');ra=run.inventory(q/'B-native',shape);run.rawproof.hold(q/'B-native',ra)
    m.restore(seed,delta,role,stamp);edited,er=visit(q/'B-typed',ga,o,api,'edit')
    assert shape==edited;run.rawproof.require(q/'B-native',q/'B-typed',ra,run.inventory(q/'B-typed',shape))
    gb,pb=compile_graph(q/'graph-B');assert plan==pb and ga==gb
    m.save(q/'actual.json',{'role':role,'graph':plan,'edit':er['actual'],'background':bg['actual'],'same_seed_products':m.digest(m.canon(ra))})
    m.erase(seed,m.SRC,m.TARGET,m.CARGO_HOME,m.HOME)
    return shape,bg,er,ga
def traced(opening,tmp,argv):
    import lifecycle
    d=tmp/'package-strace';d.mkdir();src=(opening/'trace.py').read_bytes()
    assert m.digest(src)==m.P['pinned_opening']['trace.py']
    (d/'trace.py').write_bytes(lifecycle.source(src,len(argv)))
    case=m.read(opening/'case.json');assert case['unscored_argv']==m.P['argv'];case['unscored_argv']=PKG;m.save(d/'case.json',case);m.save(d/'reference.json',{'argv':argv})
    return lifecycle.attach(m.load('secondary_scoped_exec',d/'trace.py'))
def stamped(path,mode,ready,meter,progress):
    receipt=m.read(path/'ordinary.json');assert receipt['mode']==mode and receipt['boot']==ready['boot'] and receipt['cpus']==ready['affinity'] and receipt['argv']==PKG and receipt['exit']==0
    assert receipt['env']==m.ENV and not (path/'cargo.stdout').read_bytes()
    visited=sorted(v.decode()for v in re.findall(rb'^\s*(?:Checking|Compiling) ([\w-]+) v',(path/'cargo.stderr').read_bytes(),re.M));assert visited==progress
    if mode=='pmu':
        assert receipt['invoked']==[ready['plain'],str(path/'whole-clock.json'),*PKG]
        v=meter.clock(path/'whole-clock.json',0);assert v['running']==v['enabled']>0 and v['instructions']==score.counter(path/'whole-clock.json');return v['instructions']
    assert mode=='native' and receipt['invoked']==PKG and not (path/'whole-clock.json').exists() and receipt['ns']==receipt['end_ns']-receipt['start_ns']>0;return receipt['ns']
def replay(log,graph,o,api,kind,expect,shape):
    so,se=(gzip.decompress((log/('cargo.'+k+'.gz')).read_bytes())for k in ('stdout','stderr'));s,v=typed_observed(so,se,graph,o,api,kind)
    assert v==m.read(log/'observed.json') and s==shape and v['details']==expect['details']
def main():
    w,tmp=m.host();out=w/'trait-results/secondary';out.mkdir();assert m.read(w/'trait-results/result.json')['classification'].startswith('optimized stage1 compiler screen')
    opening,_=m.check_sources(w);fresh=tmp/'handwritten-package-oracles';fresh.mkdir();o,api,parser,_=m.readers(opening,fresh);old,meter=m.pmu(w,tmp);setup(o,api);m.ARGS=PKG
    bank=m.ROOT/'bank';installed=m.read(w/'trait-results/intake.json')['installed'];cal=m.read(w/'trait-results/calibration.json');ready=cal['ready']
    rebound=old.cpu_receipt(out);assert rebound==m.read(w/'trait-results/host.json') and rebound['cpus']==ready['affinity'] and rebound['boot']==ready['boot']
    assert ready['boot']==Path('/proc/sys/kernel/random/boot_id').read_text().strip() and sorted(os.sched_getaffinity(0))==ready['affinity'] and cal['unmultiplexed_calibration_clocks']==28
    assert m.filesha(m.HERE/'package-plan.json')=='15e37ff8c7f8ae63ce95a12f4e9db219179cb0e3b633c75ec062baf9db55a4cf' and m.read(m.HERE/'package-plan.json')['command']==['cargo',*PKG[1:]]
    assert m.filesha(m.HERE/'scope.py')=='d9374e7c793da56fd2fa27f0fedf76a7cb40da82a1a2c9b3754ef3930ac03265'
    m.cp(bank/'uv',m.SRC);_,delta=m.history();m.erase(m.SRC)
    found={}
    for role in ROLES:
        m.choose(role,bank,installed);found[role]=discover(role,out,bank,delta,o,api)
    shape,bg,ed,graph=found[ROLES[0]];shape2,bg2,ed2,graph2=found[ROLES[1]];match=scope.compare_dirty(ed['actual'],ed2['actual']);m.save(out/'preclock-dirty.json',match)
    assert match['matched'] and shape==shape2 and graph==graph2 and bg['details']==bg2['details'] and ed['details']==ed2['details']
    m.shape=lambda:shape;ref={'background':bg,'edit':ed,'argv':ed['details']['argv']}
    def typed(p,kind,v,ob,reader):
        sh,rec=visit(p,graph,ob,reader,kind);assert sh==shape and rec['details']==ref[kind]['details'] and rec['actual']==ref[kind]['actual'];return sh
    run.typed=typed;tr=traced(opening,fresh,ref['argv']);tr.calibrate(out/'trace-calibration');tr.mutations(out/'trace-calibration')
    cold={}
    for role in ROLES:
        m.choose(role,bank,installed);q=out/('qualification-'+role);cold[role]=run.qualify(role,bank,delta,q,o,api,parser,ref)
        m.save(q/'virtual-project.json',identity.check(role,q,parser))
        replay(q/'preclock-edit',graph,o,api,'edit',ed,shape);replay(q/'settled-A',graph,o,api,'background',bg,shape)
        four=m.read(q/'four-state.json')['comparisons']
        for k,left,right in [('cold-B1','A-to-B','cold-B1'),('cold-B2','A-to-B','cold-B2'),('both-independent-cold','cold-B1','cold-B2')]:
            assert run.compared(q/left,q/right,shape,api,parser)==four[k]
        for v in ('A','B'):score.fixture(q/('fixture-'+v),v)
    rows=[];previous_stop=0
    for design in ORDERS:
        vals={}
        for role in design['roles']:
            m.choose(role,bank,installed);p=out/f"pair{design['pair']:02d}-{role}"
            run.trial(role,design,bank,delta,p,cold[role],o,api,parser,tr,cal,meter,ref)
            for mode in design['modes']:
                clock=m.read(p/mode/'ordinary.json');assert previous_stop<clock['start_ns']<clock['end_ns'];previous_stop=clock['end_ns']
            a=m.read(p/'accepted.json');assert a['genuine_children']==len(ref['argv']) and a['mode_order']==design['modes'];tr.replay(p/'scoped');replay(p/'typed',graph,o,api,'edit',ed,shape)
            expected=m.read(p/'native/workspace-products.json');assert len(expected)==64 and all(m.read(p/k/'workspace-products.json')==expected for k in ['pmu','typed','scoped'])
            assert run.compared(p/'native',cold[role],shape,api,parser)==a['independent_cold']
            vals[role]={'user_instructions':stamped(p/'pmu','pmu',ready,meter,ed['details']['progress']),'wall_nanoseconds':stamped(p/'native','native',ready,meter,ed['details']['progress'])}
        rows.append({'design':design,'values':vals})
    for role in ROLES:
        m.choose(role,bank,installed);assert run.final_sdk(role,installed,m.SDK,w/'trait-results')==m.read(w/'trait-results/final-sdk.json')[role]
    metrics={}
    for name in ['user_instructions','wall_nanoseconds']:
        ratios=[Fraction(row['values'][ROLES[0]][name],row['values'][ROLES[1]][name])for row in rows]
        metrics[name]={'pairs':[score.num(v)for v in ratios],'median':score.num(score.median(ratios)),'wins_over_parity':sum(v>1 for v in ratios),'wins_over_double':sum(v>2 for v in ratios)}
    m.save(out/'screen.json',{'stages':'optimized stage1','scope':PKG,'features':scope.package_scope(scope.structural(graph,m.SRC,m.CARGO_HOME/'registry/src')),'observed_dirty':ed['actual'],'paired':rows,'metrics':metrics,'n_pairs':2,'screen_only':True,'boot':ready['boot']})
if __name__=='__main__':main()
