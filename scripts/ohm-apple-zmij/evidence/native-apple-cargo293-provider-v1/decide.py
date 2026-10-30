"""Separate a fresh Cargo decision, first receipt publication, changed inputs and a true linker receipt hit."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

STEPS = ('lower','unchanged-lower','higher-no-rust','higher-rust-edit','malformed-no-rust','malformed-rust-edit','repair-before-missing','missing-no-rust','missing-rust-edit','restored-rust-edit','restored-unchanged')
STAMP = ('original-higher','repeat-higher','overwrite-same-stamp','repeat-replacement','restore-same-stamp')
RUFF = ('cold','edit','repeat-1','repeat-2','invalid','repair')

def phase(v, prior, same_input):
    old=set(prior['seals']) if prior else set()
    new=set(v['seals'])
    base={'full':v['full'],'link_only':v['link_only'],'final_ld':v.get('final',v['ld']),
          'driver':v['driver_processes'],'stock_ld_reports':v['dependency_info'],'prior_seals':len(old),
          'current_seals':len(new),'same_input':same_input,'raw':v['raw'],'status':v['status'],
          'answer':v.get('answer',v.get('tests'))}
    if v['driver_processes'] and not v['ld'] and v['status']==0 and v['raw'] in v['receipt_products'] and old & new:
        base['mechanism']='reused-existing-seal'
    elif not v['full'] and not v['link_only'] and not v['ld'] and not v['driver_processes']:
        base['mechanism']='cargo-fresh'
    elif v['dependency_info'] and new and not old:
        base['mechanism']='stock-link-published-first-seal'
    elif v['dependency_info'] and new and old:
        base['mechanism']='stock-link-with-prior-seal'
    elif v['dependency_info'] and v['status']:
        base['mechanism']='stock-link-returned-error'
    elif not v['driver_processes']:
        base['mechanism']='without-link-driver'
    else:
        base['mechanism']='link-driver-without-proven-reuse'
    return base

def main(observation):
    d=json.loads(gzip.decompress(observation.read_bytes()));cases={};preserved={};rt={}
    for name,ds in d['provider'].items():
        sequence=STAMP if 'stamp-' in name else STEPS
        assert set(ds)==set(sequence),(name,set(ds)^set(sequence))
        rows={};prior=None
        for stage in sequence:
            e=ds[stage];w=e['warm'];ref=e['empty']
            assert e['same_verdict']==((w['answer'],w['status'])==(ref['answer'],ref['status']))
            same=None if prior is None else (e['input'],e['trigger'])==(prior['input'],prior['trigger'])
            v=phase(w,prior and prior['warm'],same)
            v.update(native_clean=e['same_verdict'],whole_clean=e['same_raw'],empty=ref['answer'] if not ref['status'] else ref['status'],
                     witness=[w['streams']['native_events'],ref['streams']['native_events']])
            if 'bundled' in w:v['warm_embedded']=[b['providers'] for b in w['bundled']];v['empty_embedded']=[b['providers'] for b in ref['bundled']]
            rows[stage]=v;prior=e
        cases[name]=rows
        preserved[name]={'different_native_verdict':[s for s,r in rows.items() if not r['native_clean']],
                         'different_working_raw_with_equal_verdict':[s for s,r in rows.items() if r['native_clean'] and r['whole_clean'] is False],
                         'settled_no_input_change':[(s,r['mechanism']) for s,r in rows.items() if r['same_input'] and r['prior_seals']>0],
                         'first_no_input_change':[(s,r['mechanism']) for s,r in rows.items() if r['same_input'] and r['prior_seals']==0]}
    for name in d['summary']['ruff_clean_comparisons']:
        rows={};pre=None
        for stage in RUFF:
            key='ruff-293/'+name+'/visit/'+stage;r=d['ruff'][key];p=phase(r,pre,stage.startswith('repeat'));rows[stage]=p;pre=r
            p['empty_comparison']=d['summary']['ruff_clean_comparisons'][name][stage]
        rt[name]=rows
    return dict(origin=d['summary']['zip_sha256'],totals={'provider':d['summary']['commands'],'ruff':d['summary']['ruff_commands']},
                hosts=d['summary']['host'],cases=cases,classification=preserved,ruff=rt)

def write(path,data):
    if path.exists():assert path.read_bytes()==data,path
    else:path.write_bytes(data)

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('observations',type=Path);a.add_argument('output',type=Path);v=a.parse_args()
    out=main(v.observations);data=(json.dumps(out,sort_keys=True,separators=(',',':'))+'\n').encode();write(v.output,data);print(hashlib.sha256(data).hexdigest(),v.output)
