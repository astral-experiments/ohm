"""Read the four eligible samples only after independently verifying every accepted visit."""
from pathlib import Path
from fractions import Fraction
import gzip,json,sys
here=Path(__file__).resolve().parent;sys.path.insert(0,str(here))
import bridge
G=bridge.guard
def one(where,role,order):
    q=where/'qualification';qual=bridge.read(q/'passed.json');G(qual['positive_behavior']and qual['original_signed_raw_veto']and qual['rmeta']==96,'qualification')
    G(bridge.read(q/'canonical.json')['pass']and qual['role']==role and qual['hold']==order['hold'],'independent cold qualification')
    target=bridge.read(q/'first-B-ordinary/all-products.json');checks=['first-B-typed','first-B-vv','first-B-kernel']
    G(all(bridge.read(q/p/'all-products.json')==target for p in checks)and all(bridge.read(where/p/'all-products.json')==target for p in ['native','pmu','targeted-rustc']),'all same-seed originals')
    obs=bridge.read(where/'observed.json');G(obs['role']==role and obs['order']==order and obs['discovery_only'],'sample order')
    full=bridge.read(where/'pmu/whole-clock.json');n=bridge.read(where/'native/ordinary.json');pmu=bridge.read(where/'pmu/ordinary.json')
    G(n['argv']==pmu['argv']==['/tmp/uv-workflow-search/sdk/bin/cargo','check','--locked','--offline','-j8'] and n['argv']==n['invoked']and n['mode']=='native'and pmu['mode']=='pmu'and n['exit']==pmu['exit']==0 and n['ns']==n['end_ns']-n['start_ns']>0,'actual ordinary visits')
    G(n['cpus']==pmu['cpus']and n['boot']==pmu['boot']and n['env']==pmu['env'] and all(k not in n['env']for k in ('RUSTC_WRAPPER','CARGO_LOG','RUSTC_WORKSPACE_WRAPPER')),'ordinary env/host')
    G(full['code']==full['event_errno']==0,'whole-command native meter exit')
    G(full['instructions']>0 and full['running']==full['enabled']>0,'direct whole CPU counter')
    tr=bridge.read(where/'targeted-rustc/per-rustc.json')['targets'];vr=dict(bridge.read(where/'targeted-rustc/verified-kernel.json')['compilers']);ref=bridge.read(where/'per-rustc-request.json')['selectors']
    means={k:v['instructions']for k,v in tr.items()};G(set(bridge.P['selectors'])<=set(means)==set(ref) and len(means)==len(vr)and all(v['argv']==vr[v['pid']]==ref[k]for k,v in tr.items()),'actual selected threads/groups')
    score={'whole_cargo_userspace_instructions':full['instructions'],'uninstrumented_elapsed_ns':n['ns'],'selected_rustc_instructions':{k:means[k]for k in bridge.P['selectors']},'exploratory_other_rustc_instructions':{k:v for k,v in means.items()if k not in bridge.P['selectors']}}
    G(score==obs['values'],'independent raw endpoint reduction')
    return score
def report(out):
    G(bridge.read(out/'discovery-complete.json')['pairs']==2 and bridge.read(out/'final-sdk.json').keys()==bridge.P['roles'].keys(),'both independent completed material scopes')
    rows=[]
    for order in bridge.P['order']:
        points={r:one(out/f"hold{order['hold']}-{r}",r,order)for r in order['roles']};a=points['stock_ctfe318'];b=points['fa7a_stack_ctfe318']
        ratios={k:float(Fraction(a[k],b[k]))for k in ('whole_cargo_userspace_instructions','uninstrumented_elapsed_ns')}
        ratios['named_rustc']={k:float(Fraction(a['selected_rustc_instructions'][k],b['selected_rustc_instructions'][k]))for k in bridge.P['selectors']}
        pct={k:100.0*(1.0-b['selected_rustc_instructions'][k]/a['selected_rustc_instructions'][k])for k in bridge.P['selectors']}
        rows.append({'order':order,'raw_endpoints':points,'control_over_treatment':ratios,'three_primary_rustc_percent_instructions_removed':pct})
    return {'scope':'two matched discovery pairs; no recurrence or significance claim','pairs':rows,'signed_raw_opening_veto_preserved':True}
if __name__=='__main__':
    w,_=bridge.host();p=w/'trait-results';(p/'two-pair-discovery.json').write_text(json.dumps(report(p),sort_keys=True,indent=2)+'\n')
