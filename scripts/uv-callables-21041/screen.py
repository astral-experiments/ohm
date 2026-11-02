"""Measure eight pairs on sixteen independent previous-revision compiler histories."""
import gzip,os,re,shutil,subprocess,sys
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import domain_control,wall_clock
from origin.checkpoints import enroll as enroll_seed
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
    old,meter=m.pmu(w,tmp);cal=m.read(out/'calibration.json');ready=cal['ready'];mask=set(ready['affinity'])
    c.guard(mask and mask<=os.sched_getaffinity(0),'enrolled calibration CPU set unavailable');os.sched_setaffinity(0,mask)
    current=old.cpu_receipt(out);c.guard(current['cpus']==ready['affinity']and current['boot']==ready['boot']and cal['unmultiplexed_calibration_clocks']==28,'counter qualification/host')
    binary=Path(ready['plain']);c.guard(m.filesha(binary)==cal['plain_sha256'],'calibrated inherited meter')
    load=m.read(out/'intake.json');sdk=load['installed'];gate=c.PAIR['arms']
    c.guard(set(sdk)==set(c.ROLES)and load['sdk_lock_sha256']==P['sdk_lock_sha256'],'SDK roles')
    for r in c.ROLES:
        actual=sdk[r];c.guard(actual['server']==gate[r]['artifact']and gate[r]['driver']in actual['runtime'].values(),('same qualified binary',r))
    import domain_control
    accepted=m.read(out/'intake/domain-native/accepted.json')
    c.guard(set(accepted['roles'])==set(c.ROLES)and accepted['modes']==10 and accepted['canonical_inputs']==P['sdk_lock_sha256'],'missing source, method transition or real cache retirement')
    c.guard(m.read(out/'fresh-boot.json')['boot']==ready['boot'],'calibration boot changed')
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
    sc=out/'per-rustc-calibration';boot=m.read(out/'fresh-boot.json')
    c.guard(boot['thread_calibration']==m.filesha(sc/'calibration.json')and m.read(sc/'source.json')['host']==scoped.machine()and scoped.cal_raw(sc),'per-rustc calibration changed')
    c.guard(boot['blocking_clock']==m.filesha(out/'blocking-clock/passed.json'),'different calibrated blocking clock')
    per_meter_ready=True
    from derive import panel as derive_panel
    derive_panel.wire.bind(parse)
    def products(path):
        value=prod.aggregate(m.TARGET,path,store,parse)
        derive_panel.capture(m.TARGET,m.SDK,m.SRC,path,value,role,out,tmp)
        return value
    opened_seeds = set()
    for i,hold in enumerate(P['independent_holds']):
        histories={};baseline={}
        for role in P['orders'][i]:
            h.clean(m.TARGET);h.write('A',atime);h.guard_space(w,tmp)
            q=panel/f'opening-{i}-{role}';q.mkdir();m.choose(role,bank,sdks)
            m.save(q/'A-unit-graph.json',h.graph())
            primary.command(q/'ordinary-A',c.CHECK,'cold-A');a=products(q/'ordinary-A');c.guard(h.state('A')['working_tree']==P['A_tree'],'cold A affected source')
            primary.command(q/'settled-A',c.CHECK,'settled-A');settled=products(q/'settled-A')
            c.guard(not progress((q/'settled-A/cargo.stderr').read_bytes())and prod.compare(q/'settled-A-equivalence.json',a,settled,True),'ordinary A did not settle')
            proof_a=typed21041.run(q/'typed-fresh-A','A',False);typed_a=products(q/'typed-fresh-A')
            c.guard(prod.compare(q/'fresh-A-equivalence.json',a,typed_a,True),'fresh A audit changed products')
            domain_control.zero(q/'unchanged-kernel-A','A')
            c.guard(prod.compare(q/'unchanged-kernel-A-equivalence.json',a,products(q/'unchanged-kernel-A'),True),'unchanged command changed products')
            if i in (0,4):h.clean(m.ROOT/'behavior');behavior21041.run(q/'behavior-A','A')
            seed,seal=h.checkpoint(role,i,bank);rr=a['relative_paths']['uv_pypi_types@check'];m.save(q/'checkpoint.json',seal)
            enroll_seed(opened_seeds,seal,i,role)
            h.restore(seed,seal,rr,atime);primary.command(q/'warm-B',c.CHECK,'first-edit');b=products(q/'warm-B');m.save(q/'B-unit-graph.json',h.graph())
            primary.command(q/'settled-B',c.CHECK,'settled-B');settled_b=products(q/'settled-B')
            c.guard(not progress((q/'settled-B/cargo.stderr').read_bytes())and prod.compare(q/'settled-B-equivalence.json',b,settled_b,True),'ordinary B did not settle')
            typed21041.run(q/'typed-fresh-B','B',False);typed_noop=products(q/'typed-fresh-B')
            c.guard(prod.compare(q/'fresh-B-equivalence.json',b,typed_noop,True),'fresh B audit changed products')
            domain_control.zero(q/'unchanged-kernel-B','B')
            c.guard(prod.compare(q/'unchanged-kernel-B-equivalence.json',b,products(q/'unchanged-kernel-B'),True),'unchanged command changed products')
            if i in (0,4):behavior21041.run(q/'behavior-B','B')
            h.clean(m.TARGET);h.state('B');primary.command(q/'cold-B',c.CHECK,'independent-cold-B');cold=products(q/'cold-B')
            c.guard(prod.compare(q/'independent-B-equivalence.json',b,cold,False),'independent cold B program differs from warm B')
            if i in (0,4):
                h.clean(m.ROOT/'behavior');behavior21041.run(q/'behavior-cold-B','B')
                warm=m.read(q/'behavior-B/witness.json');fresh=m.read(q/'behavior-cold-B/witness.json')
                c.guard(warm['output_sha256']==fresh['output_sha256'] and warm['fixture_sha256']==fresh['fixture_sha256'] and warm['state']==fresh['state'],'independent native B behavior differs')
                h.clean(m.ROOT/'behavior')
            h.restore(seed,seal,rr,atime);proof=typed21041.run(q/'typed-B','B',True);typed_products=products(q/'typed-B')
            c.guard(len(proof['commands'])==8 and m.digest(m.canon(sorted(proof['commands'])))==P['prior_actual_argv_sha256'],'different actual rustc argv before enrollment')
            c.guard(prod.compare(q/'typed-equivalence.json',b,typed_products,True),'diagnostic vs plain first-edit output differs')
            normalize=lambda rows:sorted((act,pkg.replace('-','_'),version)for act,pkg,version in rows)
            normal=normalize(progress((q/'warm-B/cargo.stderr').read_bytes()))
            c.guard(normal==normalize(progress((q/'typed-B/cargo.stderr').read_bytes())) and sorted(n for act,n,version in normal)==P['edited_workspace_roster'],'eight plain/typed first-edit packages')
            streams=output_controls(q/'warm-B');m.save(q/'ordinary-controls.json',streams)
            m.save(q/'actual-cargo-opening.json',{'ordinary_progress':normal,'typed_active':proof['artifact_crates'],'actual_typed_commands':len(proof['commands'])})
            histories[role]=(seed,seal,rr);baseline[role]=(b,streams)
        derive_panel.verify_hold(out,tmp,i,c.ROLES,parse)
        for phase in ('ordinary-A','warm-B','cold-B'):
            left,right=[m.read(panel/f'opening-{i}-{r}'/phase/'products.json')for r in c.ROLES]
            same=(left['structural']==right['structural'])
            m.save(panel/f'opening-{i}-{phase}-cross-role.json',{'all_defs_and_reachable_shape_equal':same,'different':[k for k in left['structural']if left['structural'][k]!=right['structural'][k]],'absolute_headers':{role:{k:v['header'] for k,v in product['semantic'].items()}for role,product in zip(c.ROLES,(left,right))}})
            c.guard(left['relative_paths']==right['relative_paths'] and len(left['structural'])==len(right['structural'])==37,'unmatched native workspace product')
        values={}
        for role in P['orders'][i]:
            m.choose(role,bank,sdks);roleout=panel/f'pair-{i}-{role}';roleout.mkdir();values[role]={}
            seed,seal,rr=histories[role];expected,scheduled=baseline[role]
            for mode in P['mode_orders'][i]:
                s=h.restore(seed,seal,rr,atime);path=roleout/mode
                if mode=='scoped':
                    q=panel/f'opening-{i}-{role}'
                    scoped_result=physical.visit(role,roleout,q,sdks,s,expected,scheduled,products,output_controls,per_meter_ready)
                    values[role][mode]=dict(scoped_result,checkpoint_sha256=seal['sha256'])
                    continue
                if mode=='wall':
                    wall_clock.command(path,c.CHECK,'native',m.SRC,m.ENV)
                elif mode=='clock':
                    primary.command(path,c.CHECK,'pmu',binary)
                else:raise ValueError(('unregistered visit mode',mode))
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
    c.guard(len(opened_seeds)==16,'need 16 independently built and content/time-sealed A checkpoints')
    for role in c.ROLES:
        m.choose(role,bank,sdks);primary.final_sdk(role,sdks,m.SDK,out)
    m.save(panel/'raw-pairs.json',reports)
    domain_control.post_clock(out,ready)
if __name__=='__main__':run()
