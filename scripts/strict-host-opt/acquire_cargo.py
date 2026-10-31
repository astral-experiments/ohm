"""Retrieve the already-built repair-qualified Cargo, without another compiler bootstrap."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

REPO = 'astral-experiments/ohm'
ARCHIVE = '9a259bfc8b82d2bbf67d7d45b01c56902e8e4eff7654cc34d1537881868a76c2'
CARGO = '035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4'


def fetch(place):
    assert not place.exists();place.mkdir()
    cli=os.environ.get('GITHUB_CLI', 'gh')
    spec=['repos/'+REPO+'/actions/artifacts/13023471212']
    info=json.loads(subprocess.check_output([cli,'api',*spec]))
    assert info['workflow_run']['id']==41151297839 and info['name']=='disposable-gc-qualified-cargo'
    assert info['size_in_bytes']==17661123 and not info['expired'] and info['digest']=='sha256:'+ARCHIVE
    dest=place/'cargo.zip'
    with dest.open('xb') as f:subprocess.run([cli,'api',spec[0]+'/zip'],stdout=f,check=True)
    assert dest.stat().st_size==info['size_in_bytes'] and hashlib.sha256(dest.read_bytes()).hexdigest()==ARCHIVE
    with zipfile.ZipFile(dest) as z:
        assert set(z.namelist())=={'cargo','build.json'} and z.testzip() is None
        build=json.loads(z.read('build.json'));native=z.read('cargo')
    assert hashlib.sha256(native).hexdigest()==build['compiled']==build['delivered']==CARGO
    assert build['candidate']=='761ea115605c34f11a1cd29afd68812c1e1359dd' and build['parent']=='2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c'
    (place/'cargo').write_bytes(native);(place/'cargo').chmod(0o755)
    assert hashlib.sha256((place/'cargo').read_bytes()).hexdigest()==CARGO
    (place/'custody.json').write_text(json.dumps({'artifact':info,'build':build},sort_keys=True,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('fresh_directory',type=Path)
    fetch(p.parse_args().fresh_directory)
