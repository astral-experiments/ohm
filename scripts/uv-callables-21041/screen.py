"""Eight paired screening draws over two independently built earlier revisions."""
import gzip,os,re,shutil,subprocess,sys
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import core as c,history as h,products as prod,cargo_log as logs
m=c.m;P=c.P
import scoped,typed21041,behavior21041,physical
import run as primary
def parser(work,tmp):
    opening,_=m.check_sources(work)
    for name,sha in m.P['pinned_opening'].items():c.guard(m.filesha(opening/name)==sha,('admitted all-crate reader',name))
    sys.path.insert(0,str(opening));lib=m.load('admitted_opening',opening/'opening.py');kit=tmp/'uv22874-readers'
    lib.initialize(kit);return c.deep.parser(kit/'check-root-20261101/ctfe-root-attribution/metadata.py')
def progress(err):
    progress=[]
    for v in err.decode(errors='strict').splitlines():
        hit=re.match(r'^\s*(Checking|Compiling)\s+([A-Za-z0-9_-]+) v([^ ]+)',v)
        if hit:progress.append(list(hit.groups()))
    return sorted(progress)
def output_controls(path):
    stderr=(path/'cargo.stderr').read_bytes();rendered=[];finished=[]
    for line in stderr.decode(errors='strict').splitlines():
        if progress((line+'\n').encode()):continue
        hit=re.fullmatch(r'(\s*Finished .+ target\(s\)) in [0-9][0-9a-z .]*',line)
        if hit:finished.append(hit.group(1))
        else:rendered.append(line)
    c.guard(len(finished)==1,'ordinary cargo completion display')
    return {'stdout':m.filesha(path/'cargo.stdout'),'rendered_other_than_progress_and_wall':rendered,'finished':finished,'progress':progress(stderr)}
def acquire_context():
    w,tmp=c.host();out=w/'trait-results';vault=out/'rmeta-by-content';vault.mkdir();h.guard_space(w,tmp)
    import trio
    ready=trio.accept_host(out);binary=meter=None
    load=m.read(out/'intake.json');sdk=load['installed'];gate=c.PAIR['arms']
    c.guard(set(sdk)==set(c.ROLES)and load['sdk_lock_sha256']==P['sdk_lock_sha256'],'SDK roles')
    for r in c.ROLES:
        actual=sdk[r];c.guard(actual['server']==gate[r]['artifact']and gate[r]['driver']in actual['runtime'].values(),('same qualified binary',r))
    from epoch_transition import validate
    tr=m.read(out/'intake/natural-epoch-transition/passed.json');c.guard(tr['ordinary_only'] is True and tr['positive_native_calls']==8 and tr['negative_native_calls']==2,'native default epoch isolation')
    source={r:c.PAIR['arms'][r]['source']for r in c.ROLES}
    endpoints=[c.ROLES[0],c.ROLES[-1]]
    for name in ("coroutine-transition","foreign-transition"):c.guard(len(m.read(out/("intake/"+name+"/passed.json"))["modes"])==4,"mixed-SDK qualification")
    for a,b in (endpoints,list(reversed(endpoints))):validate(tr['histories'][a+'-to-'+b],[a,b],source)
    read=parser(w,tmp);bank=m.ROOT/'bank';a=h.open_source(w,bank);m.save(out/'real-A.json',a)
    pool=tmp/'ctfe22-root-sdks'
    for r in c.ROLES:shutil.move(str(pool/r),str(bank/('sdk-'+r)))
    m.choose(c.ROLES[0],bank,sdk)
    with(out/'fetch.stdout').open('xb')as so,(out/'fetch.stderr').open('xb')as se:
        subprocess.run([c.CHECK[0],'fetch','--locked'],cwd=m.SRC,env=m.ENV|{'CARGO_NET_OFFLINE':'false'},stdout=so,stderr=se,check=True,timeout=1200)
    m.save(out/'full-registry.json',h.verify_registry());c.guard(h.state('A')==a,'provision changed source')
    m.save(out/'full-unit-graph.json',h.graph());return w,tmp,out,vault,bank,sdk,a['source_mtime_ns'],read,ready,binary,meter
def run():
    w,tmp,out,store,bank,sdks,atime,parse,ready,binary,meter=acquire_context();panel=out/'uv-client';panel.mkdir();reports=[]
    import trio
    def products(path):return prod.aggregate(m.TARGET,path,store,parse)
    for hold in(0,1):
        histories={};baseline={}
        for role in (c.ROLES if hold==0 else reversed(c.ROLES)):
            h.clean(m.TARGET);h.write('A',atime);h.guard_space(w,tmp)
            q=panel/f'hold-{hold}-{role}';q.mkdir();m.choose(role,bank,sdks)
            m.save(q/'A-unit-graph.json',h.graph())
            primary.command(q/'ordinary-A',c.CHECK,'cold-A');a=products(q/'ordinary-A');c.guard(h.state('A')['working_tree']==P['A_tree'],'cold A affected source')
            primary.command(q/'settled-A',c.CHECK,'settled-A');settled=products(q/'settled-A')
            c.guard(not progress((q/'settled-A/cargo.stderr').read_bytes())and prod.compare(q/'settled-A-equivalence.json',a,settled,True),'ordinary A did not settle')
            proof_a=typed21041.run(q/'typed-fresh-A','A',False);typed_a=products(q/'typed-fresh-A')
            c.guard(prod.compare(q/'fresh-A-equivalence.json',a,typed_a,True),'fresh A audit changed products')
            if hold==0:h.clean(m.ROOT/'behavior');behavior21041.run(q/'behavior-A','A')
            seed,seal=h.checkpoint(role,hold,bank);rr=a['relative_paths']['uv_pypi_types@check'];m.save(q/'checkpoint.json',seal)
            h.restore(seed,seal,rr,atime);primary.command(q/'warm-B',c.CHECK,'first-edit');b=products(q/'warm-B');m.save(q/'B-unit-graph.json',h.graph())
            primary.command(q/'settled-B',c.CHECK,'settled-B');settled_b=products(q/'settled-B')
            c.guard(not progress((q/'settled-B/cargo.stderr').read_bytes())and prod.compare(q/'settled-B-equivalence.json',b,settled_b,True),'ordinary B did not settle')
            typed21041.run(q/'typed-fresh-B','B',False);typed_noop=products(q/'typed-fresh-B')
            c.guard(prod.compare(q/'fresh-B-equivalence.json',b,typed_noop,True),'fresh B audit changed products')
            if hold==0:behavior21041.run(q/'behavior-B','B')
            h.clean(m.TARGET);h.state('B');primary.command(q/'cold-B',c.CHECK,'independent-cold-B');cold=products(q/'cold-B')
            c.guard(prod.compare(q/'independent-B-equivalence.json',b,cold,False),'independent cold B program differs from warm B')
            if hold==0:
                h.clean(m.ROOT/'behavior');behavior21041.run(q/'behavior-cold-B','B')
                warm=m.read(q/'behavior-B/witness.json');fresh=m.read(q/'behavior-cold-B/witness.json')
                c.guard(warm['output_sha256']==fresh['output_sha256'] and warm['fixture_sha256']==fresh['fixture_sha256'] and warm['state']==fresh['state'],'independent native B behavior differs')
                h.clean(m.ROOT/'behavior')
            h.restore(seed,seal,rr,atime);proof=typed21041.run(q/'typed-B','B',True);typed_products=products(q/'typed-B')
            c.guard(prod.compare(q/'typed-equivalence.json',b,typed_products,True),'diagnostic vs plain first-edit output differs')
            normalize=lambda rows:sorted((act,pkg.replace('-','_'),version)for act,pkg,version in rows)
            normal=normalize(progress((q/'warm-B/cargo.stderr').read_bytes()))
            c.guard(normal==normalize(progress((q/'typed-B/cargo.stderr').read_bytes())) and sorted(n for act,n,version in normal)==P['edited_workspace_roster'],'eight plain/typed first-edit packages')
            streams=output_controls(q/'warm-B');m.save(q/'ordinary-controls.json',streams)
            m.save(q/'actual-cargo-opening.json',{'ordinary_progress':normal,'typed_active':proof['artifact_crates'],'actual_typed_commands':len(proof['commands'])})
            histories[role]=(seed,seal,rr);baseline[role]=(b,streams)
        trio.cross(panel,hold)
        trio.audit_treatment(panel,hold,histories,baseline,sdks,bank,atime,products,output_controls)
        for i in [n for n,v in enumerate(P['independent_holds']) if v==hold]:
            values={}
            for role in P['orders'][i]:
                m.choose(role,bank,sdks)
                seed,seal,rr=histories[role]
                expected,streams=baseline[role]
                roleout=panel/f'trio-{i}-{role}';roleout.mkdir()
                values[role]=trio.bare(roleout,seed,seal,rr,atime,expected,streams,products,output_controls,ready)
            reports.append({'trio':i,'hold':hold,'order':P['orders'][i],'values':values})
        h.clean(m.TARGET)
        for seed,_,_ in histories.values():h.clean(seed)
    for role in c.ROLES:
        m.choose(role,bank,sdks);primary.final_sdk(role,sdks,m.SDK,out)
    m.save(panel/'raw-trios.json',reports)
    import wall_clock
    wall_clock.calibrate(out/'clock-post',tmp/'trio-wall-probe')
if __name__=='__main__':run()
