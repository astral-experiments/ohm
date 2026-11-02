"""Authenticate, install and identify the original benchmark toolchain."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(os.environ['RUNNER_TEMP']) / 'ruff-db-link-reason'
RECORDS = ROOT / 'records'
SDK = ROOT / 'sdk'
HOST = 'x86_64-unknown-linux-gnu'
REPO = 'repos/astral-experiments/ohm/'
RELEASE = 'bcf21a3bcdfedd7174ef56ae17a5511fa5b2b6a0afff4b725bed6c5da50194d7'
RC = 'a36baff0cdf2957d634353234a608453536bdff79d4a67123fb47bc38260bced'
CARGO = '159be68484a7f8cb05debf82bee89e594b7f19b6'
RUST = 'a3fc6da13921586bc374586dee00883e9210aecd'
QUALIFY_RUN = 41442788155
QUALIFY_HEAD = '4979f6953482d2946a2aaaea1e5f23d92a449f28'
NEW_CARGO = '4109dd69209a642f309555cac0cee8b05e18f0ea'
NEW_RUST = 'a21de69d085aa07b3b5ac94058bac9e5aed482b4'
WILD = '0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5'

def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()

def save(name, value):
    (RECORDS / name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')

def download(endpoint, path, *, release=False):
    # Release assets negotiate binary content. Actions archives redirect from the JSON endpoint.
    args=['gh','api']
    if release:args+=['-H','Accept: application/octet-stream']
    with path.open('xb') as f:
        subprocess.run([*args,REPO+endpoint],stdout=f,check=True)

def main(role):
    if role not in ('22','23','253') or os.environ['GITHUB_REF']!='refs/heads/charlie/qa-ruff-db-link-cause-20261102':
        raise ValueError('wrong experimental source or distribution')
    RECORDS.mkdir(parents=True)
    assert shutil.disk_usage(ROOT).free>16<<30
    version='22' if role=='22' else '23'
    stem='ohm-1.99.0-'+version+'-'+HOST
    if role=='253':
        run=json.loads(subprocess.check_output(['gh','api',REPO+f'actions/runs/{QUALIFY_RUN}']))
        assert run['head_sha']==QUALIFY_HEAD and run['run_attempt']==1
        catalog=json.loads(subprocess.check_output(['gh','api',REPO+f'actions/runs/{QUALIFY_RUN}/artifacts?per_page=100']))
        asset,=[a for a in catalog['artifacts'] if a['name']==stem and not a['expired']]
        endpoint='actions/artifacts/'+str(asset['id'])
    else:
        endpoint='releases/assets/698533704' if role=='22' else 'actions/artifacts/13101900298'
    cat=json.loads(subprocess.check_output(['gh','api',REPO+endpoint]));save('catalog.json',cat)
    package=ROOT/(stem+'.tar.gz')
    if role=='22':
        assert (cat['name'],cat['size'],cat['digest'])==(package.name,359852703,'sha256:'+RELEASE)
        download(endpoint,package,release=True); assert sha(package)==RELEASE
    else:
        if role=='253':
            assert cat['id']==asset['id'] and cat['name']==stem and cat['workflow_run']['id']==QUALIFY_RUN and not cat['expired']
            assert cat['digest']==asset['digest'] and cat['digest'].startswith('sha256:')
            digest=cat['digest'].removeprefix('sha256:')
        else:
            assert (cat['name'],cat['size_in_bytes'],cat['digest'],cat['workflow_run']['id'],cat['expired'])==(stem,356855609,'sha256:'+RC,41348186330,False)
            digest=RC
        bundle=ROOT/'original.zip';download(endpoint+'/zip',bundle);assert sha(bundle)==digest
        with zipfile.ZipFile(bundle) as z:
            prov=stem+'-provenance.json'
            assert set(z.namelist())=={package.name,package.name+'.sha256',prov,prov+'.sha256'}
            with z.open(package.name) as src,package.open('xb') as dst:shutil.copyfileobj(src,dst)
            assert z.read(package.name+'.sha256').decode().split()==[sha(package),package.name]
            raw=z.read(prov);assert z.read(prov+'.sha256').decode().split()==[hashlib.sha256(raw).hexdigest(),prov]
            record=json.loads(raw);save('source-provenance.json',record)
            assert record['target']==HOST and record['sources']['cargo']['revision']==(NEW_CARGO if role=='253' else CARGO) and record['sources']['rust']['revision']==(NEW_RUST if role=='253' else RUST)
    subprocess.run(['tar','-xzf',package,'-C',ROOT],check=True)
    (installer,)=ROOT.glob('rust-*/install.sh')
    subprocess.run([installer,'--prefix='+str(SDK),'--components=rustc,rust-std-'+HOST+',cargo','--disable-ldconfig'],check=True)
    (driver,)=(SDK/'lib').glob('librustc_driver-*.so')
    names=['bin/cargo','bin/rustc','bin/rustdoc',str(driver.relative_to(SDK)),'lib/rustlib/'+HOST+'/bin/wild-ld/ld.bfd']
    tools={n:sha(SDK/n) for n in names}
    assert tools[names[-1]]==WILD and (role!='22' or tools['bin/cargo']=='3ce4e300d4463dfc769b6c18e138d1c951b02dfb15416a39cb5301303d168871')
    save('tools.json',dict(sha256=tools,head=os.environ['GITHUB_SHA'],role=role,tar=sha(package),boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()))
if __name__=='__main__':main(sys.argv[1])
