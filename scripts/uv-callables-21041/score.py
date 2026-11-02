"""Independently replay the existing native products and every wall/resource/process observation."""
from pathlib import Path
import gzip,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import core as c,wall_clock
from products import comparable
from screen import output_controls
from wall_tail import policy,visit,resources
from wall_tail.policy import enroll as enroll_seed
m=c.m;P=c.P
def score():
    w,tmp=c.host();out=w/'trait-results';panel=out/'uv-client';raw=m.read(panel/'raw-pairs.json');ready=m.read(out/'calibration.json')['ready'];wall_plan=policy.plan();visit.boot()
    checked={};resources_by_pair=[]
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
    opened_seeds = set()
    for i,hold in enumerate(wall_plan['blocks']):
        derive_panel.verify_hold(out,tmp,i,c.ROLES,parser,independent=True)
        for r in c.ROLES:
            q=panel/f'opening-{i}-{r}';a=check_products(q/'ordinary-A');b=check_products(q/'warm-B')
            c.guard(a==check_products(q/'settled-A')==check_products(q/'typed-fresh-A'),'same-seed fresh A bytes')
            c.guard(b==check_products(q/'settled-B')==check_products(q/'typed-fresh-B')==check_products(q/'typed-B'),'same-seed B typed/plain/fresh bytes')
            c.guard(comparable(b)==comparable(check_products(q/'cold-B')),'independent B public/private, all definition/expansion/allocation and sidecar values')
            c.guard(m.read(q/'A-unit-graph.json')['logical_sha256']==m.read(q/'B-unit-graph.json')['logical_sha256']==P['structural_graph_sha256'],'complete original Cargo unit graph')
            for phase,actual in [('typed-fresh-A',False),('typed-fresh-B',False),('typed-B',True)]:
                units=m.read(q/phase/'actual-units.json');roster=m.read(q/phase/'roster.json')
                c.guard(units['logical_sha256']==P['native_complete_unit_sha256']and units['count']==P['native_cargo_artifacts']==486 and len(units['workspace'])==37,'complete actual package closure')
                c.guard(roster['artifact_crates']==({n:1 for n in P['edited_workspace_roster']}if actual else {}),'actual native rustc set')
                c.guard({k:v['rmeta']for k,v in units['workspace'].items()}==a['relative_paths'],'Cargo unit to original path')
            wits=[m.read(q/('behavior-'+phase)/'witness.json')for phase in('A','B','cold-B')]
            c.guard(all(x['exact'] and x['fixture_sha256']==m.filesha(c.HERE/'witness.rs') for x in wits)and len({x['output_sha256']for x in wits})==1,'independently linked native behavior')
            import domain_control
            for phase,original in [('A',a),('B',b)]:
                p=q/('unchanged-kernel-'+phase);domain_control.check_zero(p,phase)
                compiler=m.read(p/'compiler-image.json');installed=m.read(w/'trait-results/intake.json')['installed'][r]
                c.guard(compiler['sha256']==installed['runtime']['bin/rustc'],'unchanged kernel trace enrolled another executable')
                c.guard(check_products(p)==original,'unchanged original byte set differs')
            streams=output_controls(q/'warm-B');c.guard(streams==m.read(q/'ordinary-controls.json'),'opening command outputs')
            seal=enroll_seed(opened_seeds,m.read(q/'checkpoint.json'),i,r)
            renderer=wall_clock.current()
            target=q/'edited-kernel-B';forms=m.read(q/'typed-B/roster.json')['commands'];enrollment=m.read(target/'enrollment.json');installed=m.read(out/'intake.json')['installed'][r]
            c.guard(enrollment['compiler_sha256']==installed['runtime']['bin/rustc'] and enrollment['compiler']==str(m.RUSTC) and enrollment['original_argv']==c.CHECK,'wrong real kernel binaries')
            actual=visit.kernel_receipt(m.read(target/'kernel-events.json'),enrollment,forms,c.CHECK,domain_control.ev['decode'])
            c.guard(actual==m.read(target/'actual-rustcs.json') and output_controls(target)==streams and check_products(target)==b,'changed separate kernel process, product or diagnostics')
            at=q/'warm-B';kv=m.read(at/'resources.json');rec=m.read(at/'ordinary.json');state=m.read(at/'source.json')
            backed=m.read(target/'source.json');invariant=set(state)-{'source_mtime_ns'};c.guard(set(backed)==set(state)and all(state[k]==backed[k]for k in invariant),'different actual original source state for the kernel replay')
            c.guard(state['head']==P['A'] and state['working_tree']==P['B_tree'] and state['source']==P['B_file'] and state['lock']==P['lock_sha256'] and state['index']==P['A_tree'] and state['patch_sha256']==P['edit_sha256'],'actual edited source')
            c.guard(rec['exit']==0 and rec['argv']==rec['invoked']==c.CHECK and rec['boot']==ready['boot']==renderer['boot'] and rec['cpus']==ready['affinity'] and rec['ns']==rec['end_ns']-rec['start_ns']>0 and rec['mode']=='native' and rec['deadline_fired'] is False and rec['timer']=='CLOCK_MONOTONIC; waitpid blocking; ITIMER_REAL watchdog','bare ordinary clock')
            c.guard(not {'RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','CARGO_LOG','RUSTC_LOG','LD_PRELOAD'}.intersection(rec['env']) and not (at/'kernel-events.json').exists()and not(at/'whole-clock.json').exists(),'instrumented timed Cargo')
            ares,bres=kv['before'],kv['after'];c.guard(ares['end_ns']<=rec['start_ns']<rec['end_ns']<=bres['start_ns']and ares['affinity']==rec['cpus']==bres['affinity']and resources.delta(ares,bres)==kv['delta'],'changed resource scope, boundaries or delta')
            assert len(raw)==16 and raw[i]['pair']==i and raw[i]['block']==hold and raw[i]['order']==wall_plan['order'][i]
            info=raw[i]['values'][r];assert info=={'wall_ns':rec['ns'],'checkpoint':seal,'source':state['source'],'resources_sha256':m.filesha(at/'resources.json'),'kernel_sha256':m.filesha(target/'kernel-events.json')}
            resources_by_pair.append({'pair':i,'block':hold,'role':r,'start_ns':rec['start_ns'],'end_ns':rec['end_ns'],'wall_ns':rec['ns'],'checkpoint':seal,'pid':rec['pid'],'diagnostics_sha256':m.filesha(at/'cargo.stderr'),'finished':[x.strip()for x in (at/'cargo.stderr').read_text().splitlines()if 'Finished 'in x], 'resource_deltas':kv['delta'],'raw_resources_path':str((at/'resources.json').relative_to(out)),'separate_kernel_compilers':actual['rustcs']})
    c.guard(len(opened_seeds)==32 and len(resources_by_pair)==32,'incomplete independent A seeds or resource samples')
    resources_by_pair.sort(key=lambda v:(v['pair'],wall_plan['order'][v['pair']].index(v['role'])))
    c.guard(all(x['end_ns']<y['start_ns'] for x,y in zip(resources_by_pair,resources_by_pair[1:])), 'actual time order changed')
    report=policy.score([[row['values'][r]['wall_ns']for r in c.ROLES]for row in raw]);report.update(registration_sha256=policy.SHA,original_negative_pairs=wall_plan['old_ordinary_clocks'],ordered_visits=resources_by_pair,verified_unique_raw_workspace_products=len(checked),causal_limit='Each pressure or shared cgroup counter is a coincident observation. This on/off design has no within-visit scheduler or CPU-stack attribution.')
    m.save(panel/'wall-tail-score.json',report)
    print({'guard_passed':report['pass'],'block_medians':report['block_medians_C_over_P'],'below_1_20':report['strictly_below_1_20'],'at_least_twofold':report['candidate_slower']['at_least_2']},flush=True)
if __name__=='__main__':score()
