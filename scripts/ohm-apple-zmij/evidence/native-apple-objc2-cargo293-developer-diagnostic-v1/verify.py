#!/usr/bin/env python3
"""Verify the portable objc2 provider/work records and recompute all available paired statistics offline."""
import gzip,hashlib,itertools,json,math,statistics
from pathlib import Path
D=Path(__file__).resolve().parent
sha=lambda b:hashlib.sha256(b).hexdigest()
get=lambda n:json.loads((D/n).read_bytes())
inflate=lambda n:json.loads(gzip.decompress((D/n).read_bytes()))
P='82911b516fb35608fd70ada4deb6f8429277f410';C='7924254acf6ee5a17473ac47dfb33b5842d72005';R='735e1528ed741015c57676dccf05dbdc0ff7bed1'
A='4710e1aa962b13720cf64aa84eb279c5333896d7';B='915bb2b4bf9ae7eee47cf55646bbfebae254a23b'
EXPECTED=[('lower',17,7),('unchanged-lower',17,7),('higher-no-rust',29,7),('higher-rust-edit',29,11),('malformed-no-rust',None,11),('malformed-rust-edit',None,13),('repair-before-missing',29,13),('missing-no-rust',None,13),('missing-rust-edit',None,15),('restored-rust-edit',17,19),('restored-unchanged',17,19)]
STAMP=[('original-higher',29,7),('repeat-higher',29,7),('overwrite-same-stamp',17,7),('repeat-replacement',17,7),('restore-same-stamp',29,7)]
DIAGNOSTIC={'higher-no-rust','malformed-no-rust','missing-no-rust','repair-before-missing'}

def same_image(a,b):
    return all(a[k]==b[k] for k in ("norm","output_sha","modules_sha","module_count"))

def same_result(a,b):
    return ({k:v for k,v in a['product'].items() if k!='raw'}=={k:v for k,v in b['product'].items() if k!='raw'}
            and same_image(a['image_witness'],b['image_witness']))

def provider():
    root=get('provider.json');rows=inflate('provider-observations.json.gz')
    assert root['sources']['cargo_source']==R and [root['sources']['rust'][role]['source'] for role in 'PC']==[P,C]
    assert root['sources']['rust']['P']['driver']!=root['sources']['rust']['C']['driver'] and len(rows)==20
    critical=[];different=[];count=0;genuine=0;by_role={}
    for name,phases in rows.items():
        role,placement,policy,mode=name.split('-');ref=STAMP if 'stamp' in role else EXPECTED
        assert set(phases)=={x[0] for x in ref} and placement in ('direct','library')
        problems=[];off=[];prev=None;by_role.setdefault(role[0],{'critical':0,'off':0})
        for s,val,rust in ref:
            v=phases[s];w,e=v['warm'],v['empty'];count+=2
            assert v['trigger']==sha(('#[inline(never)] pub fn value()->i32 {'+str(rust)+'}\n').encode())
            actual=(e['status'],e['answer']);needed=(0,[val,rust]) if val else (101,None)
            assert actual==needed
            equal=actual==(w['status'],w['answer']);raw=(w['raw']==e['raw']) if w['raw'] and e['raw'] else None
            assert equal==v['same_verdict'] and raw==v['same_raw']
            for q in (w,e):
                if mode=='default' and q['raw']:
                    wq=q['image_witness']
                    assert wq['raw']==q['raw'] and wq['module_count']>0 and wq['code_pages']>0
                    assert wq['source'] in ('kernel-xcode-ld+rustc-recipe','unchanged-raw-from-prior-physical-link') and wq['argv']
            qualified=(same_image(w['image_witness'],e['image_witness']) if mode=='default' and w['raw'] and e['raw'] else raw)
            assert qualified==v['same_checked_image']
            assert w['cargo_cdhash']==e['cargo_cdhash']==root['sources']['kernel_cargo_cdhash']
            outcome=root['work'][name][s]
            assert [w['full'],w['link_only'],w['final']]==[outcome[k] for k in ('full','link_only','final_ld')]
            hit=bool(prev and w['status']==0 and w['driver_processes'] and not w['ld'] and w['raw'] in w['receipt_products'] and set(w['seals'])&set(prev['seals']))
            assert hit==outcome['existing_seal_hit'];genuine+=hit;prev=w
            if not equal or v['same_checked_image'] is False:
                if mode=='default' or policy=='declared' or s not in DIAGNOSTIC:problems.append(s);by_role[role[0]]['critical']+=1
                else:off.append(s);by_role[role[0]]['off']+=1
            stamp=v.get('stamp')
            if stamp:assert stamp['size']>0 and stamp['inode']>0
        assert root['issues'][name]=={'default_declared_or_rust':problems,'off_unwatched':off}
        critical += [(name,k) for k in problems];different +=[(name,k) for k in off]
    assert count==root['commands']==392 and root['eligible']==(not critical) and genuine==root['hits']
    return {'provider_commands':count,'incorrect_required':critical,'diagnostic_off_differences':len(different),'qualified':root['eligible'],'independent_hits':genuine,'roles':by_role}

def summary():
    for row in (D/'SHA256SUMS').read_text().splitlines():
        s,p=row.split('  ',1);assert '/' not in p and sha((D/p).read_bytes())==s,p
    result=provider()
    source=inflate('application.json.gz')
    assert source['source']['cargo_source']==R
    assert [source['source']['rust'][r]['source'] for r in 'PC']==[P,C]
    rows=source['rows'];assert len(rows)==32
    references={}
    for order in ['PC','CP']:
        for r in order:
            path='objc2-cli/'+order+'/'+r+'/'
            assert not set(['CI','GITHUB_ACTIONS','TF_BUILD','CARGO_INCREMENTAL','RUSTFLAGS'])&set(source['environment'][order+'/'+r])
            for tag,rev in [('old',A),('new',B)]:
                q=rows[path+'clean-'+tag+'/clean'];ref=q['product'];obs=q['observation']
                assert ref['native']['raw'] in source['images'] and ref['native']['module_count']>0 and ref['native']['source']=='kernel-xcode-ld+rustc-recipe'
                assert sum(v['bin'] for v in obs['root_emitters'])==1 and all(v['incremental_sha256'] and len(v['incremental_sha256'])==64 and v['sessions'] for v in obs['root_emitters'])
                references[order,r,rev]=ref
            for step in ('cold','edit','repeat-1','repeat-2','invalid','repair'):
                q=rows[path+'visits/'+step];obs=q['observation'];assert len(obs['cargo_cdhash'])>0
                assert obs['objc2']==obs['full'].count('objc2')
                if step=='invalid':assert q['product'] is None and obs['status']==101 and obs['final_links']==0;continue
                rev=A if step=='cold' else B;p0=q['product'];ref=references[order,r,rev]
                assert obs['status']==0 and p0['outcome']==ref['outcome'] and p0['outcome']['exit']==(0 if rev==A else 1)
                assert same_image(p0['native'],ref['native']) and p0['native']['raw'] in source['images']
                if step in ('edit','repeat-1','repeat-2'):assert obs['objc2']==int(r=='P')
        for rev in (A,B):
            j,k=[references[order,r,rev] for r in 'PC'];assert j['outcome']==k['outcome'] and j['native']['cross']==k['native']['cross'] and j['native']['modules_sha']==k['native']['modules_sha']
    result['native_Cargo_commands']=len(rows)
    design='objc2 ty CLI / local incremental, entire ty CLI with bound native inputs on exact Cargo #293 / inclusive 12 v3'
    options=list(itertools.combinations(range(12),6))
    alloc=int(sha(' '.join((design,P,C,A,B,R)).encode()),16)%924;assert alloc==197
    for stage in ('screen','confirmation'):
        data=inflate(stage+'.json.gz');o=data['order'];expected=['PC','CP'] if stage=='screen' else ['PC' if k in options[alloc] else 'CP' for k in range(12)]
        assert o==expected and len(data['typed_products'])==len(o)*8 and len(data['raw_clocks'])==6*len(o)
        roster={s['request'] for s in data['typed_products']};assert roster
        for s in data['typed_products']:
            ref=references['PC',s['role'],A if s['phase']=='cold' else B];p=ref['native']
            assert s['raw'] in data['images'] and s['norm']==p['norm'] and s['modules']==p['modules_sha'] and s['complete_bytes']==data['images'][s['raw']]['bytes']
            assert s['units']==(353 if s['phase']=='cold' else 354) and s['request'] in roster
        assert len(data['cache'])>=len(o)*2 and all(s['objects'] and s['graph'] and len(s['work_products'])==64 for s in data['cache'])
        clocks=data['raw_clocks'];last=-1
        for q in clocks:
            assert q['start']>last and q['end']-q['start']==q['ns'] and q['ns']>0
            last=q['end']
            assert len(q['time_l'])==len(q['stdout'])==len(q['stderr'])==64
        for tag,rep in data['scores'].items():
            tags=['edit','repeat-1'] if tag=='edit+repeat-1' else [tag]
            pc=[[sum(q['ns'] for q in clocks if q['pair']==i and q['role']==r and q['phase'] in tags) for r in 'PC'] for i in range(1,len(o)+1)]
            ratios=[x/y for x,y in pc];assert pc==rep['pairs'] and statistics.median(ratios)==rep['paired']
            assert [statistics.median(a)/1e9 for a in zip(*pc)]==[rep['median_P'],rep['median_C']]
            if len(o)==12:
                assert rep['ci']==[sorted(ratios)[2],sorted(ratios)[9]]
                vals=[math.log(x/2) for x in ratios];sgn=[v*(1 if roles=='PC' else -1) for roles,v in zip(o,vals)]
                p=sum(sum(x if i in s else -x for i,x in enumerate(sgn))>=sum(vals)-1.2e-11 for s in options)/924
                assert rep['p']==p
        first=data['scores']['repeat-1'];assert data['twofold_primary']==(len(o)==12 and first['ci'][0]>2 and first['p']<=.05)
        result[stage]={k:first[k] for k in ('median_P','median_C','paired','ci','p') if k in first}
    print(json.dumps(result,indent=2))
if __name__=='__main__':summary()
