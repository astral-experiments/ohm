"""Download the complete official artifacts needed by the original twelve-host verifier."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
API = 'repos/astral-experiments/ohm/actions/artifacts/'


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def acquire(gh, artifact, digest, filename):
    if filename.exists():
        assert sha(filename) == digest
        return
    route = API + str(artifact)
    metadata = json.loads(subprocess.check_output([gh, 'api', route]))
    assert metadata['id'] == artifact and not metadata['expired'] and metadata['digest'] == 'sha256:' + digest
    with tempfile.NamedTemporaryFile(dir=filename.parent) as tmp:
        subprocess.run([gh, 'api', route + '/zip'], stdout=tmp, check=True)
        tmp.flush()
        path = Path(tmp.name)
        assert path.stat().st_size == metadata['size_in_bytes'] and sha(path) == digest
        os.link(path, filename)


if __name__ == '__main__':
    if not __debug__:
        raise RuntimeError('use Python without -O')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['primary', 'independent'])
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    gh = shutil.which('gh-auto')
    if gh is None:
        parser.error('gh-auto must be installed and authenticated for astral-experiments/ohm')
    src = HERE / args.phase / 'originals.json'
    official = json.loads(src.read_bytes())
    dest = args.destination / args.phase
    dest.mkdir(parents=True, exist_ok=True)
    for pos in official['positions']:
        name = f"{pos['block']:02}-{pos['position']}.zip"
        acquire(gh, pos['id'], pos['sha256'], dest / name)
    structural = json.loads((HERE.parents[1] / 'registration.json').read_bytes())['structural_artifact']
    acquire(gh, structural['id'], structural['sha256'], args.destination / 'structural.zip')
    if (dest / 'official.json').exists():
        assert (dest / 'official.json').read_bytes() == src.read_bytes()
    else:
        shutil.copyfile(src, dest / 'official.json')
