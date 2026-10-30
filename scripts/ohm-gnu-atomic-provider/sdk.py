"""Restore one physically verified full compiler SDK for a provider case."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ['RUNNER_TEMP']) / 'atomic-transitive-proof'
BOOT_RUN = 41138808306
BOOT_HEAD = 'f251bcb417be911fc3ed9c4814b17ffa7b360c28'
P_DRIVER = 'd38721a8dd46c97d253686d920563654b035f25b6f0687c80871fb0a92401084'
SDK = ROOT / 'subject'
def digest(data): return hashlib.sha256(data).hexdigest()
def sha(path):
    with Path(path).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()
def load(path): return json.loads(Path(path).read_bytes())
def save(path, x):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f: json.dump(x,f,sort_keys=True,indent=2); f.write('\n')
def api(endpoint):
    return json.loads(subprocess.check_output(['gh','api','repos/astral-experiments/ohm/actions/'+endpoint]))
def identity(file): return [sha(file),file.stat().st_size,file.stat().st_mode & 0o777]
def verify(base,table):
    files={f.relative_to(base).as_posix():f for f in base.rglob('*') if f.is_file()}
    assert len(table)==119 and files.keys()==table.keys(),(len(files),len(table))
    for n,f in files.items(): assert identity(f)==table[n],n

def prepare(role,artifact_id,artifact_digest):
    assert role in ['P','C']
    ROOT.mkdir(); out=ROOT/'receipt';out.mkdir()
    spec=load(HERE.parent/'ohm-gnu-atomic-db/source/source.json')['roles']
    tree=load(HERE.parent/'ohm-aarch64-portable-review/source/sdk-members.json')
    donor=Path(os.environ['QA_ROOT'])/'candidate-sdk'
    parent=load(donor.parent/'receipts/candidate.json')
    kernel=tree['driver_path']; assert parent['driver_path']==kernel and parent['driver'][0]==P_DRIVER
    assert parent['source']==spec['parent']['source'] and parent['tree']==spec['parent']['tree']
    table=tree['common']|{kernel:parent['driver']}; verify(donor,table)
    shutil.copytree(donor,SDK,copy_function=os.link,symlinks=True)
    handoff=None
    if role=='C':
        run=api('runs/'+str(BOOT_RUN))
        assert (run['head_sha'],run['conclusion'],run['run_attempt'])==(BOOT_HEAD,'success',1)
        meta=api('artifacts/'+str(artifact_id)); assert meta['workflow_run']['id']==BOOT_RUN and not meta['expired']
        assert meta['name']=='gnu-atomic-registered-compiler' and meta['digest']=='sha256:'+artifact_digest
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            d=Path(tmp); archive=d/'transfer.zip'
            with archive.open('xb') as f:
                subprocess.run(['gh','api','repos/astral-experiments/ohm/actions/artifacts/'+str(artifact_id)+'/zip'],stdout=f,check=True)
            assert sha(archive)==artifact_digest and archive.stat().st_size==meta['size_in_bytes']
            with zipfile.ZipFile(archive) as z:
                assert sorted(z.namelist())==['atomic-candidate.json','driver.zst'];z.extractall(d)
            c=load(d/'atomic-candidate.json');assert c['unchanged_members']==118 and c['parent_driver']==parent['driver']
            assert (c['source'],c['reviewed_source'],c['tree'],c['parent'],c['reviewed_parent'])==(
                spec['candidate']['source'],spec['candidate']['reviewed'],spec['candidate']['tree'],parent['source'],spec['parent']['reviewed'])
            assert c['driver_path']==kernel and c['bootstrap']==parent['bootstrap'] and sha(d/'driver.zst')==c['compression']
            assert c['compression']=='59c1745411be2329aa40ad135f2b00f77dceb821f28bc8d9c4712da0374a5a2e'
            assert c['driver']==['45d8737f938d6ed97be5903342718f087d0af6ea710dd3c2416babc8c570d4b7',142781688,0o755]
            pending=(SDK/kernel).with_suffix('.atomic-new')
            with pending.open('xb') as f:subprocess.run(['zstd','-q','-d','-c',d/'driver.zst'],stdout=f,check=True)
            pending.chmod(c['driver'][2]);assert identity(pending)==c['driver'];pending.replace(SDK/kernel)
            table[kernel]=c['driver'];assert table[kernel][0]!=P_DRIVER
            handoff={'run':BOOT_RUN,'head':BOOT_HEAD,'archive':artifact_id,'sha256':artifact_digest,'record':c}
    else: assert artifact_id==0 and not artifact_digest
    verify(SDK,table);assert identity(donor/kernel)==parent['driver']
    save(out/'sdk.json',{'role':role,'source':spec['parent' if role=='P' else 'candidate'],'parent':parent,'handoff':handoff,'files':table,'driver_path':kernel})
    print('Authentic SDK',role,table[kernel][0],table['bin/cargo'][0],len(table),flush=True)
