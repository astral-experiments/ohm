"""Receive an exact cross-run Cargo for the two native private-target interleavings."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

HERE=Path(__file__).resolve().parent
REPOSITORY=1319437234
SIGNED='4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e'

def file_sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()

def receive(registry,metadata,archive,sdk,work):
    assert not work.exists() and sdk.is_dir() and file_sha(sdk/'bin/cargo')==SIGNED
    reg=json.loads(registry.read_bytes());meta=json.loads(metadata.read_bytes())
    assert [meta['id'],meta['workflow_run']['id'],meta['workflow_run']['head_sha'],meta['size_in_bytes']]==[reg[k] for k in ('artifact_id','workflow_run','workflow_sha','archive_size')]
    assert not meta['expired'] and meta['workflow_run']['repository_id']==meta['workflow_run']['head_repository_id']==REPOSITORY
    assert meta['digest']=='sha256:'+reg['archive_sha256'] and archive.stat().st_size==reg['archive_size'] and file_sha(archive)==reg['archive_sha256']
    work.mkdir(mode=0o700);product=work/'product';product.mkdir()
    with zipfile.ZipFile(archive) as z:
        for name,limit in [('cargo',200*1024*1024),('build.json',2*1024*1024)]:
            member,=[f for f in z.infolist() if f.filename==name]
            assert 0<member.file_size<=limit
            with z.open(member) as src,(product/name).open('xb') as dst:shutil.copyfileobj(src,dst)
    (product/'cargo').chmod(0o755)
    assert file_sha(product/'cargo')==reg['cargo_sha256'] and file_sha(product/'build.json')==reg['build_sha256']
    doc=json.loads((product/'build.json').read_bytes())
    assert doc['qa']==reg['workflow_sha'] and doc['candidate']==doc['tree']['commit']==reg['source']
    assert doc['tree']['tree']==reg['tree'] and doc['tree']['mode_path_sha256_inventory']==reg['inventory']
    assert doc['compiled']==doc['delivered']==reg['cargo_sha256']
    version=subprocess.check_output([product/'cargo','-Vv'],text=True)
    assert 'commit-hash: '+reg['source'] in version.splitlines()
    shutil.copyfile(registry,work/'registration.json');shutil.copyfile(metadata,work/'artifact-metadata.json')
    for role in ('stack','stack-enosys'):
        base=work/role;base.mkdir()
        (base/'sdk-21').symlink_to(sdk.resolve(),target_is_directory=True)
        (base/'product').symlink_to(product.resolve(),target_is_directory=True)
        shutil.copyfile(registry,base/'stack-receipt.json')
        subprocess.run([sys.executable,'-IB',str(HERE/'reattached.py'),role,str(base)],check=True,timeout=270)

if __name__=='__main__':receive(*[Path(p).resolve() for p in sys.argv[1:]])
