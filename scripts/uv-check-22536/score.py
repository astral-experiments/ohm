"""Read all eligible raw clocks and counters, retaining the two code edits and the real review separately."""
from pathlib import Path
from statistics import median
from fractions import Fraction as Fr
from math import comb
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from basis import CASE,LOCK,PLAN,EVENTS,SIX,WUNITS,canon,digest,filehash,read,readz
import fixed_products
def ratios(pairs,strict_bar):
    values=[Fr(a,b)for a,b in pairs];assert len(values)==8 and all(v>0 for v in values)
    count=sum(x>strict_bar for x in values);p=Fr(sum(comb(8,i)for i in range(count,9)),256)
    return dict(raw_control_treatment=pairs,paired_ratios=list(map(str,values)),median=str(median(values)),four_pair_hold_medians=[str(median(x))for x in(values[:4],values[4:])],above_parity=sum(x>1 for x in values),above_bar=count,strict_bar=str(strict_bar),p_one_sided=str(p),eight_of_eight_and_both_holds=all(x>strict_bar for x in values)and all(median(x)>strict_bar for x in(values[:4],values[4:])))
def reduce_rows(source):
    vals=lambda pair,role,key,metric:sum((pair[role][s]['scoped'][metric]if metric in SIX else(sum(pair[role][s]['scoped'].values())if metric=='sum_six'else pair[role][s][metric]))for s in key)
    out={}
    for label,key in [('feature_B','B'),('auxiliary_C','C'),('rename_D','D'),('production_B_plus_D','BD'),('entire_B_plus_C_plus_D','BCD')]:
        out[label]={}
        for metric in ['wall','whole','sum_six',*SIX]:
            raw=[[vals(pair,role,key,metric)for role in ('P','T')]for pair in source];v=ratios(raw,Fr(5,4)if metric in SIX else Fr(2));out[label][metric]=v
            v['confirmatory_20pct_family']=metric in SIX and len(key)==1 and key in ('B','D')
            if v['confirmatory_20pct_family']:v['bonferroni_p_12']=str(min(Fr(1),12*Fr(v['p_one_sided'])))
    family=sorted([(Fr(out[n]['wall']['p_one_sided']),n)for n in ('feature_B','rename_D','production_B_plus_D')]);adjusted=Fr(0)
    for j,(p,n)in enumerate(family):
        adjusted=max(adjusted,min(Fr(1),p*(3-j)));out[n]['wall']['holm_p_for_individual_claims']=str(adjusted)
    return out
def inventory(tree,material):
    assert tree['images'][0]['file']==material['cargo_kernel_identity']and tree['exits'][tree['root']]==0
    rows={a['pid']:a for a in tree['images']if a['file']==material['rustc_kernel_identity']};assert all(Path(i['exe']).name!='rustc'or i['pid']in rows for i in tree['images']);return rows
def replay(root):
    cal=read(root/'calibration/accepted.json');qual=read(root/'qualification/accepted.json');cert=read(root/'compatibility.json');materials=read(root/'actual-inputs.json')
    assert qual['suitable_to_score']and cert['eligible']and qual['plan']==cal['protocol']==CASE['protocol']and cert['roles']==[qual['control'],'F']
    assert set(qual['actual_role_argv'])==set('BCD')and qual['upstream_rank_witnesses']=={r:{'A':0,'B':1,'C':1,'D':1}for r in cert['roles']};assert set(materials)=={'R','S','F'}and all(v['runtime_sha256']==LOCK['roles'][r]['hash'] and v['signed_cargo']==PLAN['control']['signed_22_cargo']and v['members']==142 and v['core_only']for r,v in materials.items())
    assert materials[qual['control']]['rustc_kernel_identity']!=materials['F']['rustc_kernel_identity'];machine=cal['boot'];values=[];receipts=[];seeds=set()
    for i,order in enumerate(PLAN['pairs']['pair_orders'],1):
        typed={};av={};arms={}
        for char in order:
            d=root/'pairs'/str(i)/char;meta=readz(d/'complete.json.gz');assert meta['pair']==i and meta['arm']==char and meta['hold']==1+(i-1)//4 and meta['boot']==machine and meta['compiler']==(qual['control']if char=='P'else'F')
            av[char]=meta['argument_surface'];six={};seen=set();mat=materials[meta['compiler']];assert read(d/'seed.json')['cold_executable_identity']==mat['rustc_kernel_identity'];cold=readz(d/'cold-A/argv.json.gz');assert len(cold['all_units'])==497 and len(cold['all_other_rustcs'])==45 and cold['workspace_rmeta_from_argv'].keys()==WUNITS
            cs=d/'cold-A/kernel.json.gz';ct=EVENTS['decode'](readz(cs));all_cold=inventory(ct,mat);assert len(all_cold)==542 and set(all_cold)=={row[1]for row in cold['all_units']}|{row[0]for row in cold['all_other_rustcs']};sh=filehash(cs);assert sh not in seeds;seeds.add(sh)
            assert read(d/'seed.json')['target_bytes_modes_times_sha256']==meta['seed_target'];assert set(meta['values'])==set('BCD')
            for s in 'ABCD':
                q=d/('noedit-'+s);quiet=readz(q/'argv.json.gz');assert not quiet['all_units']and not quiet['all_other_rustcs']and not inventory(EVENTS['decode'](readz(q/'kernel.json.gz')),mat)
                if s=='A':continue
                native=d/('native-'+s);forms=readz(native/'argv.json.gz');argv={n:r[0]for n,r in forms['forms'].items()};assert sorted(argv)==SIX and not forms['all_other_rustcs']
                real=inventory(EVENTS['decode'](readz(native/'kernel.json.gz')),mat);assert len(real)==6 and all(real[pid]['argv']==argv[name]for name,pid,parent in forms['all_units']);assert digest(canon(av[char][s]))==qual['actual_role_argv'][s]
                gold=readz(native/'products.json.gz');assert gold['workspace'].keys()==WUNITS and len(gold['public_sidecars'])==423 and readz(native/'typed-warm-cold.json.gz')['accepted']
                fixed=readz(native/'fixed-products.json.gz');assert {Path(p)for p in fixed}==fixed_products.paths({n:v[0]for n,v in gold['workspace'].items()})
                for visit in ('wall','whole','scoped'):
                    run=d/(visit+'-'+s);assert readz(run/'products.json.gz')==gold and readz(run/'fixed-products.json.gz')==fixed
                w=read(d/('wall-'+s)/'ordinary.json');assert w['ns']==w['end_ns']-w['start_ns']>0 and w['exit']==0 and not w['deadline_fired']and w['boot']==machine and w['cpus']==cal['cpus']
                whole=read(d/('whole-'+s)/'whole.json');assert whole['instructions']>0 and whole['event_errno']==whole['code']==0 and 995*whole['enabled']<=1000*whole['running']<=1000*whole['enabled'] and whole['start']<whole['stop']
                sc=d/('scoped-'+s);r=read(sc/'per-rustc.json');tree=EVENTS['decode'](readz(sc/'kernel.json.gz'));req=readz(sc/'request.json.gz');assert req['selectors']==argv and tree['images'][0]['argv']==req['command']==w['argv']and w['argv'][1:]==PLAN['command'][1:]and tree['exits'][tree['root']]==0 and r['root']==tree['root']
                actual=inventory(tree,mat);assert len(actual)==6 and sorted(r['targets'])==SIX
                obs={}
                for name,row in r['targets'].items():
                    import struct
                    instructions,en,ru,event=struct.unpack('=QQQQ',bytes.fromhex(row['raw_hex']));assert instructions==row['instructions']>0 and en==row['time_enabled_ns']and ru==row['time_running_ns']and 0<ru==en and event==row['event_id']and event not in seen;seen.add(event)
                    pid=row['pid'];assert row['argv']==argv[name]==actual[pid]['argv']and row['file']==actual[pid]['file']and tree['exits'][pid]==0;obs[name]=instructions
                six[s]={'wall':w['ns'],'whole':whole['instructions'],'scoped':obs};assert six[s]==meta['values'][s]
            arms[char]=six;typed[char]=meta['seed_target'];receipts.append([i,char,filehash(d/'complete.json.gz')])
        assert av['P']==av['T'];values.append(arms)
    assert len(seeds)==16
    return {'protocol':CASE['protocol'],'machine':machine,'control':qual['control'],'treatment':'F','paired_order':PLAN['pairs']['pair_orders'],'complete_pairs':8,'unique_genuine_cold_kernel_digests':sorted(seeds),'held_by_source':True,'per_pair_raw':values,'endpoints':reduce_rows(values),'raw_complete_arms':receipts,'replicated_on_independent_host':False}
if __name__=='__main__':print(json.dumps(replay(Path(sys.argv[1])),sort_keys=True,indent=2))
