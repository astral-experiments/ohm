"""Verify both directions using the same tables as the admitted native reader."""
import argparse, gzip, hashlib, json, runpy, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import dispatch_map,proof


def sha(data):
    return hashlib.sha256(data).hexdigest()


def with_map_if_needed(left,right,reader,di,keys):
    # This constructs the complete candidate using only the input file's
    # payload and the independently decoded physical DefPathHash roster.
    middle,identity=proof.reencoded(left,right,reader,di,keys)
    if middle==right:
        return identity
    proof.check(len(middle)==len(right),'unexplained file length before map proof')
    # Prove both directions of BOTH relations, including the intermediate as
    # a source in its own right. The map verifier only accepts a full second
    # image after re-encoding the two rows and the one verified type shorthand.
    legs=[proof.project(left,middle,reader,di,keys),
          proof.project(middle,left,reader,di,keys),
          dispatch_map.project(middle,right,reader,di,keys),
          dispatch_map.project(right,middle,reader,di,keys)]
    expected=[middle,left,right,middle]
    proof.check(all(r['reconstructed_sha256']==sha(b)for r,b in zip(legs,expected,strict=True)),
                'unclosed intermediate byte proof')
    return {'composition':'DefIndex then RPITIT','intermediate':[len(middle),sha(middle)],
            'source_to_intermediate':legs[0],'intermediate_to_source':legs[1],
            'intermediate_to_target':legs[2],'target_to_intermediate':legs[3],
            'reconstructed_sha256':sha(right)}

def both(left,right,root_reader,di,defkeys):
    a,b=root_reader(left),root_reader(right)
    for k in ('target','crate_name','stable_crate_id','private_svh','public_svh','global_public_hash'):
        proof.check(a[k]==b[k],'different native '+k)
    proof.check(left!=right,'no byte difference')
    moved=di.keyed(left,a)!=di.keyed(right,b)
    convert=with_map_if_needed if moved else dispatch_map.project
    rows=[]
    for one,two in ((left,right),(right,left)):
        result=convert(one,two,root_reader,di,defkeys)
        proof.check(result['reconstructed_sha256']==sha(two),'opposite image digest')
        rows.append(result)
    combined=['composition' in r for r in rows]
    proof.check(combined[0]==combined[1],'asymmetric classification')
    return {'class':('DefIndex permutation and RPITIT map order' if combined[0] else
                     'synthetic DefIndex permutation' if moved else 'RPITIT map order'),
            'crate':a['crate_name'],'raw':[{'bytes':len(x),'sha256':sha(x)}for x in (left,right)],
            'both_directions':rows}


def contents(path):
    f=path.open('rb')
    if f.read(2)==b'\x1f\x8b':
        f.close();f=gzip.open(path,'rb')
    else:f.seek(0)
    with f:b=f.read((64<<20)+1)
    proof.check(len(b)<=64<<20,'oversize metadata')
    return b


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reader',required=True,type=Path,help='existing admitted candidate_gate.py')
    p.add_argument('left',type=Path);p.add_argument('right',type=Path)
    args=p.parse_args();v=runpy.run_path(str(args.reader.resolve()))
    r=v['L']['M']
    result=both(contents(args.left),contents(args.right),v['Z']['ROOT'],r['di'],r['keys'])
    print(json.dumps(result,sort_keys=True,indent=2))
