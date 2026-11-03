"""Recover every external output admitted to the unscored full 7024/4a6 hardware enrollment."""
import argparse,collections,gzip,hashlib,json,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
ORIGINAL='4d4174e42163408029f0b82d0c868ef567f034d8239145e5041e66769cdd8bb0'
def enc(x):return json.dumps(x,sort_keys=True,separators=(',',':')).encode()
def orig(p):
    with p.open('rb')as f:assert p.stat().st_size==3171164 and hashlib.file_digest(f,'sha256').hexdigest()==ORIGINAL
    with zipfile.ZipFile(p)as z:
        assert z.testzip()is None and not any(n.endswith('hardware.json')for n in z.namelist())
        s=json.loads(z.read('fixed-extern/seed-census.json'));v=[]
        for n,x in enumerate(s):
            root=f"fixed-extern/seed-{n}-{x['role']}/"
            raw=gzip.decompress(z.read(root+'external-products.json.gz'));assert hashlib.sha256(raw).hexdigest()==x['commitment']
            v.append(json.loads(raw))
            r=json.loads(z.read(root+'record.json'));assert r['exit']==0 and r['error_codes']==[] and r['source']=='710c60f7135879b05f6c05a34085cd7af5c19e7f' and r['cargo']==({'P':'9e65ff9195787519d9d1f1b810d028cf9083db78fc65b665abef35f3def9fbb5','C':'f97b6020c860e05eb3b4a20f0d2ae0d0e1b10953bc2a2d2205b77df9565cb13d'}[x['role']])
        names=set.union(*(set(y)for y in v))
        return {'seeds':s,'outputs':{k:[y.get(k)for y in v]for k in sorted(names)}}
def verify(p):
    r=p['outputs'];s=p['seeds'];assert [x['role']for x in s]==list('PCPCPCPC')
    sets=[{k:v[i]for k,v in r.items()if v[i]is not None}for i in range(len(s))]
    assert all(len(y)==1322 and hashlib.sha256(enc(y)).hexdigest()==x['commitment']for y,x in zip(sets,s))
    distinct={k:v for k,v in r.items()if len({tuple(x or ())for x in v})>1}
    def values(v):return {tuple(x or())for x in v}
    stable={k for k,v in distinct.items()if len(values(v[::2]))==len(values(v[1::2]))==1 and values(v[::2]).isdisjoint(values(v[1::2]))}
    suffix=lambda xs:dict(sorted(collections.Counter(Path(n).suffix for n in xs).items()))
    pairs=[sum(v[a]!=v[b]for v in r.values())for a in range(0,8,2)for b in range(1,8,2)]
    assert pairs==[352]*16 and suffix(stable)=={'.rlib':45,'.rmeta':269,'.so':25} and suffix(set(distinct)-stable)=={'.ll':40,'.log':1,'.rmeta':1,'.so':1}
    return {'actual_seeds':len(sets),'products_each':len(sets[0]),'different_each_of_16':pairs,'stable_within_role_changes':suffix(stable),'other_variation':suffix(set(distinct)-stable),'whole_Ruff_counters':0}
ap=argparse.ArgumentParser();ap.add_argument('--original',type=Path);ap.add_argument('--make',action='store_true');args=ap.parse_args()
if args.make:
    d=orig(args.original);(HERE/'observed.json.gz').write_bytes(gzip.compress(enc(d),mtime=0))
d=json.loads(gzip.decompress((HERE/'observed.json.gz').read_bytes()))
if args.original:assert orig(args.original)==d
print(json.dumps(verify(d),sort_keys=True))
