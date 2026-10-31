"""Fetch one fixed same-repository SDK only after rechecking its actual successful native source job."""
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import *

REPO='astral-experiments/ohm'
def metadata(path):
    return json.loads(subprocess.check_output(['gh','api','repos/'+REPO+path]))
def verify(job,origin,artifact,expected,triple):
    branch='charlie/qa-rc22-native-markers-'+('apple-' if triple==APPLE else '')+'20261031'
    require(origin['id']==expected['run'] and origin['head_sha']==expected['head'] and origin['head_branch']==branch and origin['repository']['full_name']==REPO and origin['head_repository']['full_name']==REPO and origin['path']=='.github/workflows/ci.yml' and origin['event']=='workflow_dispatch' and origin['run_attempt']==1,'source workflow receipt')
    require(job['id']==expected['job'] and job['run_id']==expected['run'] and job['head_sha']==expected['head'] and job['status']=='completed' and job['conclusion']=='success' and job['name']==f'Native SDK ({triple})','wrong native source job')
    for step in ('Reconstruct exact Rust and Cargo Git histories','Authenticate distributed bootstrap Cargo and stock linker layout','Build exact native Rust, standard library, rustdoc and both Cargo readers','Reopen every completed SDK member','Publish reusable native SDK'):
        hit=[s for s in job['steps'] if s['name']==step]
        require(len(hit)==1 and hit[0]['status']=='completed' and hit[0]['conclusion']=='success',('source operation',step))
    require(artifact['id']==expected['artifact'] and not artifact['expired'] and artifact['size_in_bytes']==expected['archive_bytes'] and artifact['digest']=='sha256:'+expected['archive_sha256'] and artifact['name']=='rc22-native-sdk-'+triple and artifact['workflow_run']['id']==expected['run'] and artifact['workflow_run']['head_sha']==expected['head'],'different native SDK archive')

def get(expected,out,metadata_dir):
    triple=host();origin=metadata('/actions/runs/'+str(expected['run']));job=metadata('/actions/jobs/'+str(expected['job']));art=metadata('/actions/artifacts/'+str(expected['artifact']))
    verify(job,origin,art,expected,triple)
    out.mkdir();metadata_dir.mkdir()
    save(metadata_dir/'binding.json',{'run':origin['id'],'head':origin['head_sha'],'job':job['id'],'steps':[(s['name'],s['conclusion']) for s in job['steps']],'artifact':art['id'],'digest':art['digest'],'bytes':art['size_in_bytes']})
    archive=out.parent/'source-native.zip'
    with archive.open('xb') as f:subprocess.run(['gh','api','repos/'+REPO+'/actions/artifacts/'+str(expected['artifact'])+'/zip'],stdout=f,check=True)
    require(archive.stat().st_size==expected['archive_bytes'] and sha(archive)==expected['archive_sha256'],'native ZIP differs')
    with zipfile.ZipFile(archive) as z:
        require(len(z.namelist())==3 and set(z.namelist())=={'kit.tar.zst','receipt.json','members.json'},'unknown outer SDK members')
        for n in z.namelist():
            with z.open(n) as i,(out/n).open('xb') as o:shutil.copyfileobj(i,o)
    require(sha(out/'receipt.json')==expected['receipt'] and sha(out/'members.json')==expected['members'] and sha(out/'kit.tar.zst')==expected['kit'],'wrong ZIP member')
if __name__=='__main__':get(read(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]))
