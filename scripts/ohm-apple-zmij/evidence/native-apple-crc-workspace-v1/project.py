"""Pack all ten real workspace Cargo and kernel streams plus bootstrap and source receipts."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import zipfile

from_base = Path(__file__).resolve().parent
ORIGINAL = '45012e8b81dae37c06c2469cdaf08746cae78f087289ee830da25ec29f8f32e9'


def project(source, dest):
    def put(tar, name, data):
        info = tarfile.TarInfo(name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    with source.open('rb') as f:
        assert hashlib.file_digest(f, 'sha256').hexdigest() == ORIGINAL
    selected = []
    with zipfile.ZipFile(source) as raw, tarfile.open(dest, 'x:xz', preset=3) as tar:
        keys = raw.namelist()
        assert len(keys) == len(set(keys)) and raw.testzip() is None
        rows = [k.removesuffix('verified.json') for k in keys if k.startswith('ty-comparison/workspace/') and k.endswith('/verified.json')]
        assert len(rows) == 10
        for k in sorted(keys):
            if k.endswith('/'):
                continue
            if '/' in k and not k.startswith('workspace-dyld/') and k.rpartition('/')[0]+'/' not in rows:
                continue
            data = raw.read(k)
            if k.endswith('.gz'):
                data = gzip.decompress(data)
            put(tar, k, data)
            selected.append((k, hashlib.sha256(data).hexdigest()))
        manifest = dict(run='41066385681', attempt=2, artifact='12985485763', original_zip_sha256=ORIGINAL, files=selected)
        put(tar, 'MANIFEST.json', json.dumps(manifest, sort_keys=True).encode())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    project(args.source, from_base/'workspace.tar.xz')
