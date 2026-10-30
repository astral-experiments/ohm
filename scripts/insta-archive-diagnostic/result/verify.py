"""Recheck the retained syscall, dirty-reason, target and native-provider evidence."""
import argparse, copy, gzip, hashlib, json, re, sys
from pathlib import Path
D=Path(__file__).resolve().parent
sys.path.insert(0,str(D.parent))
from readback import compare
def require(good):
    if not good:raise ValueError('invalid Linux archive causal evidence')
def check(shipped,strict,previous):
    r=shipped['rows'];s=strict['rows'];hist=previous['previous_native']
    require(shipped['controls']==compare(shipped) and shipped['controls']['disagreements']==[])
    require(shipped['upstream_archive']=={'id':13017885347,'bytes':174028913,'zip_sha256':'5f6d0d47afe1f265e00473b7c23807f8a191ab91bbc3ae6ab19efb72ca516021','run':41137435629,'head':'210bee3f16da74ff34618f06608824edf6385d1b'})
    require(strict['upstream_archive']=={'id':13016094804,'bytes':53795708,'zip_sha256':'35d4afa518277b7039341bcc5b44d207888bfffef2cd50be367e81779163d27d','run':41137435629,'head':'210bee3f16da74ff34618f06608824edf6385d1b'})
    require(shipped['tools']['original']['physical_driver']['sha256']==strict['tools']['original']['physical_driver']['sha256'])
    ins=shipped['enrolled'];st=ins['original']['stat'];require(st[:4]==[33,7870513,1,8637394] and len(ins['members'])==18 and ins['original']['sha256']=='7903a1d70d27d79303d1c1a4ecfe292e69eb8a0e0a725f834947893b66fc8c55')
    for pol in ('allow','hold'):
        for n in (1,2):
            q=r[f'{pol}-repeat-{n}']
            require((q['full'],q['link_only'],q['wild'],q['root_wild'],q['root_rust'])==(2,0,1,1,[['ron','full'],['e2e','full']]))
            require(len(q['audit'])==len(q['touches'])==len(q['direct_externs'])==1 and q['direct_externs'][0][2]==[ins['direct']])
            a=q['audit'][0];t=q['touches'][0];require(a[3]==pol and a[4:6]==['1','1'] and a[6]==str(int(pol=='hold')))
            require(a[-1]==ins['direct'] and t[0]==int(a[1]) and f'utimensat({a[2]}<{ins["direct"]}>, NULL' in t[2] and t[2].endswith('= 0'))
            require(t[2].count('UTIME_OMIT')==1+int(pol=='hold') and (a[9:11]==a[11:13])==(pol=='hold'))
            require(q['archive_before']['sha256']==q['archive_after']['sha256']==ins['original']['sha256'])
            require((q['archive_before']['stat']==q['archive_after']['stat'])==(pol=='hold'))
            reasons='\n'.join(q['fingerprints'])
            require('ohm-foreign-span-bytes' in reasons and 'for insta v1.48.0: fs_status=StaleDepFingerprint { unit: UnitIndex(192)' in reasons and 'unit UnitIndex(97) CAN skip' in reasons and 'for ty_server v0.0.0: fs_status=StaleDepFingerprint { unit: UnitIndex(97)' in reasons)
        for suff in ('edited','restored'):
            q=r[pol+'-'+suff];require(q['full']==18 and q['link_only']==0 and q['wild']==2 and q['root_wild']==1)
    require(sum(len(q['audit']) for q in r.values())==26 and sum(int(a[6]) for q in r.values() for a in q['audit'])==14)
    require([r['hold-invalid-rust'][k] for k in ('full','wild','cargo')]==[2,0,101])
    for key,counts in [('unwrapped-cold',(312,0,49)),('unwrapped-repeat',(3,1,2))]:
        q=s[key];require((q['full'],q['link_only'],q['wild'])==counts and not q['timestamp_syscalls'] and q['cargo']==q['case']==0 and q['typed']==309)
    require(s['unwrapped-repeat']['cutoff'] and s['unwrapped-repeat']['image']==s['unwrapped-cold']['image']==shipped['controls']['old'])
    for role in ('strict-293','shipped'):
        x=hist[role];require(x['run']==41120192553)
        stats=[v['stat'] for v in x['rows'].values()]
        require(len({tuple(a[:4]) for a in stats})==1 and len({v['sha'] for v in x['rows'].values()})==1 and len({tuple(sorted(v['members'].items())) for v in x['rows'].values()})==1)
        require(len({a[4] for a in stats})==(1 if role=='strict-293' else 6))
        bad=previous['rejected'][role];require(bad['run']==41137063070 and bad['interleaved_unwrapped_rust_wild']==[306,47] and bad['audit_lines']==[] and bad['coherence']['before']['stat'][1]!=bad['coherence']['after']['stat'][1])
    text='\n'.join(previous['index97_log'])
    require("unit UnitIndex(97) checking dep 'ron' build_state=BuiltUnchanged" in text and 'target="insta"' in text and 'StaleDepFingerprint { unit: UnitIndex(192)' in text and 'target="e2e"' in text)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--self-test',action='store_true');args=ap.parse_args()
    manifest=(D/'SHA256SUMS').read_text().splitlines();expected={n:h for h,n in [row.split() for row in manifest]}
    require(set(expected)=={'shipped.json.gz','strict-293.json.gz','independent-controls.json.gz'})
    db={}
    for name,digest in expected.items():
        b=(D/name).read_bytes();require(hashlib.sha256(b).hexdigest()==digest);db[name]=json.loads(gzip.decompress(b))
    shipped,strict,hist=[db[n+'.json.gz'] for n in ('shipped','strict-293','independent-controls')]
    check(shipped,strict,hist)
    if args.self_test:
        for target,key,value in [('hold-repeat-1','full',1),('hold-repeat-2','touches',[]),('hold-valid','case',0),('hold-malformed','cargo',0),('hold-repeat-1','fingerprints',[])]:
            changed=copy.deepcopy(shipped);changed['rows'][target][key]=value
            try:check(changed,strict,hist)
            except (ValueError,AssertionError):continue
            raise ValueError('accepted a fabricated '+target+' '+key)
    print('33 signed Cargo visits, 26 audited archive requests (14 held), 3 raw native images, 2 strict natural-control visits. Signed repeats: 2 full, 0 link-only, 1 stock Wild under either policy. No native verdict differences.')
if __name__=='__main__':main()
