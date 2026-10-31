"""Reopen both worker archives and recheck the qualified command, compiler ABI, source, and oracle bytes."""
from pathlib import Path
import gzip,hashlib,json,subprocess,sys,tempfile,zipfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from verify import verify
def h(b):return hashlib.sha256(b).hexdigest()
def main():
    prefix='private/host-unicode-wild-dir-v1/results/'
    specs=[('first.zip',3668750,316,'886fe10b47ce084494f67f5f9fb8b7d0b76390c2c73474c160bdf55e397c485b'),('qualified.zip',3673153,318,'01ac025afe7cc3e72d702473ece8b68d940b731a53714b4df3c8e4fbb9e2e5ce')]
    for n,size,count,sha in specs:
        f=HERE/n;assert f.stat().st_size==size and h(f.read_bytes())==sha
        with zipfile.ZipFile(f) as z:
            assert len(z.namelist())==count==len(set(z.namelist())) and z.testzip() is None
            for item in z.infolist():
                p=Path(item.filename);assert not p.is_absolute() and '..' not in p.parts and item.file_size<30_000_000
            build=z.read('input/build.json');assert h(build)=='d54bc38a259b60b17168c745fa19389d81f9d861b7be42ef04e09b4de4e8ea4c'
            proof=json.loads(build);sdk=z.read('receipts/21/installed.json')
            assert h(sdk)=='e444c9e242c48e62f21fd88250594db028d27c7275d1e1914af1c595c5e78a0b' and proof['signed_runtime']==json.loads(sdk)
            assert proof['tree']['tree']=='19c379477ec24be16c82b952dc2e892c0563e2c7' and proof['tree']['files']==3109 and proof['tree']['mode_path_sha256_inventory']=='c43d43954ae37b222933baae703bbac6dcb7905de4caaa5e27bef3ecfc1618c3'
            assert proof['compiled']==proof['delivered']=='035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4' and proof['candidate']=='761ea115605c34f11a1cd29afd68812c1e1359dd'
    with tempfile.TemporaryDirectory() as tmp,zipfile.ZipFile(HERE/'qualified.zip') as new,zipfile.ZipFile(HERE/'first.zip') as old:
        new.extractall(tmp);qualified=verify(Path(tmp)/prefix)
        rendered=(json.dumps(qualified,sort_keys=True,indent=2)+'\n').encode()
        assert new.read('terminal.json')==rendered==(HERE/'verified.json').read_bytes() and h(rendered)=='704df1389bc5332e3fc717f4b5de8e85eddef7b7831671668a253e1f037abd79'
        assert qualified['commands']==31
        groups=json.loads(new.read(prefix+'complete.json'))
        oldgroups=json.loads(old.read(prefix+'complete.json'));assert set(groups)==set(oldgroups)
        for group in groups:
            oldrows=json.loads(old.read(prefix+group+'/complete.json'));newrows=json.loads(new.read(prefix+group+'/complete.json'))
            assert set(oldrows)==set(newrows)
            for phase,entry in newrows.items():
                earlier=oldrows[phase];rel=prefix+group+'/'+phase+'/';r=earlier['result'];now=entry['result']
                assert r==json.loads(old.read(rel+'observation.json')) and not earlier['encoded']
                for k in ('status','reader','reader_sha256','generated'):assert r.get(k)==now.get(k)
                if r['status']==0:
                    for key in (r['reader_sha256'],*r['generated'].values()):
                        payload=gzip.decompress(old.read(prefix+'objects/'+key+'.gz'));assert h(payload)==key
        print('Verified 31 qualified visits, both same-path migrations, and 31 independently repeated verdicts and complete products.')
        print('Qualified output SHA-256',h(rendered))
if __name__=='__main__':main()
