"""Independently reopen raw clocks, source, outputs and the qualified per-role native histories."""
from fractions import Fraction
from statistics import median
from pathlib import Path
import gzip,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import core as c
from products import comparable
from screen import output_controls
m=c.m;P=c.P
def num(v):return {'fraction':str(v),'factor':round(float(v),6)}
def summary(rows):
    c.guard(len(rows)==8,'eight preregistered pairs');result={}
    for metric in ('wall','clock'):
        ratios=[];holds=[[],[]];arms={r:[] for r in c.ROLES}
        for i,row in enumerate(rows):
            c.guard(row['pair']==i and row['order']==P['orders'][i] and row['hold']==P['independent_holds'][i] and row['modes']==P['mode_orders'][i],'pair design')
            values=[row['values'][r][metric]['value']for r in c.ROLES];c.guard(all(type(x)is int and x>0 for x in values),'positive raw clocks')
            for r,x in zip(c.ROLES,values):arms[r].append(x)
            ratio=Fraction(*values);ratios.append(ratio);holds[row['hold']].append(ratio)
        result[metric]={'raw_by_role':arms,'paired_control_over_candidate':[num(x)for x in ratios],'median_paired_factor':num(median(ratios)),
            'hold_medians':[num(median(v))for v in holds],'above_parity':sum(x>1 for x in ratios),'above_double':sum(x>2 for x in ratios),'n':8}
    return result
def score():
    w,tmp=c.host();out=w/'trait-results';panel=out/'uv-client';raw=m.read(panel/'raw-pairs.json');ready=m.read(out/'calibration.json')['ready'];_,meter=m.pmu(w,tmp)
    data={};refusals=[];checked={}
    parser=c.deep.parser(tmp/'uv22874-readers/check-root-20261101/ctfe-root-attribution/metadata.py')
    def check_products(at):
        obj=m.read(at/'products.json');c.guard(len(obj['public_sidecars'])==415,'wrong sidecar inventory')
        c.guard(len(obj['raw'])==37 and obj['raw'].keys()==obj['semantic'].keys()==obj['relative_paths'].keys(),'declared product keys')
        for n,(size,key)in obj['raw'].items():
            if key not in checked:
                b=gzip.decompress((out/'rmeta-by-content'/(key+'.gz')).read_bytes());c.guard(len(b)==size and m.digest(b)==key,'retained raw workspace product')
                import wire_shape
                name=P['native_workspace_units'][n]['crate'];decoded=parser(b,name)
                checked[key]=(n,size,m.canon(c.deep.project(lambda *_:decoded,b,name)),wire_shape.shape(*decoded[:2]))
            c.guard(checked[key]==(n,size,m.canon(obj['semantic'][n]),obj['structural'][n]),'independently decoded complete rmeta and rooted key shape')
        return obj
    from derive import panel as derive_panel
    for hold in (0,1):
        derive_panel.verify_hold(out,tmp,hold,c.ROLES,parser,independent=True)
        for r in c.ROLES:
            q=panel/f'hold-{hold}-{r}';a=check_products(q/'ordinary-A');b=check_products(q/'warm-B')
            c.guard(a==check_products(q/'settled-A')==check_products(q/'typed-fresh-A'),'same-seed fresh A bytes')
            c.guard(b==check_products(q/'settled-B')==check_products(q/'typed-fresh-B')==check_products(q/'typed-B'),'same-seed B typed/plain/fresh bytes')
            c.guard(comparable(b)==comparable(check_products(q/'cold-B')),'independent B public/private, all definition/expansion/allocation and sidecar values')
            c.guard(m.read(q/'A-unit-graph.json')['logical_sha256']==m.read(q/'B-unit-graph.json')['logical_sha256']==P['structural_graph_sha256'],'complete original Cargo unit graph')
            for phase,actual in [('typed-fresh-A',False),('typed-fresh-B',False),('typed-B',True)]:
                units=m.read(q/phase/'actual-units.json');roster=m.read(q/phase/'roster.json')
                c.guard(units['logical_sha256']==P['native_complete_unit_sha256']and units['count']==P['native_cargo_artifacts']==486 and len(units['workspace'])==37,'complete actual package closure')
                c.guard(roster['artifact_crates']==({n:1 for n in P['edited_workspace_roster']}if actual else {}),'actual native rustc set')
                c.guard({k:v['rmeta']for k,v in units['workspace'].items()}==a['relative_paths'],'Cargo unit to original path')
            if hold==0:
                wits=[m.read(q/('behavior-'+phase)/'witness.json')for phase in('A','B','cold-B')]
                c.guard(all(x['exact'] and x['fixture_sha256']==m.filesha(c.HERE/'witness.rs') for x in wits)and len({x['output_sha256']for x in wits})==1,'independently linked native behavior')
            import domain_control
            for phase,original in [('A',a),('B',b)]:
                p=q/('unchanged-kernel-'+phase);domain_control.check_zero(p,phase)
                compiler=m.read(p/'compiler-image.json');installed=m.read(w/'trait-results/intake.json')['installed'][r]
                c.guard(compiler['sha256']==installed['runtime']['bin/rustc'],'unchanged kernel trace enrolled another executable')
                c.guard(check_products(p)==original,'unchanged original byte set differs')
            streams=output_controls(q/'warm-B');c.guard(streams==m.read(q/'ordinary-controls.json'),'opening command outputs')
            seal=m.read(q/'checkpoint.json')['sha256'];data[(hold,r)]=(b,seal,streams)
    for i,row in enumerate(raw):
        for r in c.ROLES:
            expected,seal,streams=data[(row['hold'],r)];q=panel/f'pair-{i}-{r}'
            for mode in P['mode_orders'][i]:
                if mode=='scoped':continue
                at=q/mode;v=row['values'][r][mode];rec=m.read(at/'ordinary.json');s=m.read(at/'source.json')
                c.guard(rec['exit']==0 and rec['argv']==c.CHECK and rec['boot']==ready['boot'] and rec['cpus']==ready['affinity']and rec['ns']==rec['end_ns']-rec['start_ns']>0,'authentic whole-command timing')
                c.guard(s['head']==P['A']and s['working_tree']==P['B_tree']and s['source']==v['source_sha256']==P['B_file']and s['lock']==P['lock_sha256']and v['checkpoint_sha256']==seal,'source/checkpoint')
                c.guard(output_controls(at)==m.read(at/'ordinary-controls.json')==streams,'same-seed command diagnostics or package roster changed')
                observed=check_products(at);ok=observed==expected;c.guard(ok==v['same_seed_qualified']==m.read(at/'same-seed-equivalence.json')['passed'],'recorded raw/semantic gate')
                if not ok:refusals.append([i,r,mode])
                if mode=='wall':c.guard(rec['timer']=='CLOCK_MONOTONIC; waitpid blocking; ITIMER_REAL watchdog'and rec['deadline_fired']is False and rec['invoked']==c.CHECK and rec['mode']=='native'and not(at/'whole-clock.json').exists()and v['value']==rec['ns'],'uninstrumented whole wall')
                else:
                    clock=meter.clock(at/'whole-clock.json',0);c.guard(rec['invoked']==[ready['plain'],str(at/'whole-clock.json'),*c.CHECK]and clock['running']==clock['enabled']>0 and v['value']==clock['instructions'],'inherited unmultiplexed whole-command instructions')
    import physical
    perf=physical.reduce(panel,raw,data,check_products,output_controls)
    report={'scope':'matched signed-release production builds, procedural derive impl identity, ordinary cargo check -p uv-client after actual uv edit #21041','eligible':not refusals,'same_seed_refusals':refusals,
        'verified_unique_workspace_products':len(checked),'metrics':None if refusals else summary(raw),'branch':P['branch']}
    if report['metrics']:
        for mode in ('wall','clock'):
            x=report['metrics'][mode]['raw_by_role']
            report['metrics'][mode]['paired_statistics']=physical.metric(list(zip(x[c.ROLES[0]],x[c.ROLES[1]],strict=True)))
    m.save(panel/'ordinary-score.json',report)
    left=m.read(out/'blocking-clock/passed.json');right=m.read(out/'blocking-clock-post/passed.json')
    c.guard(left['machine']==right['machine']=={'boot':ready['boot'],'cpus':ready['affinity']} and left['probe']==right['probe'] and all(len(t['samples'])==25 and t['nonzero_exit']==17 and t['deadline_exit']==-9 for t in (left,right)),'different pre/post wait calibration')
    if perf['complete']:perf['primary_test']=physical.preregistered_tests(perf['metrics'])
    m.save(panel/'native-rustc.json',perf)
    combined=dict(report,native_scope=perf['scope'],physical_complete=perf['complete'],primary_test=perf.get('primary_test'))
    m.save(panel/'score.json',combined);print(json.dumps(combined,sort_keys=True))
    c.guard(not refusals and perf['complete'],'at least one required visit could not be qualified')
if __name__=='__main__':score()
