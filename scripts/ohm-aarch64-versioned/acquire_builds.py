"""Reopen the exact four immutable build artifacts; materialize only registered data in a private runner."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from qualified_build import O,Q,R,ART,jar,get
from version_kit import rt
from study import sha,save

def main():
    root=rt.ROOT/'inputs'/'versioned';root.mkdir()
    gate=json.loads((HERE/'qualified-builds.json').read_bytes())
    assert gate['run']==R and gate['QA']==Q and gate['artifacts']==ART
    wf=json.loads(get('gh',f'actions/runs/{R}'));assert wf['status']=='completed' and wf['conclusion']=='failure' and wf['head_sha']==Q
    assets={row['name']:row for row in json.loads(get('gh',f'actions/runs/{R}/artifacts'))['artifacts']}
    assert set(assets)==set(ART)
    for name,(i,n,h) in ART.items():
        a=assets[name];assert not a['expired'] and (a['id'],a['size_in_bytes'],a['digest'])==(i,n,'sha256:'+h)
    n='gnu-versioned-marker-compiler-pair';i,sz,wire=ART[n]
    rt.room(True)
    zipped=root/'sdk.zip'
    with zipped.open('xb') as dest:
        subprocess.run(['gh','api',f'repos/{O}/actions/artifacts/{i}/zip'],stdout=dest,check=True)
    assert zipped.stat().st_size==sz and sha(zipped)==wire
    with zipfile.ZipFile(zipped) as z:
        assert z.namelist()==['linux-aarch64-sdk-pair.tar.zst']
        with z.open(z.namelist()[0]) as a,(root/'sdk.tar.zst').open('xb') as b:
            shutil.copyfileobj(a,b,2**20)
    assert sha(root/'sdk.tar.zst')==gate['capsule']
    r=jar('gh','gnu-versioned-marker-compiler-receipts')
    r.extractall(root/'native')
    assert r.read('qa-head').decode().strip()==Q
    assert all(sha(root/'native'/(k+'-sdk.json'))==v for k,v in gate['subjects'].items())
    p=jar('gh','gnu-versioned-cargo-product');assert sorted(p.namelist())==['cargo','product.json'];p.extractall(root/'cargo')
    exe=root/'cargo/cargo';assert sha(exe)==gate['cargo_elf'] and sha(root/'cargo/product.json')==gate['cargo_manifest']
    meta=json.loads((root/'cargo/product.json').read_bytes());assert meta['mode']==0o755 and meta['git']==gate['source']['cargo']['source'];exe.chmod(meta['mode'])
    save(rt.LOG/'source-qualified-product-ingress.json',{'builds':gate,'archive':sha(root/'sdk.tar.zst'),'cargo':sha(exe),'source_workflow':os.environ['GITHUB_SHA']})
if __name__=='__main__': main()
