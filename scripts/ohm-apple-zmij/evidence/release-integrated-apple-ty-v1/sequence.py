"""Compare original files through a cumulative sequence of hosted checkpoints."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

def digest(data):
    return hashlib.sha256(data).hexdigest()

def hashed_files(receipt, original_dir):
    archive=original_dir/(receipt['name']+'.zip')
    assert archive.stat().st_size==receipt['size']
    with archive.open('rb') as f:
        assert hashlib.file_digest(f,'sha256').hexdigest()==receipt['sha256']
    rows={}
    with ZipFile(archive) as z:
        for i in z.infolist():
            if i.is_dir():continue
            assert i.filename not in rows
            with z.open(i) as f:rows[i.filename]=hashlib.file_digest(f,'sha256').hexdigest()
    manifest=''.join(dg+'  '+p+'\n' for p,dg in sorted(rows.items())).encode()
    assert len(rows)==receipt['originals'] and digest(manifest)==receipt['inner_manifest_sha256']
    return rows

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path,help='Directory holding immutable downloads')
    parser.add_argument('result',type=Path)
    parser.add_argument('receipts',nargs='+',type=Path,help='One or more GitHub-authenticated archive receipts')
    args=parser.parse_args()
    prior={}
    proof=[]
    for path in args.receipts:
        receipt=json.loads(path.read_bytes());current=hashed_files(receipt,args.directory)
        diff={p:dict(before=a,after=current.get(p)) for p,a in prior.items() if current.get(p)!=a}
        # versioned_select.current intentionally overwrites the one active selection pointer.
        assert set(diff)<={'versioned-current.json'},diff
        if diff:
            archive=args.directory/(receipt['name']+'.zip')
            with ZipFile(archive) as z: selections=json.loads(z.read('versioned-current.json'))
            assert selections['name'] in ('aware','signed') and selections['source'] in ('fd55a13d0220748794ba3c7c9556ef8ceed8591f','2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c')
        proof.append({**{k:receipt[k] for k in ('id','name','sha256','originals','inner_manifest_sha256')},'added':len(set(current)-set(prior)),'carried':len(prior)-len(diff),'changed':diff})
        prior=current
    data=(json.dumps(proof,indent=2,sort_keys=True)+'\n').encode()
    if args.result.exists():assert args.result.read_bytes()==data
    else:args.result.write_bytes(data)
    print([(r['name'],r['originals'],len(r['changed'])) for r in proof])
if __name__=='__main__':main()
