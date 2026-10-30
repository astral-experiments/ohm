"""Verify the native accounting and dispositions in the compressed public projection."""
import gzip,hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parent
def h(b):return hashlib.sha256(b).hexdigest()
def checks(x):
    refs=set(('signed','classic','aware'))
    assert x['run']==41110754345 and x['archive']=={'id':13005066644,'bytes':151308988,'sha256':'21fa01ccb032337607407bb16b92161f5f04943b5b60c1d2e7521fb42b0499c5','members':14658}
    assert x['integrated']=={'source':'fd55a13d0220748794ba3c7c9556ef8ceed8591f','sha':'9f09941432a849b13ee6177c2f4b0f35f5d9c350e518688d64325ce513ec532d'} and x['rust']['source']=='01dccb633d12cc0124c06e02c858aff74af1dcea'
    assert set(x['versioned'])==set(x['old'])==set(x['registry'])==refs and len({x['versioned'][q]['code_signing'] for q in refs})==3
    total=0
    for role in refs:
        v=x['versioned'][role];assert v['commands']==392 and not v['required_failures'] and v['disabled_unwatched']==12;total+=v['commands']
        assert v['rust_rows']==152 and v['distinct_complete_programs']>=140 and v['actual_receipt_hits']==(7 if role=='aware' else 0)
        o=x['old'][role];assert len(o)==44 and len([r for r in o if r['placement']=='direct'])==22;total+=2*len(o)
        stale=set()
        for row in o:
            w,e=row['warm'],row['clean']
            assert e['code'] in (0,101) and ((e['code']==101)==(e['answer'] is None))
            if e['code']==101:assert e['raw'] is None
            else:assert e['answer'][0] in (17,29) and len(e['raw'])==64
            if (w['code'],w['answer'])!=(e['code'],e['answer']):
                assert row['policy']=='unwatched' and w['full']==[] and w['links']==0 and w['code']==0
                stale.add((row['placement'],row['phase']))
            elif w['code']==0:assert row['same_native_product']
        wanted={(p,q) for p in ('direct','library') for q in ('higher-no-rust','malformed-no-rust','missing-no-rust')} if role!='classic' else set()
        assert stale==wanted
        for stage,counts in x['registry'][role].items():
            expect=1 if stage in ('cold','empty') or role!='aware' else 0
            assert counts=={'zmij':expect,'zlib_rs':expect};total+=1
    for a,b in zip(x['old']['signed'],x['old']['aware']):
        assert (a['placement'],a['policy'],a['phase'],a['warm']['code'],a['warm']['answer'])==(b['placement'],b['policy'],b['phase'],b['warm']['code'],b['warm']['answer'])
    assert sum(x['transfers'].values())==72 and x['literal_v1']==x['literal_v2']==36
    total+=sum(x['transfers'].values())+x['literal_v1']+x['literal_v2']
    assert x['observations']==total==1596 and x['ordinary_ty_clocks']==0
    assert len(x['raw_projection_hashes'])==6 and all(len(q)==64 for q in x['raw_projection_hashes'].values())
    return total
if __name__=='__main__':
    for line in (root/'SHA256SUMS').read_text().splitlines():
        dg,name=line.split('  ',1);assert h((root/name).read_bytes())==dg,name
    x=json.loads(gzip.decompress((root/'observations.json.gz').read_bytes()));print(f'Verified {checks(x):,} native observations and zero ty timing samples.')
