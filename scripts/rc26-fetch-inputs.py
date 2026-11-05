from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(os.environ['RC26_ROOT'])
ROOT.mkdir()
INPUT = ROOT / 'inputs'
INPUT.mkdir()
(ROOT / 'proofs').mkdir()


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def fetch(url, name, digest, authenticated=True):
    dest = INPUT / name
    args = ['curl', '--fail', '--silent', '--show-error', '--location', '--output', str(dest)]
    headers = ''
    if authenticated:
        args += ['--header', '@-']
        media = 'application/vnd.github+json' if '/actions/artifacts/' in url else 'application/octet-stream'
        headers = 'Authorization: Bearer ' + os.environ['GH_TOKEN'] + '\nAccept: ' + media + '\n'
    result = subprocess.run([*args, url], input=headers, text=True)
    proof = {'url': url, 'name': name, 'exit': result.returncode,
             'bytes': dest.stat().st_size if dest.exists() else None,
             'sha256': sha(dest) if dest.exists() else None, 'expected_sha256': digest}
    (ROOT / 'proofs' / (name + '.download.json')).write_text(json.dumps(proof, indent=2) + '\n')
    if result.returncode:
        if dest.exists():
            dest.rename(ROOT / 'proofs' / ('partial-' + name))
        raise RuntimeError('Input download failed: ' + name)
    assert proof['sha256'] == digest, proof
    return dest


parent = fetch('https://api.github.com/repos/astral-experiments/ohm/releases/assets/714957495',
               'parent357-sdk.tar.zst', 'c9245fff238b278c1d1263985c375b4d1f3c3e0a5f5660728eb6598780257821')
zip_path = fetch('https://api.github.com/repos/astral-experiments/ohm/actions/artifacts/13455710028/zip',
                 'candidate-artifact.zip', '2cdeac5d3087f9f7c83f5ee353e3370badea1ab0a54a70dbbc1c504ac83e348c')
worker = fetch('https://api.github.com/repos/astral-experiments/ohm/releases/assets/714983864',
               '351-original-worker.zip', '3adb1e8ff5c2b438e40b518503327a9876c4db4c7a4dd90c72b4830689457098')
for archive, dest in ((zip_path, INPUT), (worker, ROOT / 'frozen351')):
    with zipfile.ZipFile(archive) as z:
        assert all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in z.namelist())
        z.extractall(dest)
sdk = INPUT / 'ohm-1.99.0-26-x86_64-unknown-linux-gnu.tar.gz'
assert sdk.stat().st_size == 360107873 and sha(sdk) == '83e1d8100b59b7f7e042cc5246fe75b6f0117333631d1557b8884f1b8d260152'
(INPUT / 'candidate-request.json').write_text(json.dumps({
    'run': 42107067758, 'head': '405f059f80442e076d69c900805045581d5b9075',
    'bytes': sdk.stat().st_size, 'sha256': sha(sdk),
    'manifest_sha256': '35612a2e4d1186ac0d0a29a6083e178f3e9eb1b75ff886b5c615093033d2ccf0',
}, indent=2) + '\n')
parent_root = ROOT / 'parent357'
parent_root.mkdir()
proc = subprocess.Popen(['zstd', '-dc', str(parent)], stdout=subprocess.PIPE)
with tarfile.open(fileobj=proc.stdout, mode='r|') as tar:
    tar.extractall(parent_root, filter='data')
proc.stdout.close()
assert proc.wait() == 0
inventory = json.loads((parent_root / 'production-357/installed/sdk-inventory.json').read_text())
prefix = parent_root / 'sdk/trait-25-production-357'
assert len(inventory) == 142
for name, row in inventory.items():
    p = prefix / name
    assert p.resolve().is_relative_to(prefix)
    assert p.stat().st_size == row['bytes'] and sha(p) == row['sha256']
    assert p.stat().st_mode & 0o777 == row['mode']
fixed_cargo = parent_root / 'sdk/trait-25-owner-formatted/bin/cargo'
assert sha(fixed_cargo) == 'e095525d408717c5ca32f808177e2c0f0620f0d66b2e20ca6077b5bdbd989a87'
(ROOT / 'proofs/parent-inventory.json').write_text(json.dumps(inventory, indent=2) + '\n')
print('Both SDK archives and all 142 parent SDK files are verified.', flush=True)
