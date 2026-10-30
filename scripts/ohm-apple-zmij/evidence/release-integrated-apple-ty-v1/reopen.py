"""Reopen native binaries, Xcode traces and ordinary Cargo clocks in a complete hosted checkpoint."""
import argparse
import hashlib
from pathlib import Path
import sys
from zipfile import ZipFile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from project import structural
from verify import read,packed,prove_clocks
sys.path.insert(0,str(HERE/'offline'))
from application import reopen
from native import Dataset
from protocol import Receiver,sources
from release_checks import same_rust
from root_measure_objc2 import check

def run():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path,help='The final cumulative ZIP named in index.json')
    args=parser.parse_args()
    index=read(HERE/'index.json')
    archive=index['final_archive']
    with args.archive.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==archive['sha256']
    assert args.archive.stat().st_size==archive['size']
    with ZipFile(args.archive) as z:
        inner=hashlib.sha256()
        nonempty=[i for i in z.infolist() if not i.is_dir()]
        assert len({i.filename for i in nonempty})==len(nonempty)==archive['originals']
        for info in sorted(nonempty,key=lambda i:i.filename):
            with z.open(info) as f:dg=hashlib.file_digest(f,'sha256').hexdigest()
            inner.update((dg+'  '+info.filename+'\n').encode())
        assert inner.hexdigest()==archive['inner_manifest_sha256']
        for mode in index['studies']:
            v=Receiver(z);subjects=sources(v)
            if mode=='rust':
                rows,_,_,_=reopen(Dataset(z))
                native=structural(mode,{'rows':rows})
            else:native=structural(mode,same_rust(v,subjects))
            assert packed(native)==(HERE/(mode+'-structural.json.gz')).read_bytes()
    for mode,stages in index['studies'].items():
        for stage in stages:
            observed=check(args.archive,archive['sha256'],stage,mode)
            reference=read(HERE/(mode+'-'+stage+'.json.gz'))
            # The proofs contain the digest of their earliest independently acquired checkpoint.
            # Sequence verification documents original members carried unchanged into the final ZIP.
            assert reference['archive']==index['stage_archives'][mode+'/'+stage]
            observed['archive']=reference['archive']
            assert packed(observed)==(HERE/(mode+'-'+stage+'.json.gz')).read_bytes()
            print(mode,stage,prove_clocks(mode,stage,observed),'pairs')
if __name__=='__main__':run()
