"""Recover the signed native derive calls and late query-provider counts from original bytes."""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify import records


def evidence(result,crate):
    sys.path.insert(0,str(result));import verify_recovery
    files=verify_recovery.load(next(result.glob('*.xz')))
    profiles=[]
    for phase,pid,_ in json.loads(files['ron-profiles/visits.json']):
        start='ron-profiles/'+pid+'/'
        value,=[v for n,v in files.items() if n.startswith(start) and n.endswith('.mm_profdata')]
        q=collections.Counter(); allk=collections.Counter(); calls=collections.Counter()
        args=json.loads(files[start+'invocation.json'])['args']
        for kind,items,_ in records(value):
            allk[kind]+=1
            if kind=='Query':q[items[0]]+=1
            if kind=='GenericActivity' and items[0] in ('expand_proc_macro','expand_derive_proc_macro_outer'):
                assert len(items)==1;calls[items[0]]+=1
        native=[a.split('=',1)[0] for i,a in enumerate(args) if i and args[i-1]=='--extern' and a.endswith('.so')]
        assert native==['serde_derive'] and not any('incremental=' in a for a in args)
        assert q['typeck_root']==945 and q['mir_borrowck']==913 and allk['Query']==126211
        assert allk['IncrementalLoadResult']==0 and allk['QueryCacheHitCount']==78175
        assert calls=={'expand_derive_proc_macro_outer':16,'expand_proc_macro':16}
        profiles.append(dict(phase=phase, profile=hashlib.sha256(value).hexdigest(),typeck_root=q['typeck_root'],mir_borrowck=q['mir_borrowck'],
                             observed_events=allk,derive_calls=calls,only_native_macro_extern=native))
    assert hashlib.sha256(crate.read_bytes()).hexdigest()=='fd490c5b18261893f14449cbd28cb9c0b637aebf161cd77900bfdedaff21ec32'
    sites={'src/extensions.rs':[5],'src/options.rs':[38],'src/ser/mod.rs':[80],'src/ser/path_meta.rs':[112,241],
           'src/value/map.rs':[18],'src/de/mod.rs':[1051,1055,1110,1113]}; src=[]
    with tarfile.open(crate) as t:
        revision=json.load(t.extractfile('ron-0.12.0/.cargo_vcs_info.json'))['git']['sha1'];assert revision=='c6a8cff1eff986cc1ad9b026e838335187d411f0'
        for name,positions in sites.items():
            lines=t.extractfile('ron-0.12.0/'+name).read().decode().splitlines()
            for i in positions:
                attribute=lines[i-1].strip(); assert attribute.startswith('#[derive(') and 'Deserialize' in attribute
                src.append({'file':name,'line':i,'calls':['Deserialize']+(['Serialize'] if 'Serialize' in attribute else []),'source':attribute})
    assert sum(len(r['calls']) for r in src)==16
    with zipfile.ZipFile(result.parent/'primary.zip') as z:
        pmu=json.loads(z.read('first-unchanged/pmu.json')); whole=pmu['whole'][1];selected=pmu['selected'][1]
        cost=whole/2;new=cost-(whole-selected)
        assert (whole,selected)==(2541466454,1756795215)
    return {'signed_profiles':profiles,'source_revision':revision,'source_derived_sites':src,
            'scope':'The original native profiler did not record per-call function arguments; only Serde was a native macro extern. Source sites are independently inferred.',
            'instructions':{'whole':whole,'ron':selected,'other':whole-selected,'allowable_ron_if_others_fixed':new,
                            'fraction_ron_required_saving':1-new/selected}}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('original_result',type=Path);p.add_argument('ron_crate',type=Path)
    args=p.parse_args();print(json.dumps(evidence(args.original_result,args.ron_crate),sort_keys=True,indent=2))
