"""Keep complete kernel exec traces, phase verdicts and fingerprint ledgers from the enrolled historical Ruff run."""
import argparse,gzip,hashlib,json,re,zipfile
from pathlib import Path
FULL_SHA='a5a390f0f430c15209d44794cbb8358e6a540992822c3d9dbea26eb54a200172'
FULL_SIZE=191509985
P='7024b0d2dc5f64bba72c0d6d28f537a5cd9707ed'
C='4a6de7858c60e579fc30e01f5b60ddcaa84c2e30'
PRE='ba07041c4b41686b0f80ad89985b8881046cb48e'
SOURCES={'release-parent':(P,'9e65ff9195787519d9d1f1b810d028cf9083db78fc65b665abef35f3def9fbb5'),
         'release-child':(C,'f97b6020c860e05eb3b4a20f0d2ae0d0e1b10953bc2a2d2205b77df9565cb13d'),
         'pre-reader':(PRE,'c67a662901b9d15945579f0b607c234cf92e55488c687b68ba8a95f9e22326a2')}
def admit(p):
    assert p.stat().st_size==FULL_SIZE
    with p.open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==FULL_SHA
def desired(n):
    parts=n.split('/')
    if len(parts)>=3 and parts[0] in ('release-parent','release-child','signed') and parts[1] in ('old','independent-clean-edited') and parts[-1].startswith('exec.'):return False
    return n in {'release-results.json','release-refusals.json','release-factories.json'} or (n.startswith(('upgrade-signed/','upgrade-pre-reader/','signed/','release-parent/','release-child/')) and (re.search(r'/exec\.\d+$',n)or n.endswith(('/prior-records.json','/upgraded-records.json','/epoch.json','/result.json'))))
def from_original(p):
    admit(p)
    with zipfile.ZipFile(p)as z:
        assert z.testzip()is None;factories=json.loads(z.read('release-factories.json'))
        for name,(rev,sha)in SOURCES.items():
            b=z.read('cargo-'+name);r=factories[name]
            assert r['cargo_source']==rev and r['sha256']==sha==hashlib.sha256(b).hexdigest()and len(b)==r['bytes']
        return {i.filename:z.read(i).decode()for i in z.infolist()if desired(i.filename)}
def encode(x):return gzip.compress(json.dumps(x,separators=(',',':'),ensure_ascii=True,sort_keys=True).encode(),mtime=0)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('original',type=Path);ap.add_argument('output',type=Path);a=ap.parse_args()
    data=from_original(a.original);payload=encode(data);a.output.write_bytes(payload);print(len(data),len(payload),hashlib.sha256(payload).hexdigest())
