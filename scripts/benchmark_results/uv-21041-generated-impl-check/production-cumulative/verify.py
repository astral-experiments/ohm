"""Replay the eight paired raw Linux counters, monotonic blocking waits and optional original archive."""
from pathlib import Path
from fractions import Fraction
from statistics import median
from math import comb
import argparse,gzip,hashlib,json,runpy,struct,zipfile
H=Path(__file__).resolve().parent
def sha(b):return hashlib.sha256(b).hexdigest()
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':')).encode()
def extract(z,roles,roster):
    decode=runpy.run_path(str(H/'exec_events.py'))['decode']
    def get(k):return json.loads(z.read(k))
    hashes={};rows=[];unchanged={}
    plan=get('uv-client/raw-pairs.json');boot=get('fresh-boot.json')['boot'];command=['/tmp/uv-workflow-search/sdk/bin/cargo','check','-p','uv-client','--locked','--offline','-j8']
    def member(k):data=z.read(k);hashes[k]=sha(data);return json.loads(data)
    for i,row in enumerate(plan):
        arms={}
        for role in roles:
            base=f'uv-client/pair-{i}-{role}/';k=base+'scoped/';r=member(k+'per-rustc.json');tree=decode(member(k+'kernel-events.json'));ts=r['targets'];assert set(ts)==set(roster)
            target=next(iter(ts.values()));images=[v for v in tree['images']if v['file']==target['file'] or Path(v['exe']).name=='rustc' or v.get('argv')and Path(v['argv'][0]).name=='rustc']
            assert len(images)==8
            ans={}
            for name,a in ts.items():
                v,=[v for v in images if v['pid']==a['pid']];argv=v['argv'];assert argv==a['argv']and v['file']==a['file']and tree['exits'][a['pid']]==0 and argv[argv.index('--crate-name')+1]==name
                counter=struct.unpack('<4Q',bytes.fromhex(a['raw_hex']));assert counter==(a['instructions'],a['time_enabled_ns'],a['time_running_ns'],a['event_id'])and counter[0]>0 and counter[1]==counter[2]>0 and counter[3]>0
                ans[name]=[a['pid'],sha(canonical(argv)),a['raw_hex']]
            c=member(base+'clock/whole-clock.json');e=member(base+'clock/ordinary.json');w=member(base+'wall/ordinary.json')
            assert c['code']==c['event_errno']==0 and c['instructions']>0 and c['running']==c['enabled']>0 and e['boot']==w['boot']==boot and e['argv']==w['argv']==w['invoked']==command
            assert not w['deadline_fired']and w['end_ns']-w['start_ns']==w['ns']>0 and w['exit']==0 and w['timer']=='CLOCK_MONOTONIC; waitpid blocking; ITIMER_REAL watchdog'
            arms[role]={'rustc':ans,'whole_raw':{k:c[k]for k in ('instructions','running','enabled','event_errno','code')},'blocking_wall':[w['start_ns'],w['end_ns']]}
        rows.append({'order':row['order'],'hold':row['hold'],'arms':arms})
    for h in (0,1):
        for role in roles:
            for stage in ('A','B'):
                k=f'uv-client/hold-{h}-{role}/unchanged-kernel-{stage}/';tr=decode(member(k+'kernel-events.json'));zero=member(k+'zero.json')
                assert zero['rustc_images']==0 and all(Path(v['exe']).name!='rustc'and(not v.get('argv')or Path(v['argv'][0]).name!='rustc')for v in tr['images']);unchanged[k]=0
    per_hold={}
    for h in (0,1):
        k=f'derive-evidence/hold-{h}-passed.json';per_hold[str(h)]=member(k)
        assert all(per_hold[str(h)][r]['selected']==6 for r in roles)
    native={}
    for h in (0,1):
        for role in roles:
            key=f'{h}/{role}';q=f'uv-client/hold-{h}-{role}/';b=member(q+'A-launcher-binding.json');native[key]=b
            assert b['launcher']==command[0].removesuffix('cargo')+'rustc' and b['rustc_fingerprint']>0 and b['cached_queries']>0
    for i,row in enumerate(rows):
        for role in roles:
            key=f"{row['hold']}/{role}";base=f'uv-client/pair-{i}-{role}/';b=native[key]
            for mode in ('scoped','clock','wall'):assert member(base+mode+'-launcher-binding.json')==b
            target=next(iter(get(base+'scoped/per-rustc.json')['targets'].values()));assert target['file']==[b['dev'],b['inode'],b['size']]and target['exe']==b['launcher']
    return {'launchers_and_warm_Cargo_inputs':native,'visits':rows,'archive_member_sha256':hashes,'boot':boot,'unchanged':unchanged,'source_and_metadata':per_hold,'command':command}
def score(surface,roles,roster):
    rows=surface['visits'];assert [r['hold']for r in rows]==[0]*4+[1]*4 and [r['order']for r in rows]==[[roles[int(x)]for x in n]for n in ('01','10','10','01','10','01','01','10')]
    endpoints={k:[]for k in [*roster,'sum_of_eight','whole_cargo','bare_wall_ns']}
    for row in rows:
        arms=[]
        for role in roles:
            a=row['arms'][role];assert set(a['rustc'])==set(roster);t={k:struct.unpack('<4Q',bytes.fromhex(v[2]))[0]for k,v in a['rustc'].items()}
            assert len({v[0]for v in a['rustc'].values()})==8 and all(v>0 for v in t.values());t['sum_of_eight']=sum(t.values());t['whole_cargo']=a['whole_raw']['instructions'];t['bare_wall_ns']=a['blocking_wall'][1]-a['blocking_wall'][0];arms.append(t)
        for k in endpoints:endpoints[k].append([a[k]for a in arms])
    result={}
    for name,v in endpoints.items():
        rs=[Fraction(b,a)for a,b in v];h=[median(rs[:4]),median(rs[4:])]
        result[name]={'raw':v,'role_medians':[str(median([Fraction(r[i])for r in v]))for i in (0,1)],'candidate_over_control':str(median(rs)),'control_over_candidate':str(median([1/r for r in rs])),'hold_candidate_over_control':[str(x)for x in h],'improved':sum(x<1 for x in rs),'strictly_over_2x':sum(x<Fraction(1,2)for x in rs)}
        if name=='sum_of_eight':
            ratios=[1/x for x in rs];strict=sum(x>2 for x in ratios);folds=[median(ratios[:4]),median(ratios[4:])]
            p=Fraction(sum(comb(8,k)for k in range(strict,9)),2**8)
            result[name].update(wins_over_twofold=strict,one_sided_p=str(p),hold_control_over_candidate=list(map(str,folds)),qualified=strict==8 and all(x>2 for x in folds))
    return result
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--original',type=Path);args=parser.parse_args()
    for s in (H/'SHA256SUMS').read_text().splitlines():
        digest,path=s.split('  ',1);assert Path(path).name==path and sha((H/path).read_bytes())==digest
    origin=json.loads((H/'origin.json').read_bytes());sample=json.loads(gzip.decompress((H/'samples.json.gz').read_bytes()));roles=origin['roles'];run=sample['visits'];assert len(run)==8 and len(sample['unchanged'])==8
    if args.original:
        with args.original.open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==origin['artifact']['sha256']
        with zipfile.ZipFile(args.original)as z:assert extract(z,roles,origin['rustc_roster'])==sample
    found=score(sample,roles,origin['rustc_roster']);assert found==json.loads((H/'paired.json').read_bytes())
    for k in ('uv_client','sum_of_eight','whole_cargo','bare_wall_ns'):
        r=found[k];print(f"{k}: {float(Fraction(r['control_over_candidate'])):.6f}x, {100*(1-float(Fraction(r['candidate_over_control']))):.4f}% fewer, {r['improved']}/8 better")
    print('Eight-rustc sum >2x on 8/8:',found['sum_of_eight']['qualified'],'p =',found['sum_of_eight']['one_sided_p'])
if __name__=='__main__':main()
