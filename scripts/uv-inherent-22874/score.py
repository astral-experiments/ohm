"""Independently reopen raw clocks, source, outputs and the qualified per-role native histories."""
from fractions import Fraction
from statistics import median
from pathlib import Path
import gzip,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import core as c
from products import comparable,movement,identities
from screen import output_controls
m=c.m;P=c.P
def num(v):return {'fraction':str(v),'factor':round(float(v),6)}
def summary(rows):
    c.guard(len(rows)==4,'four preregistered pairs');result={}
    for metric in ('clock','wall'):
        ratios=[];holds=[[],[]];arms={r:[] for r in c.ROLES}
        for i,row in enumerate(rows):
            c.guard(row['pair']==i and row['order']==P['orders'][i] and row['hold']==P['independent_holds'][i] and row['modes']==P['mode_orders'][i],'pair design')
            values=[row['values'][r][metric]['value']for r in c.ROLES];c.guard(all(type(x)is int and x>0 for x in values),'positive raw clocks')
            for r,x in zip(c.ROLES,values):arms[r].append(x)
            ratio=Fraction(*values);ratios.append(ratio);holds[row['hold']].append(ratio)
        result[metric]={'raw_by_role':arms,'paired_control_over_candidate':[num(x)for x in ratios],'median_paired_factor':num(median(ratios)),
            'hold_medians':[num(median(v))for v in holds],'above_parity':sum(x>1 for x in ratios),'above_double':sum(x>2 for x in ratios),'n':4}
    return result
import mechanism
def score():
    w,tmp=c.host();out=w/'trait-results';panel=out/'uv-client';raw=m.read(panel/'raw-pairs.json');ready=m.read(out/'calibration.json')['ready'];_,meter=m.pmu(w,tmp)
    data={};refusals=[];checked={}
    parser=c.deep.parser(tmp/'uv22874-readers/check-root-20261101/ctfe-root-attribution/metadata.py')
    def check_products(at):
        obj=m.read(at/'products.json')
        c.guard(len(obj['raw'])==38 and obj['raw'].keys()==obj['semantic'].keys()==obj['relative_paths'].keys(),'declared product keys')
        for n,(size,key)in obj['raw'].items():
            if key not in checked:
                b=gzip.decompress((out/'rmeta-by-content'/(key+'.gz')).read_bytes());c.guard(len(b)==size and m.digest(b)==key,'retained raw workspace product')
                checked[key]=(n,size,m.canon(c.deep.project(parser,b,n)),identities(b,parser)if n=='uv_pypi_types'else None)
            actual_name,actual_len,actual_semantic,provider=checked[key]
            c.guard((actual_name,actual_len,actual_semantic)==(n,size,m.canon(obj['semantic'][n])),'independent semantic decode from original rmeta')
            if provider is not None:c.guard(provider==obj['provider'],'independent emitted impl/method identities')
        return obj
    for hold in(0,1):
        for r in c.ROLES:
            q=panel/f'hold-{hold}-{r}';a=check_products(q/'ordinary-A');settled=check_products(q/'settled-A');b=check_products(q/'warm-B');cold=check_products(q/'cold-B');t=check_products(q/'typed-B')
            c.guard(a==settled and comparable(b)==comparable(cold)==comparable(t),'prerequisite warm/cold/typed semantic equality')
            c.guard(movement(r,a['provider'],b['provider'])==m.read(q/'movement.json'),'native mechanism')
            c.guard(m.read(q/'A-unit-graph.json')['logical_sha256']==m.read(q/'B-unit-graph.json')['logical_sha256']==P['structural_graph_sha256'],'package graph')
            if hold==0:c.guard(all(m.read(q/('behavior-'+phase)/'witness.json')['exact']for phase in('A','B')),'native behavior')
            streams=output_controls(q/'warm-B');c.guard(streams==m.read(q/'ordinary-controls.json'),'opening command outputs')
            seal=m.read(q/'checkpoint.json')['sha256'];data[(hold,r)]=(b,seal,streams)
    for i,row in enumerate(raw):
        for r in c.ROLES:
            expected,seal,streams=data[(row['hold'],r)];q=panel/f'pair-{i}-{r}'
            for mode in P['mode_orders'][i]:
                at=q/mode;v=row['values'][r][mode];rec=m.read(at/'ordinary.json');s=m.read(at/'source.json')
                c.guard(rec['exit']==0 and rec['argv']==c.CHECK and rec['boot']==ready['boot'] and rec['cpus']==ready['affinity']and rec['ns']==rec['end_ns']-rec['start_ns']>0,'authentic whole-command timing')
                c.guard(s['head']==P['A']and s['working_tree']==P['B_tree']and s['source']==v['source_sha256']==P['B_file']and s['lock']==P['lock_sha256']and v['checkpoint_sha256']==seal,'source/checkpoint')
                c.guard(output_controls(at)==m.read(at/'ordinary-controls.json')==streams,'same-seed command diagnostics or package roster changed')
                observed=check_products(at);ok=observed==expected;c.guard(ok==v['same_seed_qualified']==m.read(at/'same-seed-equivalence.json')['passed'],'recorded raw/semantic gate')
                if not ok:refusals.append([i,r,mode])
                if mode=='wall':c.guard(rec['invoked']==c.CHECK and rec['mode']=='native'and not(at/'whole-clock.json').exists()and v['value']==rec['ns'],'uninstrumented whole wall')
                else:
                    clock=meter.clock(at/'whole-clock.json',0);c.guard(rec['invoked']==[ready['plain'],str(at/'whole-clock.json'),*c.CHECK]and clock['running']==clock['enabled']>0 and v['value']==clock['instructions'],'inherited unmultiplexed whole-command instructions')
    report={'scope':'optimized stage1, ordinary cargo check -p uv-client after uv #22874, screening only','eligible':not refusals,'same_seed_refusals':refusals,
            'verified_unique_workspace_products':len(checked),'metrics':None if refusals else summary(raw),'branch':P['branch'],'two_sided_sign_test_best_possible_with_four_pairs':0.125}
    ordinary=dict(report,per_rustc_endpoint='independently guarded');m.save(panel/'ordinary-score.json',ordinary)
    physical=mechanism.reduce(parser,out,panel);m.save(panel/'native-rustc.json',physical)
    terminal=[Fraction(row['user_instructions'][c.ROLES[1]]['uv_client'],row['user_instructions'][c.ROLES[0]]['uv_client'])for row in physical['per_hold']]
    sums=[Fraction(row['sum_of_nine_disjoint_compilers'][c.ROLES[1]],row['sum_of_nine_disjoint_compilers'][c.ROLES[0]])for row in physical['per_hold']]
    report['promotion']={'preregistered_primary_rustc':'terminal uv_client','terminal_user_instructions_child_over_parent':[str(v)for v in terminal],'all_nine_disjoint_ratio':[str(v)for v in sums],'terminal_20_percent_fewer_in_both_independent_histories':not refusals and all(x<=Fraction(4,5)for x in terminal),'confirmation':'four whole-Cargo screening pairs only; new held cohorts and the independent #21041 edit needed before any durable claim'}
    m.save(panel/'score.json',report);print(json.dumps(report,sort_keys=True));c.guard(not refusals,'same-seed raw or decoded product mismatch; clocks ineligible')
if __name__=='__main__':score()
