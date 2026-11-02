"""Reopen the native SDK, independent histories, real source witnesses and physical calibrators."""
from pathlib import Path
from statistics import median
import hashlib,json,os,struct
from basis import CASE,HERE,LOCK,PLAN,SIX,WORKSPACE,canon,digest,filehash,read,readz
import fixed_products,producer_map,live_review
def affirm(root):
    cal=read(root/'calibration/accepted.json');qual=read(root/'qualification/accepted.json');selected=qual['control'];mat=read(root/'actual-inputs.json');bounds=read(root/'compatibility.json');dc=root/'calibration';assert cal['protocol']==qual['plan']==CASE['protocol']and cal['boot']not in cal['excluded']and len(cal['excluded'])==len(set(cal['excluded']))>24 and len(cal['cpus'])==len(set(cal['cpus']))==8
    assert set(cal['excluded'])==set(read(HERE/'dispatch-enrollment.json')['excluded_boots'])and len(cal['excluded'])==28
    assert filehash(dc/'scoped/calibration.json')==cal['scoped']and filehash(dc/'wall/passed.json')==cal['blocking'];sc=read(dc/'scoped/calibration.json');assert sc['reexec_rejected']and set(sc['known_two_instruction_loop'])=={'serial','threads','fork'}
    for key,expected in {'serial':22000000,'threads':66000000,'fork':0}.items():
        v=sc['known_two_instruction_loop'][key];assert v['expected_delta']==expected and v['counts'][1]-v['counts'][0]==v['measured_delta']and abs(v['measured_delta']-expected)<=100000
    for key,mul in {'serial':1,'threads':3,'fork':1,'reexec':1}.items():
        ns=[]
        for n in(3000000,14000000):
            r=read(dc/(key+'-'+str(n)+'.json'));assert r['event_errno']==r['code']==0 and r['start']<r['stop']and 0<r['running']<=r['enabled']and r['running']*1000>=r['enabled']*995;ns.append(r['instructions'])
        assert ns==cal['whole'][key]and abs(ns[1]-ns[0]-22000000*mul)<100000
    wc=read(dc/'wall/passed.json');assert wc['machine']['boot']==cal['boot']and wc['machine']['cpus']==cal['cpus']and wc['source']==filehash(HERE/'kit/wall_probe.c')and wc['clock_source']==filehash(HERE/'kit/wall_clock.py');offsets=[]
    for i in range(5):
        for delay in (0,3,13,31,53):
            d=dc/'wall'/('probe-'+str(i)+'-'+str(delay));m=read(d/'ordinary.json');a,b=map(int,(d/'cargo.stdout').read_text().split());over=m['ns']-(b-a);assert m['exit']==0 and not m['deadline_fired']and m['start_ns']<=a<=b<=m['end_ns']and b-a>=delay*1000000 and 0<=over<=12000000;offsets.append(over)
    assert median(offsets)<=4000000 and wc['nonzero_exit']==17 and wc['deadline_exit']==-9 and 60000000<=wc['deadline_ns']<1000000000
    gate=root/'qualification';roles={'R','F'}|{selected};canonical=read(HERE/'ctfe-authority.json')['native_originals']
    for role in roles:
        f=gate/('actual-ctfe-'+role+'.json');r=read(f);gold=canonical['R' if role=='R'else'S'];assert filehash(f)==qual['canonical_ctfe_source_receipts'][role]and r['checks']==gold['checks']and r['matches_official_regression']==(role!='R')and r['rustc_launcher_sha256']==LOCK['roles'][role]['runtime']['bin/rustc']['sha256']and r['source_commit']==mat[role]['source']['commit'];assert len(r['visits'])==5 and all(len(v['commands'])==4 and all(q['exit']==0 for q in v['commands'])for v in r['visits'].values())
    folders={'signed-1':'R','treatment':'F'}
    if selected=='S':folders|={'signed-2':'R','corrected':'S'}
    for name,role in folders.items():
        dr=gate/name;res=read(dr/'verdict.json');assert res['role']==role and res['states']==CASE['states']and res['normal_roster']==SIX and all(res['actual_unchanged'].values())and res['native_workspace']==39
        assert res['passes']==(selected!='S'or role!='R')
        if not res['passes']:assert res['only_known_ctfe']
        for st in 'BCD':
            comp=readz(dr/('fresh-'+st)/'typed-warm-cold.json.gz');assert comp['accepted']==res['semantic'][st]['accepted']and comp['ctfe_terminal_only']==res['semantic'][st]['ctfe_terminal_only']and comp['all_workspace']==39 and comp['all_public']==423 and not comp['unresolved']
            warm=dr/('warm-'+st);products=readz(warm/'products.json.gz');ordinary=readz(warm/'fixed-products.json.gz')
            paths={name:v[0]for name,v in products['workspace'].items()}
            assert {Path(n)for n in ordinary}==fixed_products.paths(paths)
            for crate in SIX:assert ordinary[paths[crate]]==products['workspace'][crate][1:]
            for n,(size,sha)in ordinary.items():
                assert isinstance(size,int)and size>=0 and len(bytes.fromhex(sha))==32
                if n.endswith('.public-api-hash'):assert products['public_sidecars'][n]==sha
            for a,b in zip((dr/('warm-'+st),dr/('fresh-'+st)),('edited','cold')):
                live=read(a/'live-api.json');assert live['baseline']['accepted'] and live['VariantPreferences']['accepted']==(st in'BC')and live['SupportedVariantProperties']['accepted']==(st=='D')
    for role in (selected,'F'):
        for st,nn in zip('ABCD',(0,1,1,1)):
            d=gate/(role+'-upstream-'+st);a=read(d/'accepted.json');assert a['passed_rank_tests']==nn and a['source']==CASE['states'][st]and a['revision']==CASE['upstream_rank_test'][st]and filehash(d/'stdout')==a['stdout']and filehash(d/'stderr')==a['stderr']
    for name,kind in [('incremental','incremental'),('metadata','metadata')]:assert filehash(root/'epoch-native'/name/'passed.json')==bounds[kind]
    stable={};position={};moves=[]
    for line in (root/'sdk-directory-moves.jsonl').read_text().splitlines():
        obj=json.loads(line);role=obj['role'];x=obj['launcher_and_cargo']
        assert role in mat and set(x)=={'cargo','rustc'} and all(x[k][0]==mat[role][k+'_kernel_identity']and x[k][1]>0 for k in x)
        assert stable.setdefault(role,x)==x
        src,dst=Path(obj['source']),Path(obj['destination'])
        assert {src.name,dst.name}=={'sdk',role} and [p.parent.name for p in (src,dst)if p.name==role]==['ctfe22-root-sdks']
        assert position.get(role,src)==src
        if dst.name=='sdk':assert dst not in position.values()
        position[role]=dst;moves.append(role)
    assert {selected,'F'}<=set(stable) and all(p.name==r for r,p in position.items()) and len(moves)>=16
    return {'additional_fixed_native_certificates':live_review.replay(root),'full_Cargo_producer_graph':producer_map.eligible_histories(root),'dedicated_boot':cal['boot'],'original_sdk_families':sorted(roles),'scoped_hardware_calibrator':cal['scoped'],'bare_wall_calibrator':cal['blocking'],'native_original_groups':folders,'live_source_histories_admitted':True}

if __name__=='__main__':
    import sys
    print(json.dumps(affirm(Path(sys.argv[1])),sort_keys=True))
