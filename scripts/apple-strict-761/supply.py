"""Import the exact native product from this packaging QA branch before running the experiment."""
from pathlib import Path
import hashlib, json, os, subprocess, sys, zipfile
A=41151585589;AH='abfe0ef3b4f7aa42e3b9073457c9a6e129236343'
C='761ea115605c34f11a1cd29afd68812c1e1359dd';T='19c379477ec24be16c82b952dc2e892c0563e2c7'
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def api(q):return json.loads(subprocess.check_output(['gh','api','repos/astral-experiments/ohm/'+q]))
def enroll(root):
    root=root.resolve();b=root/'inbound';b.mkdir();r=api('actions/runs/'+str(A));assert r['head_sha']==AH and r['conclusion']=='success'
    meta,=[a for a in api(f'actions/runs/{A}/artifacts')['artifacts'] if a['name']=='source-sealed-apple-strict-cargo' and not a['expired']]
    assert meta['workflow_run']['head_sha']==AH and meta['workflow_run']['id']==A
    assert meta['id']==13022788392 and meta['size_in_bytes']==15487894 and meta['digest']=='sha256:3d0ee55fe20e680cc0c5075ea36259f5d70ccae57e34df0b4ec3d07f86c007df'
    z=b/'native-761.zip'
    with z.open('xb') as f:subprocess.run(['gh','api',f'repos/astral-experiments/ohm/actions/artifacts/{meta["id"]}/zip'],stdout=f,check=True)
    assert z.stat().st_size==meta['size_in_bytes'] and 'sha256:'+sha(z)==meta['digest']
    with zipfile.ZipFile(z) as f:
        assert set(f.namelist())=={'cargo','build.json'};p=b/'strict-cargo';p.write_bytes(f.read('cargo'));p.chmod(0o755)
        proof=json.loads(f.read('build.json'));(root/'receipts/strict-build.json').write_bytes(f.read('build.json'))
    assert proof['qa']==AH and proof['source']['commit']==C and proof['source']['tree']==T and proof['source']['mode_path_sha256_inventory']=='c43d43954ae37b222933baae703bbac6dcb7905de4caaa5e27bef3ecfc1618c3'
    assert {'all-static','ohm-defaults'}<=set(proof['features']) and proof['env']['CFG_RELEASE_CHANNEL']=='dev'
    assert proof['compiled']==proof['sha256']==sha(p) and proof['signed_runtime']==json.loads((root/'receipts/21/installed.json').read_bytes())
    output=subprocess.check_output([p,'-Vv'],text=True);assert 'commit-hash: '+C+'\n' in output and 'host: aarch64-apple-darwin' in output
    subprocess.run(['/usr/bin/codesign','--verify','--strict',p],check=True)
    (root/'receipts/strict-custody.json').write_text(json.dumps({k:meta[k] for k in ('name','id','digest','size_in_bytes','workflow_run')},indent=2,sort_keys=True)+'\n')
if __name__=='__main__':enroll(Path(sys.argv[1]))
