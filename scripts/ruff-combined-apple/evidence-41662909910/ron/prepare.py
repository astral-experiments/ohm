"""Prepare the locked Ron source closure used in the Ruff regression replay."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tomllib
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser(__doc__)
parser.add_argument('output', type=Path)
parser.add_argument('ruff_checkout', type=Path)
parser.add_argument('rustup_home', type=Path, help='Private RUSTUP_HOME with an ohm toolchain')
parser.add_argument('--registry-cache', type=Path,
                    help='Cargo registry/cache directory containing downloaded .crate files')
args = parser.parse_args()
out = args.output.resolve()
out.mkdir()
spec = json.loads(Path(__file__).with_name('expected-source.json').read_bytes())
lock = subprocess.check_output(['git', '-C', args.ruff_checkout, 'show', spec['ruff'] + ':Cargo.lock'])
assert hashlib.sha256(lock).hexdigest() == spec['original_lock_sha256']
entries = {p['name'] + '-' + p['version']: p for p in tomllib.loads(lock.decode())['package']}
vendor = out / 'vendor'
vendor.mkdir()
for key, sha in spec['registry_checksums'].items():
    entry = entries[key]
    assert entry['checksum'] == sha
    file = out / (key + '.crate')
    cached = list(args.registry_cache.glob('*/' + file.name)) if args.registry_cache else []
    if cached:
        shutil.copyfile(cached[0], file)
    else:
        url = 'https://static.crates.io/crates/' + entry['name'] + '/' + file.name
        with urllib.request.urlopen(url) as response, file.open('wb') as dest:
            shutil.copyfileobj(response, dest)
    assert hashlib.sha256(file.read_bytes()).hexdigest() == sha
    with tarfile.open(file) as tar:
        for member in tar:
            name = Path(member.name)
            assert name.parts[0] == key and '..' not in name.parts
            assert member.isfile() or member.isdir()
            tar.extract(member, vendor, filter='data')
    depot = vendor / key
    hashes = {str(f.relative_to(depot)): hashlib.sha256(f.read_bytes()).hexdigest()
              for f in depot.rglob('*') if f.is_file()}
    (depot / '.cargo-checksum.json').write_text(json.dumps({'files': hashes, 'package': sha}))

project = out / 'project'
(project / '.cargo').mkdir(parents=True)
(project / 'src').mkdir()
(project / '.cargo/config.toml').write_text(
    '[source.crates-io]\nreplace-with="exact-ruff"\n[source.exact-ruff]\ndirectory='
    + json.dumps(str(vendor)) + '\n')
shutil.copytree(vendor / 'ron-0.12.0', project / 'ron')
(project / 'Cargo.toml').write_text(
    '[package]\nname="green_stub_ron_replay"\nversion="0.1.0"\nedition="2021"\n'
    '[workspace]\nexclude=["ron"]\n[dependencies]\nron={path="ron"}\n')
(project / 'src/main.rs').write_text(
    'fn main() { let values: Vec<u32> = ron::from_str("[17,29]").unwrap(); '
    'assert_eq!(values, [17, 29]); println!("{values:?}"); }\n')
(project / 'Cargo.lock').write_bytes(lock)
env = {k: os.environ[k] for k in ('HOME', 'PATH', 'LANG') if k in os.environ}
env.update(RUSTUP_HOME=str(args.rustup_home.resolve()), RUSTUP_TOOLCHAIN='ohm',
           CARGO_HOME=str(out / 'seed-cargo'), CARGO_TARGET_DIR=str(out / 'seed-target'),
           CARGO_BUILD_BUILD_DIR=str(out / 'seed-build'), CARGO_NET_OFFLINE='true')
data = json.loads(subprocess.check_output(
    ['cargo', '+ohm', 'metadata', '--offline', '--format-version', '1'], cwd=project, env=env))
ron, = [p['id'] for p in data['packages'] if p['name'] == 'ron']
features, = [n['features'] for n in data['resolve']['nodes'] if n['id'] == ron]
assert sorted(features) == spec['signed_root_features']
resolved = {p['name'] + '-' + p['version']: p.get('checksum') for p in
            tomllib.loads((project / 'Cargo.lock').read_text())['package']
            if p['name'] != 'green_stub_ron_replay'}
assert resolved.keys() == spec['registry_checksums'].keys()
assert resolved['ron-0.12.0'] is None
assert all(resolved[k] == v for k, v in spec['registry_checksums'].items() if k != 'ron-0.12.0')
(out / 'source.json').write_text(json.dumps(spec, indent=2) + '\n')
