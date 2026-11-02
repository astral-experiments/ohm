"""Verify the original bounded ZIP and independently reconstruct the three real edits and paired B+D."""
from pathlib import Path
import hashlib,json,shutil,stat,sys,tempfile,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from score import replay
from basis import canon,digest
from native_reader import affirm
def unpack(path,expected):
    assert path.is_file()and path.stat().st_size<=128<<20
    with path.open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==expected
    with tempfile.TemporaryDirectory()as folder,zipfile.ZipFile(path)as z:
        root=Path(folder);members=z.infolist();assert len({m.filename for m in members})==len(members)
        assert sum(m.file_size for m in members)<=768<<20 and all(m.file_size<=64<<20 and not m.is_dir()and stat.S_IFMT(m.external_attr>>16)in(0,stat.S_IFREG)and not Path(m.filename).is_absolute()and '..'not in Path(m.filename).parts and chr(92)not in m.filename for m in members)
        manifest=json.loads(z.read('receipt.json'));assert set(manifest['members'])|{'receipt.json'}=={m.filename for m in members}
        for n,(length,sha)in manifest['members'].items():
            m=z.getinfo(n);assert m.file_size==length and n.startswith(('session-results/','trait-results/','metadata-origins/'))
            with z.open(n)as fp:assert hashlib.file_digest(fp,'sha256').hexdigest()==sha
            if n.startswith('session-results/'):
                dest=root/n;dest.parent.mkdir(exist_ok=True,parents=True)
                with z.open(n)as fp,dest.open('xb')as out:shutil.copyfileobj(fp,out)
        gold=root/'session-results/result.json'
        if not gold.is_file():return {'accepted':False,'reason':'Incomplete original; no score.','members_verified':len(members)}
        gates=affirm(root/'session-results');original=json.loads(gold.read_bytes());actual=replay(root/'session-results');assert canon(original)==canon(actual)
        return {'accepted':True,'independent_score_sha256':digest(canon(actual)),'physical_and_native':gates,'original':actual}
if __name__=='__main__':print(json.dumps(unpack(Path(sys.argv[1]),sys.argv[2]),indent=2,sort_keys=True))
