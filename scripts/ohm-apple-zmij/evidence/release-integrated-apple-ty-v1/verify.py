"""Independently verify full clock observations and the native Apple developer workload."""
import argparse
import collections
import gzip
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parent
PHASES=("edit","repeat-1","repeat-2")
ENDPOINTS=(*PHASES,"edit+repeat-1")
ROLES="PC"
ALLOCATIONS=list(itertools.combinations(range(12),6))
def read(path):
    data=path.read_bytes()
    if path.suffix=='.gz':data=gzip.decompress(data)
    return json.loads(data)
def digest(data):
    return hashlib.sha256(data).hexdigest()
def packed(obj):
    return gzip.compress((json.dumps(obj,sort_keys=True,separators=(',',':'))+'\n').encode(),mtime=0)
def prove_clocks(study,stage,data):
    n={'screen':2,'confirmation':12}[stage]
    code={'rust':257,'cargo':428}[study]
    order=['PC','CP'] if n==2 else ['PC' if i in ALLOCATIONS[code] else 'CP' for i in range(n)]
    assert data['stage']==stage and data['order']==order
    assert len(data['raw_clocks'])==n*2*3 and len(data['typed_products'])==n*2*4
    anchors={}
    for row in data['typed_products']:
        assert row['units']>=350 and row['complete_bytes']>=20_000_000 and row['raw'] in data['images']
        assert all(len(row[k])==64 for k in ('raw','request','modules','receipt','norm'))
        key=(row['role'],row['phase'])
        v=(row['request'],row['norm'],row['modules'])
        assert anchors.setdefault(key,v)==v
    for r in ROLES:
        assert anchors[r,'cold'][1]!=anchors[r,'edit'][1] and anchors[r,'edit'][1]==anchors[r,'repeat-1'][1]==anchors[r,'repeat-2'][1]
    actual={}
    previous=-1
    for row in data['raw_clocks']:
        key=(row['pair'],row['role'],row['phase']);assert key not in actual
        assert previous<row['start']<row['end'] and row['end']-row['start']==row['ns']
        assert row['user']>=0 and row['system']>=0
        assert all(len(row[k])==64 for k in ('time_l','stdout','stderr'))
        actual[key]=row;previous=row['end']
    assert list(actual)==[(i,r,ph) for i,roles in enumerate(order,1) for r in roles for ph in PHASES]
    assert all(q['work_products'] and q['graph'] and q['objects']>0 for q in data['cache'])
    assert data['ordinary_cli_executions']==n*2*4
    assert set(data['scores'])==set(ENDPOINTS)
    for endpoint in ENDPOINTS:
        pieces=('edit','repeat-1') if endpoint=='edit+repeat-1' else (endpoint,)
        pairs=[[sum(actual[i,r,q]['ns'] for q in pieces) for r in ROLES] for i in range(1,n+1)]
        report=data['scores'][endpoint]
        assert pairs==report['pairs']
        ratios=[x/y for x,y in pairs]
        assert statistics.median(ratios)==report['paired']
        assert all(statistics.median(p[j] for p in pairs)/1e9==report['median_'+r] for j,r in enumerate(ROLES))
        if 'tree_cpu_seconds' in report:
            cpu=[[sum(actual[i,r,q]['user']+actual[i,r,q]['system'] for q in pieces) for r in ROLES] for i in range(1,n+1)]
            assert report['tree_cpu_seconds']==cpu
        if n==12:
            assert report['ci']==[sorted(ratios)[2],sorted(ratios)[9]]
            log=[math.log(r/2) for r in ratios];oriented=[x if s=='PC' else -x for x,s in zip(log,order)]
            p=sum(sum(x if i in alloc else -x for i,x in enumerate(oriented))/n>=statistics.mean(log)-1e-12 for alloc in ALLOCATIONS)/924
            assert p==report['p']
    if study=='cargo':
        sel=data['physical_cargo_selections'];assert len(sel)==2*n
        for role,sha in (('P','2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c'),('C','fd55a13d0220748794ba3c7c9556ef8ceed8591f')):
            group=[x for x in sel if x['role']==role];assert len(group)==n and {x['source'] for x in group}=={sha}
            assert len({(x['binary']['dev'],x['binary']['ino'],x['binary']['sha256']) for x in group})==1
    else:assert data['physical_cargo_selections']==[]
    if n==12:assert data['twofold_primary']==(data['scores']['repeat-1']['ci'][0]>2 and data['scores']['repeat-1']['p']<=.05)
    return n
def proof_native(subj,sets):
    expected={'clean-old/clean','clean-new/clean','visits/cold','visits/edit','visits/repeat-1','visits/repeat-2','visits/invalid','visits/repair'}
    assert set(sets)=={'PC','CP'}
    for order,groups in sets.items():
        assert set(groups)==set(ROLES)
        for r,visits in groups.items():
            assert set(visits)==expected
            for name,record in visits.items():
                q=record['observation'];p=record['product']
                assert q['objc2']==q['full'].count('objc2') and q['final_links']<=q['ld']
                if name=='visits/invalid':
                    assert q['status']==101 and q['verdict'] is None and p is None and q['ld']==0
                    continue
                old=name in ('clean-old/clean','visits/cold')
                assert q['status']==0 and q['verdict']==(0 if old else 1)
                anchor=visits['clean-old/clean' if old else 'clean-new/clean']['product']
                assert p['outcome']==anchor['outcome']
                assert all(p['native'][k]==anchor['native'][k] for k in ('norm','modules_sha','module_count','output_sha'))
                assert p['native']['module_count']>0 and q['units']>=350
            assert visits['visits/cold']['product']['native']['norm']!=visits['visits/edit']['product']['native']['norm']
        for step in ('visits/repeat-1','visits/repeat-2'):
            p,c=[groups[r][step]['observation'] for r in ROLES]
            assert (p['objc2'],c['objc2'])==(1,0) and len(c['full'])<len(p['full']) and c['ld']<=p['ld']
    return 32

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--partial',action='store_true',help='Read local intermediate packet before final packaging')
    args=parser.parse_args()
    if not args.partial:
        for line in (ROOT/'SHA256SUMS').read_text().splitlines():
            dg,p=line.split('  ',1);assert digest((ROOT/p).read_bytes())==dg,p
    info=read(ROOT/'index.json')
    assert (info['run'],info['qa'])==(41114554812,'82173e48173fedfc71a3c5ebad3c9d23e0bcfe81')
    subjects=read(ROOT/'native-subjects.json.gz')
    assert (subjects['host']['machine'],subjects['filesystem'].lower())==('arm64','apfs')
    assert subjects['host']['xcode']=='Xcode 16.0\nBuild version 16A242d'
    assert subjects['rust']['P']['source']=='9b4b11ce8cb84020be10dc54a6426807bfa87caa'
    assert subjects['rust']['C']['source']=='01dccb633d12cc0124c06e02c858aff74af1dcea'
    assert subjects['rust']['P']['driver']!=subjects['rust']['C']['driver']
    assert subjects['rust']['P']['std']==subjects['rust']['C']['std'] and len(subjects['rust']['P']['std'])==54
    assert subjects['rust']['P']['members']==subjects['rust']['C']['members']==2466
    assert subjects['observer']['ld']==subjects['stock_ld']=='2b48a59af70235283aa94c43eb0dd2ef80182c106db43279db936cc87426b443'
    assert subjects['cargo']['aware']['source']=='fd55a13d0220748794ba3c7c9556ef8ceed8591f'
    assert subjects['cargo']['signed']['source']=='2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c'
    a=read(ROOT/'provider-cross-host.json');assert a['observations']==1596 and not a['semantic_differences'] and not a['native_work_differences']
    assert len(a['relocated_standalone_linker_output_paths'])==84
    assert all(pair[0]==pair[1] for pair in a['compiler_drivers'].values())
    for study,stages in info['studies'].items():
        native=read(ROOT/(study+'-structural.json.gz'));proof_native(study,native)
        for stage in stages:
            clock=read(ROOT/(study+'-'+stage+'.json.gz'));n=prove_clocks(study,stage,clock)
            print(study,stage,n,'pairs;',', '.join(f'{k} {clock["scores"][k]["paired"]:.4f}x' for k in ENDPOINTS))
        print(study,'32 genuine native checks')
if __name__=='__main__':main()
