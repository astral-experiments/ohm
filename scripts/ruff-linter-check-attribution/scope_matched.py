"""Recover the source compilers and run the exact native qualification in one worker."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
import scope_fixture
import scope_inventory as inv
import worker as w


def api(path):
    return json.loads(subprocess.check_output(w.gh(path)))


def kit(label, binding):
    w.checked_head(); w.resources()
    code=w.WS/('scope-'+label)/'scripts/ruff-matched-stage'; receipt=w.ROOT/('scope-kit-'+label); receipt.mkdir()
    sha=binding['head']; run=binding['run']; run_info=api(f'actions/runs/{run}')
    w.need(w.git(code, 'rev-parse','HEAD')==sha and w.git(code,'status','--porcelain','--untracked-files=all')=='','wrong builder checkout')
    w.need((run_info['head_sha'],run_info['head_repository']['full_name'],run_info['head_branch'],run_info['event'],run_info['run_attempt'],run_info['conclusion'])==(sha,w.REPO,'charlie/qa-rdr-visibility-scope-20261103','workflow_dispatch',1,'success'),'unregistered factory')
    assets={v['name']:v for v in api(f'actions/runs/{run}/artifacts')['artifacts']}; blobs={}
    for key in ('receipts','kit'):
        name,num,size,digest=binding[key]; live=assets[name]
        w.need([live['id'],live['size_in_bytes'],live['digest']]==[num,size,'sha256:'+digest] and not live['expired'] and live['workflow_run']['id']==run and 0<size<450*2**20,'unregistered factory artifact')
        f=receipt/(key+'.zip')
        with f.open('xb')as stream:subprocess.run(w.gh(f'actions/artifacts/{num}/zip'),stdout=stream,check=True,timeout=300)
        w.need(w.sha(f)==digest and f.stat().st_size==size,'transport hash');blobs[key]=f
    with zipfile.ZipFile(blobs['receipts'])as z:
        def record(n):
            w.need(z.getinfo(n).file_size<8*2**20,'oversized source manifest');return json.loads(z.read(n))
        expect=z.read('archive.sha256').decode(); req=record('registration.json'); accepted=record('accepted.json');smoke=record('smoke.json')
        w.need(req==json.loads((code/'registration.json').read_bytes()) and accepted['registration']==w.sha(code/'registration.json'),'source registration')
        w.need({k:r['revision']for k,r in req['roles'].items()}==binding['source'] and all(v['invalid']=='E0308'for v in smoke['arms'].values())and set(smoke['arms'])=={'normal','defer'},'incomplete factory control')
        w.need(re.fullmatch(r'[0-9a-f]{64}  matched-stage.tar.zst\s*',expect),'archive receipt')
    compressed=receipt/'kit.tar.zst'
    with zipfile.ZipFile(blobs['kit'])as z:
        w.need(z.namelist()==['matched-stage.tar.zst'],'non-capsule archive')
        with z.open('matched-stage.tar.zst')as source, compressed.open('xb')as target: shutil.copyfileobj(source,target,2**20)
    w.need(w.sha(compressed)==expect.split()[0],'original capsule checksum');blobs['kit'].unlink()
    (receipt/'capsule/objects').mkdir(parents=True);seen=set();size=0
    with subprocess.Popen(['zstd','-q','-dc',compressed],stdout=subprocess.PIPE)as dec:
        with tarfile.open(fileobj=dec.stdout,mode='r|')as stream:
            for entry in stream:
                name=entry.name.rstrip('/')
                if name in ('capsule','capsule/objects'):
                    w.need(entry.isdir(),'not a directory');continue
                allowed=name in ('capsule/C.json','capsule/P.json','capsule/qualified.json') or re.fullmatch(r'capsule/objects/[0-9a-f]{64}',name)
                size+=entry.size;w.need(allowed and entry.isfile() and name not in seen and 0<entry.size<700*2**20 and size<5200*2**20 and 0<entry.mode<=0o777,'invalid capsule member')
                dest=receipt/name
                with stream.extractfile(entry)as source,dest.open('xb')as target:shutil.copyfileobj(source,target,2**20)
                os.chmod(dest,entry.mode);seen.add(name)
        w.need(dec.wait()==0,'incomplete compressed capsule')
    compressed.unlink();spec=importlib.util.spec_from_file_location('capsule_'+label,code/'capsule.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    manifest=m.reopen(receipt/'capsule',receipt/'reopened');w.save(w.OUT/('scope-kit-'+label+'.json'),dict(run=run,head=sha,entries=binding,qualified=accepted,manifest=manifest));return manifest


def acquire():
    bindings=json.loads((w.HERE/'scope-factory-bindings.json').read_bytes()); kits={label:kit(label,info)for label,info in bindings.items()}
    cfg={}
    for label,man in kits.items():
        for role,variant in (('P','normal'),('C','defer')):
            sdk=Path(man['arms'][variant]['root']);driver,=list((sdk/'lib').glob('librustc_driver-*.so'))
            cfg[label+'-'+role]=dict(sdk=str(sdk),driver=w.sha(driver),source=bindings[label]['source'][role]);w.need(cfg[label+'-'+role]['source'] and sdk.is_dir(),'missing role')
    w.save(w.OUT/'scope-sdks.json',cfg)


def study(role):
    w.checked_head();w.resources();cfg=json.loads((w.OUT/'scope-sdks.json').read_bytes());w.need(role in cfg,'unregistered role')
    sdk=Path(cfg[role]['sdk']);old=w.ROOT/'signed-control-sdk'
    if not old.exists():
        w.need(w.SDK.is_dir() and not w.SDK.is_symlink(),'original SDK directory');w.SDK.rename(old)
    else:
        w.need(w.SDK.is_dir() and not w.SDK.is_symlink() and w.SDK.parent==w.ROOT,'wrong scratch SDK');shutil.rmtree(w.SDK)
    subprocess.run(['cp','-a','--reflink=auto',sdk,w.SDK],check=True)
    driver,=list((w.SDK/'lib').glob('librustc_driver-*.so'));w.need(w.sha(driver)==cfg[role]['driver'],'wrong active driver')
    w.OUT=w.OUT/role;w.OUT.mkdir();prior=w.ROOT/'before-edit'
    if prior.exists():
        w.need(prior.is_dir() and not prior.is_symlink() and prior.parent==w.ROOT,'wrong private donor');shutil.rmtree(prior)
    conf=cfg[role];w.save(w.OUT/'provenance.json',conf)
    inv.study()


def fixture(role):
    roles=json.loads((w.OUT/'scope-sdks.json').read_bytes());candidate=roles[role]
    scope_fixture.fixture(Path(candidate['sdk']),w.ROOT/('scope-fixture-'+role),w.OUT/('fixture-'+role+'.json'),candidate['driver'])


if __name__=='__main__':
    if sys.argv[1:]==['acquire']:acquire()
    elif len(sys.argv)==3 and sys.argv[1] in ('study','fixture'):{'study':study,'fixture':fixture}[sys.argv[1]](sys.argv[2])
    else:raise ValueError('experiment or role')
