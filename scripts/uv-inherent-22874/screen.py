"""Four paired screening draws over two independently built earlier revisions."""
import gzip,os,re,shutil,subprocess,sys
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import core as c,history as h,products as prod,cargo_log as logs
m=c.m;P=c.P
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
def typed(phase):
    so,se=primary.command(phase,[*c.CHECK,'-vv','--message-format=json'],'typed')
    events=logs.cargo_messages(so);commands=logs.running_rustcs(se,m.RUSTC)
    active=[x for x in events if x['reason']=='compiler-artifact'and not x['fresh']];names=Counter(v['target']['name'].replace('-','_')for v in active)
    actual=Counter(v[v.index('--crate-name')+1]for v in commands)
    c.guard(names==actual and actual['uv_pypi_types']==1,('true returned Cargo child/artifact roster',names,actual))
    details={'commands':commands,'artifact_crates':dict(names),'completed':events[-1],'diagnostics':[v for v in events if v['reason']=='compiler-message'],
             'material':h.state('B'),'unit_graph':h.graph()};m.save(phase/'roster.json',details);return details
def behavior(at,rev):
    at.mkdir();file=m.SRC/P['file'];c.guard(m.filesha(file)==P[rev+'_file'],'wrong behavior revision')
    target=m.ROOT/'behavior';args=[str(m.SDK/'bin/cargo'),'test','--locked','--offline','-j8','-p','uv-pypi-types','--lib',P['runtime_test'],'--','--exact']
    env=m.ENV|{'CARGO_TARGET_DIR':str(target),'CARGO_INCREMENTAL':'0','CARGO_PROFILE_DEV_DEBUG':'0','CARGO_PROFILE_TEST_DEBUG':'0','INSTA_UPDATE':'no'}
    with(at/'stdout').open('xb')as so,(at/'stderr').open('xb')as se:p=subprocess.run(args,cwd=m.SRC,env=env,stdout=so,stderr=se,timeout=1200)
    data=(at/'stdout').read_text();ok=p.returncode==0 and ('test '+P['runtime_test']+' ... ok')in data and '1 passed; 0 failed'in data
    m.save(at/'witness.json',{'argv':args,'exit':p.returncode,'exact':ok,'source':h.state(rev),'off_clock':True});c.guard(ok,'upstream exact behavior')
def acquire_context():
    w,tmp=c.host();out=w/'trait-results';vault=out/'rmeta-by-content';vault.mkdir();h.guard_space(w,tmp)
    old,meter=m.pmu(w,tmp);cal=m.read(out/'calibration.json');ready=cal['ready'];mask=set(ready['affinity'])
    c.guard(mask and mask<=os.sched_getaffinity(0),'enrolled calibration CPU set unavailable');os.sched_setaffinity(0,mask)
    current=old.cpu_receipt(out);c.guard(current['cpus']==ready['affinity']and current['boot']==ready['boot']and cal['unmultiplexed_calibration_clocks']==28,'counter qualification/host')
    binary=Path(ready['plain']);c.guard(m.filesha(binary)==cal['plain_sha256'],'calibrated inherited meter')
    load=m.read(out/'intake.json');sdk=load['installed'];gate=m.read(c.HERE/'provider-gate.json')['roles']
    c.guard(set(sdk)==set(c.ROLES)and load['sdk_lock_sha256']==P['sdk_lock_sha256'],'SDK roles')
    for r in c.ROLES:
        actual=sdk[r];c.guard(actual['server']['id']==gate[r]['artifact_id']and actual['server']['sha256']==gate[r]['archive']and gate[r]['driver']in actual['runtime'].values(),('same qualified binary',r))
    sourcegate=m.read(out/'intake/cache-transition/passed.json');wire=m.read(out/'intake/metadata-transition/passed.json')
    c.guard(sourcegate['native_processes']==wire['cache_native_processes']==16 and wire['one_byte_per_role'] is True and wire['native_processes']==len(wire['rows'])>0,'both native cache and metadata epoch directions')
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
    def products(path):return prod.aggregate(m.TARGET,path,store,parse,prod.identities)
    for hold in(0,1):
        histories={};baseline={}
        for role in (c.ROLES if hold==0 else reversed(c.ROLES)):
            m.choose(role,bank,sdks);h.guard_space(w,tmp,m.ROOT);h.clean(m.TARGET);h.write('A',atime);q=panel/f'hold-{hold}-{role}';q.mkdir()
            m.save(q/'A-unit-graph.json',h.graph())
            primary.command(q/'ordinary-A',c.CHECK,'cold-A');a=products(q/'ordinary-A');c.guard(h.state('A')['working_tree']==P['A_tree'],'cold A affected checkout')
            primary.command(q/'settled-A',c.CHECK,'settled-A');settled=products(q/'settled-A')
            c.guard(prod.compare(q/'settled-A-equivalence.json',a,settled,True),'unmodified A outputs changed')
            if hold==0:h.clean(m.ROOT/'behavior');behavior(q/'behavior-A','A')
            seed,seal=h.checkpoint(role,hold,bank);rr=a['relative_paths']['uv_pypi_types'];m.save(q/'checkpoint.json',seal)
            h.restore(seed,seal,rr,atime);primary.command(q/'warm-B',c.CHECK,'first-edit');b=products(q/'warm-B')
            movement=prod.movement(role,a['provider'],b['provider']);m.save(q/'movement.json',movement);m.save(q/'B-unit-graph.json',h.graph())
            h.clean(m.TARGET);h.state('B');primary.command(q/'cold-B',c.CHECK,'independent-cold-B');cold=products(q/'cold-B')
            c.guard(prod.compare(q/'independent-B-equivalence.json',b,cold,False),'warm/independent B semantic mismatch')
            if hold==0:behavior(q/'behavior-B','B');h.clean(m.ROOT/'behavior')
            h.restore(seed,seal,rr,atime);proof=typed(q/'typed-B');typed_products=products(q/'typed-B')
            c.guard(prod.compare(q/'typed-equivalence.json',b,typed_products,False),'diagnostic vs ordinary semantic mismatch')
            normal=progress((q/'warm-B/cargo.stderr').read_bytes());c.guard(any(x[1]=='uv-pypi-types'for x in normal),'ordinary provider edit did not rebuild')
            c.guard(normal==progress((q/'typed-B/cargo.stderr').read_bytes()),'typed and ordinary actual package roster differs')
            streams=output_controls(q/'warm-B');m.save(q/'ordinary-controls.json',streams)
            m.save(q/'actual-cargo-opening.json',{'ordinary_progress':normal,'typed_active':proof['artifact_crates'],'actual_typed_commands':len(proof['commands']),'native_selected':movement})
            histories[role]=(seed,seal,rr);baseline[role]=(b,streams)
        for i in [n for n,x in enumerate(P['independent_holds'])if x==hold]:
            values={}
            for role in P['orders'][i]:
                m.choose(role,bank,sdks);roleout=panel/f'pair-{i}-{role}';roleout.mkdir();values[role]={}
                seed,seal,rr=histories[role];expected,scheduled=baseline[role]
                for mode in P['mode_orders'][i]:
                    s=h.restore(seed,seal,rr,atime);path=roleout/mode
                    primary.command(path,c.CHECK,'pmu'if mode=='clock'else'native',binary if mode=='clock'else None)
                    rec=m.read(path/'ordinary.json');c.guard(rec['boot']==ready['boot']and rec['cpus']==ready['affinity']and rec['argv']==c.CHECK,'command/boot/cores')
                    result=products(path);m.save(path/'source.json',h.state('B'));c.guard(h.state('B')==s,'command changed source')
                    ok=prod.compare(path/'same-seed-equivalence.json',expected,result,True)
                    observed=output_controls(path);m.save(path/'ordinary-controls.json',observed);c.guard(observed==scheduled,'ordinary roster or output changed within role')
                    val=rec['ns']
                    if mode=='clock':
                        counter=meter.clock(path/'whole-clock.json',0);c.guard(counter['enabled']==counter['running']>0,'multiplexed PMU');val=counter['instructions']
                    values[role][mode]={'value':val,'same_seed_qualified':ok,'source_sha256':s['source'],'checkpoint_sha256':seal['sha256']}
            reports.append({'pair':i,'hold':hold,'order':P['orders'][i],'modes':P['mode_orders'][i],'values':values})
        h.clean(m.TARGET)
        for seed,_,_ in histories.values():h.clean(seed)
    for role in c.ROLES:
        m.choose(role,bank,sdks);primary.final_sdk(role,sdks,m.SDK,out)
    m.save(panel/'raw-pairs.json',reports)
if __name__=='__main__':run()
