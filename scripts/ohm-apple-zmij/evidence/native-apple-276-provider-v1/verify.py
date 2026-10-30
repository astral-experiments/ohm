"""Verify the compact observations or, with --raw, independently rederive them from the original CI ZIP."""
import argparse
import collections
import gzip
import json
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from reopen import C,CARGO,P,PLAN,QA,RELEASE,STEPS,UNWATCHED,WORKER,filehash,require,run,sha,summarize

def canonical_report(v):
    value=json.loads(json.dumps(v))
    for k in ('unexpected','unwatched_mismatches','differential','declared_failed'):
        value[k].sort()
    return value

def decode(d):
    require(d['schema']==1 and d['part']=='final','wrong schema')
    require(d['source']['P']==P and d['source']['C']==C and d['qa_head']==QA,'wrong source')
    require((d['source']['cargo'],d['source']['archive'])==(CARGO,RELEASE),'wrong release')
    require(d['protocol']=={'worker':WORKER,'plan':PLAN},'wrong protocol')
    require(len(d['source']['driver'])==2 and len(set(d['source']['driver'].values()))==2,'same driver')
    require(d['source']['identical_runtime']>=2000 and d['workflow']==41060913032,'wrong toolchain')
    phases=[t[0] for t in STEPS]
    observed_counts=collections.Counter()
    for key,case in d['cases'].items():
        role,where,rule,mode=key.split('-')
        assert role in 'PC' and where in ('direct','library') and rule in ('unwatched','declared') and mode in ('default','off')
        assert d['driver_ids'][key]['sha256']==d['source']['driver'][role]
        assert set(case)==set(phases)
        for phase,native,rust in STEPS:
            want=[101,None] if native in ('malformed','missing') else [0,[17 if native=='lower' else 29,rust]]
            q=case[phase];w,e=q['warm'],q['empty']
            assert q['want']==[e['status'],e['answer']]==want
            for j,v in [('warm',w),('empty',e)]:
                assert set(v['streams'])=={'stdout','stderr','native_events'} and all(re.fullmatch('[0-9a-f]{64}',s) for s in v['streams'].values())
                assert v['ld']>=len(v['final']) and sorted(v['cached'])==v['cached'] and sorted(v['full'])==v['full']
                assert all(t['linker_sha256']==d['source']['stock_xcode_ld'] for t in v['final'])
                assert len({t['pid'] for t in v['final']})==len(v['final'])
                for link in v['final']:
                    assert link['pid']>0 and link['ppid']>0 and link['argv'] and link['output_name']
                if v['status']==0:
                    assert v['answer'][0] in (17,29) and v['answer'][1] in (7,11,13,15,19)
                    assert d['images'][v['image']]['raw']==v['image']
                    assert v['error'] is None
                else:
                    assert v['status']==101 and not v['image'] and not v['answer']
                    assert v['error']['archive'] or v['error']['symbol']
                observed_counts[v['status']]+=1
            eq=(w['image']==e['image']) if w['image'] and e['image'] else None
            assert eq==q['same_raw']
            eq=(d['images'][w['image']]['text']==d['images'][e['image']]['text']) if w['image'] and e['image'] else None
            assert eq==q['same_text']
    assert len(d['cases'])==16 and sum(observed_counts.values())==352
    rep=summarize(d)
    return rep

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw',type=Path,help='original provider qualification ZIP');a=p.parse_args()
    root=Path(__file__).resolve().parent
    for line in (root/'SHA256SUMS').read_text().splitlines():
        digest,relative=line.split('  ',1)
        assert re.fullmatch(r'[a-zA-Z0-9_.-]+',relative) and filehash(root/relative)==digest,relative
    d=json.loads(gzip.decompress((root/'final-observation.json.gz').read_bytes()))
    s=decode(d);original=json.loads((root/'final-readback.json').read_text())
    assert canonical_report(s)==canonical_report(original)
    if a.raw:
        require(filehash(a.raw)==d['raw_sha256'],'wrong original ZIP digest')
        data,summary=run(a.raw,'final')
        require(data==d and canonical_report(summary)==canonical_report(original),'original disagrees with projection')
    print(json.dumps({k:s[k] for k in ('commands','cases','native_programs','true_cargo_101','actual_full_rustcs','actual_cached_rustcs','actual_stock_ld','actual_provider_ld','complete_image_comparisons','differential','unexpected')},sort_keys=True))
