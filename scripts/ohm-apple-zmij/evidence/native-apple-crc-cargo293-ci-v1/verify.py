#!/usr/bin/env python3
"""Verify the portable CRC provider/work records and recompute all available paired statistics offline."""
import gzip,hashlib,itertools,json,math,statistics
from pathlib import Path
D=Path(__file__).resolve().parent
sha=lambda b:hashlib.sha256(b).hexdigest()
get=lambda n:json.loads((D/n).read_bytes())
inflate=lambda n:json.loads(gzip.decompress((D/n).read_bytes()))
P='444c0273a2e2bc0b161e988d43c882349bc2d7a6';C='82911b516fb35608fd70ada4deb6f8429277f410';R='735e1528ed741015c57676dccf05dbdc0ff7bed1'
A='ccba26cc3af909b7f19060f48f53daeab5070f9d';B='d8dac4cb576bd091a8b6cdc60a65c770ea75a96e'
EXPECTED=[('lower',17,7),('unchanged-lower',17,7),('higher-no-rust',29,7),('higher-rust-edit',29,11),('malformed-no-rust',None,11),('malformed-rust-edit',None,13),('repair-before-missing',29,13),('missing-no-rust',None,13),('missing-rust-edit',None,15),('restored-rust-edit',17,19),('restored-unchanged',17,19)]
STAMP=[('original-higher',29,7),('repeat-higher',29,7),('overwrite-same-stamp',17,7),('repeat-replacement',17,7),('restore-same-stamp',29,7)]
DIAGNOSTIC={'higher-no-rust','malformed-no-rust','missing-no-rust','repair-before-missing'}

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
            assert w['cargo_cdhash']==e['cargo_cdhash']==root['sources']['kernel_cargo_cdhash']
            outcome=root['work'][name][s]
            assert [w['full'],w['link_only'],w['final']]==[outcome[k] for k in ('full','link_only','final_ld')]
            hit=bool(prev and w['status']==0 and w['driver_processes'] and not w['ld'] and w['raw'] in w['receipt_products'] and set(w['seals'])&set(prev['seals']))
            assert hit==outcome['existing_seal_hit'];genuine+=hit;prev=w
            if not equal or raw is False:
                if mode=='default' or policy=='declared' or s not in DIAGNOSTIC:problems.append(s);by_role[role[0]]['critical']+=1
                else:off.append(s);by_role[role[0]]['off']+=1
            stamp=v.get('stamp')
            if stamp:assert stamp['size']>0 and stamp['inode']>0
        assert root['issues'][name]=={'default_declared_or_rust':problems,'off_unwatched':off}
        critical += [(name,k) for k in problems];different +=[(name,k) for k in off]
    assert count==root['commands']==392 and root['eligible']==(not critical) and genuine==root['hits']
    return {'provider_commands':count,'incorrect_required':critical,'diagnostic_off_differences':len(different),'qualified':root['eligible'],'independent_hits':genuine,'roles':by_role}

def stats(mode,raw):
    orders=raw['order'];n=len(orders);subsets=list(itertools.combinations(range(12),6))
    pick=int(sha(('crc typeshed on exact 735e1528, inclusive complete-compile 12 v2 / '+P+C+A+B).encode()),16)%len(subsets)
    assert pick==23 and orders==(['PC','CP'] if mode=='screen' else ['PC' if i in subsets[pick] else 'CP' for i in range(12)])
    phases=raw['phases'];pairs=phases['repeat-1']['raw_ns']
    assert len(pairs)==n and len(raw['disk'])==n and min(v for x in raw['disk'] for v in x)>0
    assert phases['edit+repeat-1']['raw_ns']==[[a[0]+b[0],a[1]+b[1]] for a,b in zip(phases['edit']['raw_ns'],pairs)]
    clock_rows=raw['raw_clocks'];assert len(clock_rows)==n*6
    last=-1
    for index,order in enumerate(orders,1):
        for role in order:
            for step in ('edit','repeat-1','repeat-2'):
                record,=[r for r in clock_rows if (r['pair'],r['role'],r['step'])==(index,role,step)]
                ri='PC'.index(role)
                assert last<record['start_ns'] and record['stop_ns']-record['start_ns']==record['ns']==phases[step]['raw_ns'][index-1][ri]
                assert raw['cpu'][step][index-1][ri]==[record['user'],record['system']]
                assert all(len(record[k])==64 for k in ('stdout','stderr','time_l','program','zip'))
                last=record['stop_ns']
    for s,v in phases.items():
        counts=v['raw_ns'];ratios=[a/b for a,b in counts];assert min(ratios)==v['min'] and max(ratios)==v['max'] and statistics.median(ratios)==v['paired']
        assert [statistics.median(a)/1e9 for a in zip(*counts)]==v['seconds']
        if n==12:
            assert [sorted(ratios)[2],sorted(ratios)[9]]==v['ci']
            observed=[math.log(a/2) for a in ratios]; seq=[x if order=='PC' else -x for x,order in zip(observed,orders)]
            assert sum(sum((1 if i in chosen else -1)*x for i,x in enumerate(seq))>=sum(observed)-1.2e-11 for chosen in subsets)/924==v['p_2x']
    x=phases['repeat-1'];assert raw['passed']==(x['min']>2 if n==2 else x['ci'][0]>2 and x['p_2x']<=0.05)
    return {k:x[k] for k in ('seconds','paired','min','max','ci','p_2x') if k in x}

def main():
    for line in (D/'SHA256SUMS').read_text().splitlines():
        dig,name=line.split('  ',1);assert '/' not in name and sha((D/name).read_bytes())==dig,name
    outcome=provider()
    crc=inflate('ruff-observations.json.gz');cl=crc['clocks'];checks=crc['structural'];outcome['stages']=crc['terminal_gates']
    roles='PC'
    for order,phases in checks.items():
        for step,green in phases.items():
            p,c=[crc['physical_native'][f'{order}/{r}/visits/{step}'] for r in roles]
            assert green==bool(p['full']==['build_script_build','ty_vendored','zlib_rs','zlib_rs'] and c['full']==['build_script_build','ty_vendored']
                    and len(p['markers'])==len(c['markers'])==2 and all(x['hard'] for x in p['markers']) and all(not x['hard'] and x['recheck'] for x in c['markers'])
                    and all(not r['link_only'] and r['ld']==2 and r['root_ld']==r['build_script_ld']==r['driver_processes']==1 and r['product']['raw'] in r['receipt_products'] for r in (p,c)))
    refs={}
    for role in 'PC':
        reference={tag:crc['physical_native'][f'PC/{role}/clean-{tag}/clean']['product'] for tag in ('old','new')}
        assert reference['old']['raw']!=reference['new']['raw'] and reference['old']['zip_sha256']!=reference['new']['zip_sha256']
        for tag,product in reference.items():
            assert product['raw'] in crc['images'] and product['zip_sha256'] in crc['zips']
        for order in ('PC','CP'):
            for tag,product in reference.items():
                assert crc['physical_native'][f'{order}/{role}/clean-{tag}/clean']['product']==product
            for step in ('cold','edit','repeat-1','repeat-2','invalid','repair'):
                q=crc['physical_native'][f'{order}/{role}/visits/{step}']
                assert (q['status'],q['product'])==((101,None) if step=='invalid' else (0,reference['old' if step=='cold' else 'new']))
            native=crc['bundled'][role]
            assert [native[k]['value'] for k in ('initial','unchanged','replace','repair','empty-reference')]==[17,17,29,29,29]
            assert native['malformed']['status']==native['missing']['status']==101 and native['repair']['binary']==native['empty-reference']['binary']
        refs[role]=reference['new']
    for k in ('screen','confirmation'):
        if k in cl:
            outcome[k]=stats(k,cl[k])
            for row in cl[k]['raw_clocks']:
                assert (row['program'],row['zip'])==(refs[row['role']]['raw'],refs[row['role']]['zip_sha256'])
    if 'confirmation' in cl:
        assert all(crc['terminal_native'][r]['product']==refs[r] for r in roles)
    assert not cl or outcome['qualified'] and set(checks)=={'PC','CP'} and all(all(x.values()) for x in checks.values())
    assert 'confirmation' not in cl or cl['screen']['valid']
    if crc['terminal_gates']:
        gates=crc['terminal_gates']
        assert gates['providers']==outcome['qualified']
        if checks:assert gates['structural']==all(all(x.values()) for x in checks.values())
        for raw,key in [('screen','pilot'),('confirmation','independent')]:
            if raw in cl:assert gates[key]==cl[raw]['valid' if raw=='screen' else 'passed']
            else:assert gates[key] is None
    print(json.dumps(outcome,indent=2))
if __name__=='__main__':main()
