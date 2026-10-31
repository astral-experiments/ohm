"""Download built Cargo inputs with the private repository's own job token, before the offline experiment."""
from pathlib import Path
import hashlib,json,os,re,shutil,subprocess,sys,zipfile
REPO='astral-experiments/ohm'
P='7277e6cdaba44c43294a07c0661fc8e69fd8e3e7'
S='2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c'
C='b76dc8006155d48a8cd7d6c5543acb9c18e2ce4b'
A=41150601667; AH='96051e5c262ce0d04dc5bb9631a65eb80e848de4'
B=41149649623; BH='0db917cab8e5cfb2cbd51ee794d9f6ce958bc495'
def hx(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def api(path):return json.loads(subprocess.check_output(['gh','api','repos/'+REPO+'/'+path]))
def supply(root):
    saved=root/'input';saved.mkdir()
    artifacts=[]
    def archive(run,head,name,expected=None):
        r=api('actions/runs/'+str(run));assert r['status']=='completed' and r['conclusion']=='success' and r['head_sha']==head
        a,=[v for v in api(f'actions/runs/{run}/artifacts')['artifacts'] if v['name']==name and not v['expired']]
        assert a['workflow_run']['id']==run and a['workflow_run']['head_sha']==head
        if expected:assert a['id']==expected[0] and a['size_in_bytes']==expected[1] and a['digest']=='sha256:'+expected[2]
        dest=saved/(name+'.zip')
        with dest.open('xb') as f:subprocess.run(['gh','api',f'repos/{REPO}/actions/artifacts/{a["id"]}/zip'],stdout=f,check=True)
        assert hx(dest)==a['digest'].split(':')[1] and a['size_in_bytes']==dest.stat().st_size
        artifacts.append({k:a[k] for k in ['id','name','size_in_bytes','digest','workflow_run']})
        return zipfile.ZipFile(dest)
    roles={}
    def register(role,path,commit,h,version):
        assert path.is_file() and hx(path)==h and version==subprocess.check_output([path,'-Vv'],text=True)
        assert len(commit)==40 and 'commit-hash: '+commit+'\n' in version
        roles[role]=dict(binary=str(path),head=commit,sha256=h,version=version)
    sr=json.loads((root/'receipts/21/installed.json').read_bytes())
    with archive(A,AH,'same-compiler-adjacent-cargo') as z:
        assert set(z.namelist())=={'parent','matched294','parent.json','matched294.json'}
        for role,commit in [('parent',P),('matched294',S)]:
            b=json.loads(z.read(role+'.json'));assert b['qa']==AH and b['commit']==commit and b['signed_sdk']==sr and 'all-static' in b['features']
            f=saved/role;f.write_bytes(z.read(role));f.chmod(0o755)
            register(role,f,commit,b['compiled'],b['version'])
            (saved/(role+'.json')).write_bytes(z.read(role+'.json'))
    with archive(B,BH,'disposable-gc-qualified-cargo',(13022058572,17668587,'f3d870572356d2751ea5ea7e8e8178b2a01be33122114e925459582e3a8d13aa')) as z:
        assert set(z.namelist())=={'cargo','build.json'}
        b=json.loads(z.read('build.json'));assert b['qa']==BH and b['candidate']==C and b['signed_runtime']==sr
        f=saved/'combined';f.write_bytes(z.read('cargo'));f.chmod(0o755)
        assert b['compiled']==b['delivered']=='f1a88bf5fb2bf431eeea068455d9d4e98dcfbfee3dc381ee47cc7c96df3e128f'
        register('combined',f,C,b['compiled'],b['version']);(saved/'combined.json').write_bytes(z.read('build.json'))
    f=root/'sdk-21/bin/cargo';register('signed',f,S,sr['bin/cargo'],subprocess.check_output([f,'-Vv'],text=True));roles['defaults-off']=roles['signed']
    stock=Path(subprocess.check_output(['rustup','which','--toolchain','1.99.0','cargo'],text=True).strip()).resolve(strict=True)
    version=subprocess.check_output([stock,'-Vv'],text=True);assert 'release: 1.99.0\n' in version and 'ohm' not in version.lower()
    commit=re.search('^commit-hash: ([0-9a-f]{40})$',version,re.M)[1];register('stock-cargo',stock,commit,hx(stock),version)
    ordered={r:roles[r] for r in ('parent','signed','matched294','combined','defaults-off','stock-cargo')}
    (saved/'products.json').write_text(json.dumps(ordered,indent=2)+'\n')
    (saved/'artifacts.json').write_text(json.dumps(artifacts,sort_keys=True,indent=2)+'\n')
if __name__=='__main__':supply(Path(sys.argv[1]).resolve())
