"""Recompute the provider, genuine missing filename, upgrade and compiler assembly verdicts."""
from pathlib import Path
import copy
import hashlib
import json
import re
HERE=Path(__file__).resolve().parent
load=lambda name:json.loads((HERE/name).read_bytes())
hex64=lambda v:bool(re.fullmatch(r'[a-f0-9]{64}',v))

def providers(records):
    commands={}
    for mode,track in records.items():
        histories=track['histories']
        migration=mode.startswith('migrate-')
        assert len(histories)==(2 if migration or mode=='legacy-writer' else 6)
        commands[mode]=sum(len(r['phases']) for r in histories.values())
        assert commands[mode]==track['commands'] and hex64(track['terminal']) and hex64(track['raw_reader'])
        for name,tests in histories.items():
            assert name.startswith(mode+'-')
            rows=tests['phases']
            expected={'trained-repeat':'17 7','upgrade-higher':'29 7','upgrade-unchanged':'29 7','upgrade-restamped':'29 7','downgrade-unchanged':'29 7','downgrade-malformed':None,'upgrade-malformed':None,'upgrade-missing':None,'upgrade-repaired':'17 11','downgrade-repaired':'17 11'} if migration else {'higher':'29 7','removed-higher':'17 7','same-inode-value':'29 7','real-Rust-edit':'29 11','same-inode-malformed':None,'repaired-edit':'29 13','missing':None,'restored-edit':'17 19','restored-repeat':'17 19'}
            assert hex64(tests['roots' if migration else 'mutations'])
            assert rows['cold-lower'][0:2]==[0,'17 7']
            for phase,answer in expected.items():
                same=rows[phase];empty=rows['empty-'+('restored-edit' if phase=='restored-repeat' else phase)]
                assert same[:6]==empty[:6] and same[:2]==[101 if answer is None else 0,answer]
                if answer is None:
                    assert same[2] is None
                    assert same[3]==([] if 'missing' in phase else ['late'])
                    if 'missing' in phase:assert same[4] and same[5]
                else:
                    assert hex64(same[2]) and track['unique_successful_ELF_sizes'][same[2]]>0
                    assert same[3]==(['early'] if phase in ('higher','upgrade-higher','upgrade-unchanged') else ['late'])
                for v in (same,empty):
                    assert v[6]>=1 and v[7]['all_ld']>=v[6] and v[7]['collect2'] and v[7]['cross_gcc'] and hex64(v[8])
            if mode in ('signed','classic'):assert rows['restored-repeat'][7]['compile']>=1
    assert commands=={'signed':108,'classic':108,'aware':108,'legacy-writer':36,'migrate-signed':42,'migrate-classic':42}
    return sum(commands.values())

def main():
    for l in (HERE/'SHA256SUMS').read_text().splitlines():
        h,n=l.split('  ',1);assert hashlib.sha256((HERE/n).read_bytes()).hexdigest()==h
    p=load('providers.json');assert providers(p)==444
    altered=copy.deepcopy(p)
    r=altered['aware']['histories']['aware-undeclared-library']['phases']['same-inode-malformed']
    r[:3]=[0,'29 11','0'*64]
    try:providers(altered)
    except AssertionError:pass
    else:raise AssertionError('admitted false native success')
    direct=load('direct.json')
    for role,cases in direct['checks'].items():
        assert len(cases)==29
        for name,(exitcode,mark,out,err) in cases.items():
            assert hex64(out) and hex64(err) and exitcode==int(name=='bundled' or name.startswith('missing-'))
            allowed=name in {'ordinary','general_only','vector_only','compact_input','compact_copy','external'}
            assert mark==('/dev/null/ohm-recheck-dependent-links'+('-v2' if role=='C' else '') if allowed else '/dev/null/ohm-untracked-relink-inputs')
    assert set(direct['checks'])=={'P','C'}
    named=load('named.json')['checks']
    assert set(named)=={'none','v1','v2','both'}
    for mode,cases in named.items():
        assert set(cases)=={'cold','repeat','empty'} and len({v['ELF'] for v in cases.values()})==1
        assert all(hex64(v['kernel']) and hex64(v['ELF']) for v in cases.values())
        assert (cases['repeat']['producer_full']>0)==(mode!='none')
    print('444 provider and migration Cargo commands, 12 named-input Cargo commands, 58 direct rustcs; all independent controls passed.')
if __name__=='__main__':main()
