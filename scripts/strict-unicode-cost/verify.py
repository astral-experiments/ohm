"""Recompute results from raw kernel topology, NUL argv, PMU words and Cargo output."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import statistics as st

HERE=Path(__file__).resolve().parent
ROLES=('build_rustc','generator','unicode_rustc','ron')
ORDERS=('TS','ST','ST','TS','ST','TS','TS','ST')
def read(p):return json.loads(p.read_bytes())
def col(p):return [l.split('\t') for l in p.read_text().splitlines()]
def counts(d):
    pairs=col(d/'trace/counts.tsv')
    v={k:list(map(int,a)) for k,*a in pairs}
    assert len(v)==len(pairs) and set(v)=={'root','whole',*ROLES,*['hit-'+r for r in ROLES]}
    return v
def hw(v):return len(v)==4 and v[0]==0 and v[1]>0 and v[2]>0 and v[2]==v[3]
def ev(d):
    rows=[]
    for idx,pid,dev,ino,role,ln,image in col(d/'trace/exec.tsv'):
        raw=(d/'trace'/f'args-{int(idx):04}').read_bytes();assert raw.endswith(b'\0')
        rows.append((int(pid),[int(dev),int(ino)],int(role),int(ln),image,[x.decode() for x in raw[:-1].split(b'\0')]))
    return rows
def ancestors(edges,pid,root):
    result=set()
    while pid!=root:
        assert pid not in result and pid in edges,(pid,root,'disconnected process')
        result.add(pid);pid=edges[pid]
    result.add(root);return result
def topology(d,mode):
    v=counts(d);rows=ev(d);assert hw(v['whole'])
    assert v['root'][1]==read(d/'visit.json')['returncode']
    edges={}
    for kind,pid,child in col(d/'trace/spawn.tsv'):
        assert kind in ('1','2','3') and int(child) not in edges
        edges[int(child)]=int(pid)
    if mode=='sham':
        assert not rows and not edges and all(v['hit-'+r]==[0,0] and v[r]==[0,0,0,0] for r in ROLES)
        return v,rows,{},[]
    roots={}
    for i,r in enumerate(ROLES):
        candidates=[row for row in rows if row[2]==i]
        assert len(candidates)==1,(d,r,len(candidates))
        pid=candidates[0][0];assert v['hit-'+r]==[1,pid] and hw(v[r])
        roots[r]=candidates[0]
    pids={row[0] for row in roots.values()}
    assert len(pids)==4 and all(ancestors(edges,pid,v['root'][0])&pids=={pid} for pid in pids)
    assert sum(v[r][1] for r in ROLES)<v['whole'][1]
    return v,rows,roots,edges
def calibration_result(root):
    n=10_000_000;expected=dict(zip(ROLES,(4*n,6*n,16*n,10*n)))
    expected['whole']=sum(expected.values())+14*n
    results={}
    for mode in ('cal','sham'):
        v=[topology(root/'calibration'/f'{mode}-{i}',mode)[0] for i in range(4)]
        roles=('whole',*ROLES) if mode=='cal' else ('whole',)
        results[mode]={}
        for r in roles:
            delta=st.median(v[i][r][1] for i in (1,3))-st.median(v[i][r][1] for i in (0,2))
            results[mode][r]={'predicted':expected[r],'observed':delta,'relative_error':delta/expected[r]-1}
    return {'results':results,'admitted':all(abs(a['relative_error'])<.02 for g in results.values() for a in g.values())}
def after(a,k):
    assert a.count(k)==1;return a[a.index(k)+1]
def visit(root,name,subject,expected_warn):
    d=root/name;ctl=read(d/'visit.json');mode=ctl['observer'];v,rows,roots,edges=topology(d,mode)
    assert ctl['command']==subject['argv']
    js=[json.loads(x) for x in gzip.decompress((d/'stdout.gz').read_bytes()).splitlines()]
    gzip.decompress((d/'stderr.gz').read_bytes())
    ranks=Counter(x['reason'] for x in js);bad=name in ('warm-invalid','independent-empty-invalid')
    assert ctl['returncode']==(101 if bad else 0)
    assert js[-1]=={'reason':'build-finished','success':not bad}
    assert ranks['compiler-artifact']==(302 if bad else 303) and ranks['build-script-executed']==35
    diagnostics=[a['message'] for a in js if a['reason']=='compiler-message']
    actual_errors=[a for a in diagnostics if a['level']=='error']
    if bad:
        assert len(actual_errors)==1 and actual_errors[0]['code']['code']=='E0308'
        prim,=[s for s in actual_errors[0]['spans'] if s['is_primary']]
        assert prim['file_name']=='crates/ty_project/src/lib.rs' and 'OHM_RON_CHECK_BAD_TYPE' in prim['text'][0]['text']
    else:assert diagnostics==expected_warn
    obs=read(d/'products.json');assert obs['lock']==subject['lock']
    assert set(obs['generated'])=={'generated.rs','generated_phf.rs','generated_alias.rs'}
    assert all(x['bytes']>0 and len(x['sha256'])==64 for x in obs['generated'].values()) and obs['metadata']['bytes']>0
    art=[a for a in js if a['reason']=='compiler-artifact'];assert not any(a.get('executable') for a in art)
    inventory=sorted(((a['package_id'],a['target']['name'],a['target']['kind'],a['profile'],sorted(a['features'])) for a in art),key=lambda v:json.dumps(v,sort_keys=True))
    # Sorting after canonical serialization also covers multiple same target/profile variants.
    inventory_digest=hashlib.sha256(json.dumps(inventory,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    report={'counters':{r:v[r] for r in ('whole',*ROLES)} if mode=='roster' else {'whole':v['whole']},
            'diagnostics':diagnostics,'sha':{n:o['sha256'] for n,o in obs['generated'].items()},'out':obs['generated'],
            'sources':[obs['historical_source'],obs['test_source']],'inventory':inventory_digest,'metadata':obs['metadata']['sha256']}
    if mode=='sham':return report
    ids={k:s['identity'] for k,s in subject['tools'].items()}
    assert len([t for t in rows if t[1]==ids['cargo'] and t[5][1:]==subject['argv'][2:]])==1
    for role,crate,source,emit in [('build_rustc','build_script_build','crates/ruff_unicode_names2/build.rs','dep-info,link'),
            ('unicode_rustc','unicode_names2','crates/ruff_unicode_names2/src/lib.rs','dep-info,metadata'),
            ('ron','ron','/ron-0.12.0/src/lib.rs','dep-info,metadata')]:
        pid,ident,_,_,img,a=roots[role]
        assert ident==ids['rustc'] and after(a,'--crate-name')==crate and '--emit='+emit in a
        assert any(x.endswith(source) for x in a) and '-Zthreads=8' in a
    pid,ident,_,_,gen,args=roots['generator']
    assert gen==after(roots['build_rustc'][5],'--out-dir')+'/build_script_build' and args==[gen]
    wilds=[t for t in rows if t[1]==ids['wild'] and '-o' in t[5]]
    w,=[t for t in wilds if t[3]];assert after(w[5],'-o')==gen and roots['build_rustc'][0] in ancestors(edges,w[0],v['root'][0])
    gcc=[(t[4],t[0]) for t in rows if t[4].endswith('/collect2') and '-o' in t[5] and after(t[5],'-o')==gen]
    assert len(gcc)==1 and gcc[0][1] in ancestors(edges,w[0],v['root'][0])
    compilers=[after(a,'--crate-name') for _,i,_,_,_,a in rows if i==ids['rustc'] and '--crate-name' in a and '--out-dir' in a and not any(x.startswith('--print') for x in a)]
    if name.startswith('pair-') or name=='independent-unchanged':
        assert sorted(compilers)==['build_script_build','ron','unicode_names2'] and len(wilds)==1
    if name=='historical-edit':assert 'ty_project' in compilers
    report['native']={'compilers':compilers,'wild':len(wilds),'generator_pid':pid,'generator_identity':ident}
    return report
def summary(v):
    return {'raw':v,'minimum':min(v),'median':st.median(v),'maximum':max(v)}
def verify(root):
    subject=read(root/'strict-subject.json')
    expected={'cargo':'035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4','rustc':'f7663fb7dec7e5c7ea613a85ff1d6e4c00bf97b8c50534f17e5c95cd599712b9','driver':'dae4f8dc64b2b2ac9dc04dfe2cfad633d6af1a87da2dfc532e757ffe758680e3','wild':'0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5'}
    assert {k:v['sha256'] for k,v in subject['tools'].items()}==expected
    assert read(root/'acquired.json')['orders']==list(ORDERS)
    cal=calibration_result(root);assert cal['admitted'] and cal==read(root/'calibration-verdict.json')
    phases=['cold-original','historical-edit']+[f'pair-{i:02d}-{m}' for i,o in enumerate(ORDERS,1) for m in o]+['warm-invalid','warm-repair','independent-empty-invalid','independent-repair','independent-empty-edited','independent-unchanged']
    warn=read(HERE/'fixed-warning.json');rows={p:visit(root,p,subject,warn) for p in phases}
    assert len(phases)==24 and len({r['inventory'] for r in rows.values() if not any(a['level']=='error' for a in r['diagnostics'])})==1
    assert rows['warm-invalid']['diagnostics']==rows['independent-empty-invalid']['diagnostics']
    assert len({tuple(r['sha'].items()) for r in rows.values()})==1
    assert len({r['sources'][0] for r in rows.values()})==2 and len({rows[p]['sources'][0] for p in phases[1:]})==1
    assert len({r['sources'][1] for r in rows.values()})==2
    for prev,cur in zip(phases[1:17],phases[2:18],strict=True):
        assert any(rows[prev]['out'][n]['mtime_ns']!=rows[cur]['out'][n]['mtime_ns'] for n in rows[cur]['out']),('no observed fresh generator files',prev,cur)
    def val(row,stage='whole'):return row['counters'][stage][1]
    ts=[rows[f'pair-{i:02d}-T'] for i in range(1,9)];ss=[rows[f'pair-{i:02d}-S'] for i in range(1,9)]
    deviation=[val(t)/val(s)-1 for t,s in zip(ts,ss)];observer_ok=st.median([abs(x) for x in deviation])<.03 and max(map(abs,deviation))<.08
    endpoints={}
    for role in ROLES:
        share=[val(t,role)/val(t) for t in ts]
        separated=[val(t,role)>.5*max(val(t),val(s)) for t,s in zip(ts,ss)]
        independent=val(rows['independent-unchanged'],role)/val(rows['independent-unchanged'])
        endpoints[role]={'subtree':summary([val(t,role) for t in ts]),'share':summary(share),'ideal_total_ratio':summary([1/(1-f) for f in share]),
            'independent_repeat_share':independent,'upper_bound_could_reach_2x':observer_ok and all(separated) and independent>.5}
    return {'calibration':cal,'acquisition':'signed -21 compiler+stock Wild, strict non-distribution Cargo 761ea115','commands':24,
            'hardware':'PERF_COUNT_HW_INSTRUCTIONS, user mode, inherited threads/children, observed enabled == running',
            'whole_attributed':summary([val(x) for x in ts]),'whole_sham':summary([val(x) for x in ss]),
            'pair_order':ORDERS,'traced_over_sham_minus_one':summary(deviation),'sham_gate':observer_ok,'stages':endpoints,
            'controls':{p:{'counters':rows[p]['counters'],'native':rows[p]['native'],'diagnostics':[a['level']+' '+str((a.get('code') or {}).get('code')) for a in rows[p]['diagnostics']]} for p in phases if not p.startswith('pair-')},
            'generated_files':rows['cold-original']['sha'],'inventory':rows['cold-original']['inventory'],
            'independent_controls':'known complete warning, full compiler-artifact roster, three generator files; independently empty E0308 and repair'}
if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('packet',type=Path);d=ap.parse_args().packet
    top=verify(d);print(json.dumps(top,indent=2,sort_keys=True))
