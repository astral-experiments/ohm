"""Get the one sealed Cargo at the registered GitHub run and check its release SDK."""
from pathlib import Path
import hashlib, io, json, os, subprocess, sys, zipfile
REPO='astral-experiments/ohm'
RUN=41151297839
QA='f23a67771c625785cd70f58e9b46e8d26af3d317'
SIGNED='2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c'
STRICT='761ea115605c34f11a1cd29afd68812c1e1359dd'
ELF='035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4'
def h(b):return hashlib.sha256(b).hexdigest()
def api(path):return subprocess.check_output(['gh','api',f'repos/{REPO}/{path}'])
def supply(root):
    dest=root/'input';dest.mkdir()
    run=json.loads(api(f'actions/runs/{RUN}'));assert run['head_sha']==QA and run['event']=='workflow_dispatch'
    jobs=json.loads(api(f'actions/runs/{RUN}/jobs'))['jobs'];assert any(j['conclusion']=='success' and any('Build native Cargo' in s['name'] and s['conclusion']=='success' for s in j['steps']) for j in jobs)
    items=json.loads(api(f'actions/runs/{RUN}/artifacts'))['artifacts']
    def acquire(name,ident,length,dig):
        a,=[a for a in items if a['name']==name];assert a['workflow_run']['head_sha']==QA and a['workflow_run']['id']==RUN and not a['expired']
        assert (a['id'],a['size_in_bytes'],a['digest'])==(ident,length,'sha256:'+dig)
        b=api(f'actions/artifacts/{ident}/zip');assert len(b)==length and h(b)==dig
        (dest/(name+'.json')).write_text(json.dumps(a,indent=2)+'\n');return zipfile.ZipFile(io.BytesIO(b))
    z=acquire('disposable-gc-qualified-cargo',13023471212,17661123,'9a259bfc8b82d2bbf67d7d45b01c56902e8e4eff7654cc34d1537881868a76c2')
    zz=acquire('gc-qualified-cargo-build-record',13023271637,37080,'c3316118ecb13fd54259b7ae760f9daccb978ee0acd39437404dfcec654a3eff')
    assert set(z.namelist())=={'cargo','build.json'} and z.read('build.json')==zz.read('build.json')
    b=z.read('build.json');assert h(b)=='d54bc38a259b60b17168c745fa19389d81f9d861b7be42ef04e09b4de4e8ea4c';p=json.loads(b)
    assert p['candidate']==STRICT and p['qa']==QA and p['compiled']==p['delivered']==ELF
    assert (p['tree']['files'],p['tree']['tree'],p['tree']['mode_path_sha256_inventory'])==(3109,'19c379477ec24be16c82b952dc2e892c0563e2c7','c43d43954ae37b222933baae703bbac6dcb7905de4caaa5e27bef3ecfc1618c3')
    signed=json.loads((root/'receipts/21/installed.json').read_bytes());assert p['signed_runtime']==signed and {'ohm-defaults','all-static'}<=set(p['features'])
    (dest/'build.json').write_bytes(b); binary=z.read('cargo');assert len(binary)==51101864 and h(binary)==ELF
    cargo=dest/'strict-cargo';cargo.write_bytes(binary);cargo.chmod(0o755)
    roles={}
    for name,exe,sha,commit in [('signed',root/'sdk-21/bin/cargo',signed['bin/cargo'],SIGNED),('strict',cargo,ELF,STRICT)]:
        assert h(exe.read_bytes())==sha
        version=subprocess.check_output([exe,'-Vv'],text=True);assert 'commit-hash: '+commit+'\n' in version
        roles[name]=dict(binary=str(exe),sha256=sha,head=commit,version=version)
    (dest/'products.json').write_text(json.dumps(roles,indent=2)+'\n')
if __name__=='__main__':supply(Path(sys.argv[1]).resolve())
