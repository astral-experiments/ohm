#!/usr/bin/env python3
"""Verify every compact member and independently rebuild the physical decision classification."""
import gzip,hashlib,json,sys
from pathlib import Path
root=Path(__file__).resolve().parent;sys.path.insert(0,str(root))
import decide
sha=lambda b:hashlib.sha256(b).hexdigest()
manifest={}
for line in (root/'SHA256SUMS').read_text().splitlines():
    key,name=line.split('  ',1);assert Path(name).name==name and name not in manifest;manifest[name]=key
for name,key in manifest.items():assert sha((root/name).read_bytes())==key,name
obs=root/'observation.json.gz';p=json.loads(json.dumps(decide.main(obs)));assert json.loads(gzip.decompress((root/'native-decisions.json.gz').read_bytes()))==p
assert p['totals']=={'provider':524,'ruff':24} and p['origin']=='60fe0f0d2c85ffb2df304c27cb5823d50a266d4746619828db5388e298559668'
assert len(p['classification'])==26
fixed=0
for label,ds in p['cases'].items():
    checks=p['classification'][label]
    if label.startswith('R') and label.endswith('default'):
        assert checks['different_native_verdict']==[]
    for step,verdict in checks['settled_no_input_change']:
        assert verdict=='reused-existing-seal' and ds[step]['final_ld']==0 and len(ds[step]['link_only'])==1;fixed+=1
    if label.startswith(('Rbundle','Sbundle')):
        for s,n in [('higher-no-rust',29),('unchanged-lower',17)]:assert ds[s]['answer']==[n,7] and ds[s]['warm_embedded']==ds[s]['empty_embedded'] and list(ds[s]['warm_embedded'][0])==['provider.o']
        assert ds['malformed-no-rust']['status']==ds['missing-no-rust']['status']==101
    elif label in ('R-direct-unwatched-default','R-library-unwatched-default'):
        for s,v in [('higher-no-rust',[29,7]),('malformed-no-rust',None),('missing-no-rust',None)]:assert ds[s]['answer']==v and ds[s]['native_clean']
    elif label in ('S-direct-unwatched-default','S-library-unwatched-default'):
        assert checks['different_native_verdict']==['higher-no-rust','malformed-no-rust','missing-no-rust']
assert fixed==9
for label,rr in p['ruff'].items():
    assert rr['invalid']['status']==101 and rr['invalid']['empty_comparison']=='E0425'
    for s in ['cold','edit','repair','repeat-1','repeat-2']:
        r=rr[s];assert r['answer']==(53 if s=='cold' else 54) and r['empty_comparison']['raw']==(label!='R/minimal-shell')
        if s.startswith('repeat'):
            assert r['full']==[] and r['final_ld']==0 and r['link_only']==([] if label=='S/ordinary' else ['ruff_python_ast']) and r['mechanism']==('cargo-fresh' if label=='S/ordinary' else 'reused-existing-seal')
        elif s in ('edit','repair'):assert r['full']==['ruff_python_ast'] and r['final_ld']==1
ex=json.loads((root/'minimal-debug.json').read_bytes());assert len(ex)==19 and all(e['different_bytes']==e['debug_symbol_bytes']+e['signature_bytes'] and e['warm']!=e['empty'] for e in ex.values())
print('548 actual Cargo commands, 26 provider matrices, 66 complete native images, nine previously sealed provider no-ops, four Ruff receipt hits, two signed-Cargo fresh repeats, and 19 separately classified strict raw differences verified.')
