"""Price the bounded cuts against a *different* conserving boot, retaining both refusals."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import reopen

SPECS = [
    (41668727619, '64456b5166ee3b4d36accaeba035966e97aa77798c2f9b5049389f914d6d69b4'),
    (41671338175, '1589f1657ff57aaa21c948afb840a01f902b751ade880e85c9c489dc4d533834'),
    (41675206812, '9dc7adaa541bb2d2e9cc4c9287a6c56fa9b850fffad3218bf13c321572b52f9d'),
]
REOPENED = 'ab29199f24f47fb86d1ea05064d31e3f2a598946b839e1d4fd930e71a29bd190'

def receipt(path, spec, per_name):
    run, digest = spec
    with open(path,'rb') as f:
        assert hashlib.file_digest(f,'sha256').hexdigest() == digest
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        reg = json.loads(z.read('registration.json'))
        assert reg['run'] == str(run)
        census = reopen.doc(z,'current-observed/owner-census.json.gz')
        outputs = reopen.doc(z,'current-observed/inventory.json.gz')['executables']
        o = census['outer']
        assert o[0] > 0 and o[1] == o[2] > 0 and o[3] == 0
        wild = {}
        sha = {}
        for item in census['roles']:
            if item['mode'] != 'Wild':
                continue
            av = reopen.argv(z.read('current-observed/tasks/' + item['argv']))
            output = av[av.index('-o')+1]
            key = Path(output).name
            assert key in per_name
            ins, ena, ran = item['counter']
            assert ins > 0 and ena == ran > 0
            assert item['trigger'] not in wild.setdefault(key,{})
            wild[key][item['trigger']] = ins
            sha[key] = outputs['target/' + output.split('/target/',1)[1]]['elf']['sha256']
        assert sorted(wild) == sorted(per_name) and all(set(a) == {'exec','first'} for a in wild.values())
        totals = {key:sum(a.values()) for key,a in wild.items()}
        delta = o[0] - sum(a['counter'][0] for a in census['roles'])
        return dict(run=run, original_sha256=digest, registered_head=reg['head'], boot=reg['boot'],
                    outer=o[0], actual_wild=sum(totals.values()), epoch_difference=delta,
                    conserved=abs(delta)<=1_000_000, output_sha256=sha, wild=totals)

def main(reopened,prior1,prior2,current,outfile):
    raw=Path(reopened).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==REOPENED
    new=json.loads(raw)
    per={p['name']:p for p in new['per_target']}
    cases=[receipt(p,spec,per)for p,spec in zip((prior1,prior2,current),SPECS)]
    assert [r['conserved']for r in cases]==[False,True,False]
    assert len({r['boot']for r in cases})==3 and not new['workspace_component_budgets_admitted']
    current_sha=cases[-1]['output_sha256']
    for r in cases:
        r['different_output_hashes']=[k for k,v in sorted(r['output_sha256'].items())if current_sha[k]!=v]
        r['wild_under_one_percent_of_same_name_complete']=[k for k,v in sorted(r['wild'].items())if v*100<per[k]['cuts']['complete']]
    prior=cases[1]
    excluded=prior['outer']-prior['actual_wild']
    hashcost=max(new['scans'][p]['instructions'] for p in ('compact-held-0','compact-held-1'))
    cutoff=new['source_cut_sums']
    costs={'paths_compact_sha':cutoff['paths']+hashcost, 'sections_compact_sha':cutoff['sections']+hashcost,
           'mapped_blake3_every':cutoff['hash'], 'paths_each_sha':cutoff['paths']+new['scans']['all-occurrences']['instructions']}
    with zipfile.ZipFile(current) as z:
        prefix='phase-price/unique-held/'
        pairs=zip(z.read(prefix+'paths.nul').decode().split('\0'),z.read(prefix+'observed.txt').decode().splitlines())
        rows={p:line.split()for p,line in pairs}
        nids=len({tuple(row[3:5])for row in rows.values()})
        primary=z.read('phase-price/e2e-positive/paths.nul').decode().split('\0')[:-1]
        denies={p:int(row[1])for p,row in rows.items()if row[2]=='13'}
        assert set(denies)<=set(primary) and len(denies)==19 and nids==3465
        assert len({r[2]for r in rows.values()})==2
        folders=('old-verdict','edit-verdict','observed-verdict','old-on-new-verdict')
        behavior={}
        for folder in folders:
            names=z.read(folder+'/test-list');stdout=z.read(folder+'/stdout')
            assert hashlib.sha256(names).hexdigest()==reopen.LIST
            ok=folder!='old-on-new-verdict'
            assert (b'1 passed;' if ok else b'1 failed;')in stdout
            behavior[folder]={'inventory_sha256':reopen.LIST,'stdout_sha256':hashlib.sha256(stdout).hexdigest(),'passed':ok}
        for stage,sha in [('ordinary-old',reopen.OLD),('ordinary-edit',reopen.NEW),('current-observed',reopen.NEW)]:
            inv=reopen.doc(z,stage+'/inventory.json.gz');assert len(inv['executables'])==102 and inv['executables'][inv['binary']]['elf']['sha256']==sha
        for stage in ('src-shadow','stock','src-final-repair','src-four-byte','src-malformed'):
            res=json.loads(z.read(stage+'/link-result.json'))
            if stage=='src-four-byte':assert json.loads(z.read(stage+'/runtime.json'))['returncode']==83 and res['elf']['sha256']!=reopen.NEW
            elif stage=='src-malformed':assert res['returncode']!=0 and res['elf']is None
            else:assert res['returncode']==0 and res['elf']['sha256']==reopen.NEW
            behavior[stage]=res
    sums={}
    for k,v in costs.items():
        a=excluded+v; b=a+new['all_output_validation']
        sums[k]={'retained_with_cut':a,'including_output_sha':b,'headroom_to_half_with_output_sha':prior['outer']/2-b}
    result={'separate_boot_sensitivity':sums,'conserved_reference_outer_minus_wild':excluded,'cases':cases,
            'actual_held_open_identities':nids,'refused_leases':denies,'refused_lease_bytes':sum(denies.values()),
            'full_ordinary_behavior':behavior,'admitted_new_outer_minus_wild':False}
    Path(outfile).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')

if __name__=='__main__':
    main(*sys.argv[1:])
