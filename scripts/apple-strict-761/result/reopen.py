"""Authenticate the sealed compiler build and independently replay this exact native archive offline."""
from pathlib import Path
import gzip,hashlib,json,sys,zipfile
D=Path(__file__).resolve().parent
sys.path.insert(0,str(D.parent));from verify import verify
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def load(p):return json.loads(p.read_bytes())
def original(stem):
    a=load(D/(stem+'.json'));p=D/(stem+'.zip');assert p.stat().st_size==a['size_in_bytes'] and 'sha256:'+sha(p)==a['digest']
    return a,p
def main():
    a,p=original('source-build');assert a['workflow_run']['id']==41151585589 and a['id']==13023043052
    with zipfile.ZipFile(p) as z:
        proof=json.loads(z.read('build/build.json'));assert proof['compiled']==proof['sha256']=='ffb32cb6a9eac1f356921b5f08c3f012b904fc3cf6b38b5696af712830a62516'
        assert proof['qa']=='abfe0ef3b4f7aa42e3b9073457c9a6e129236343' and proof['source']['tree']=='19c379477ec24be16c82b952dc2e892c0563e2c7' and proof['source']['commit']=='761ea115605c34f11a1cd29afd68812c1e1359dd'
        rows=[json.loads(s) for s in gzip.decompress(z.read('build/compile.stdout.gz')).splitlines()]
        leaf,=[r for r in rows if r['reason']=='compiler-artifact' and r['target']['kind']==['bin'] and r['target']['name']=='cargo']
        assert not leaf['fresh'] and {'all-static','ohm-defaults'}<=set(leaf['features']) and rows[-1]=={'reason':'build-finished','success':True}
        assert proof['signed_runtime']==json.loads(z.read('receipts/21/installed.json')) and proof['env']['CFG_RELEASE']=='1.99.0-dev'
    a,p=original('providers')
    with zipfile.ZipFile(p) as z:
        assert len(set(z.namelist()))==len(z.namelist()) and proof==json.loads(z.read('strict-build.json'))
        return verify(z)
if __name__=='__main__':print(json.dumps(main(),sort_keys=True,indent=2))
