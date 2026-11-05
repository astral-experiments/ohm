import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(os.environ['RC26_ROOT'])
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == os.environ['RC26_EXPECTED_BOOT']
assert os.getuid() == int(os.environ['RC26_EXPECTED_UID'])
HERE = ROOT / 'frozen351/scripts/driver-bind-21577'
CASE = json.loads((HERE / 'case.json').read_text())
OUT = ROOT / 'input-preparation'
OUT.mkdir()
GIT = ROOT / 'inputs/uv.git'
SOURCE = ROOT / 'source'
git_env = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1')


def run(argv, env=None, stdout=None):
    with (OUT / 'commands.jsonl').open('a') as file:
        file.write(json.dumps([str(value) for value in argv]) + '\n')
    return subprocess.run(argv, env=env, stdout=stdout, stderr=(OUT / 'stderr').open('ab'), check=True)


run(['git', 'init', '--bare', GIT], env=git_env, stdout=(OUT / 'git-init.stdout').open('wb'))
run(['git', '-C', GIT, 'fetch', '--depth=80', '--no-tags', 'https://github.com/astral-sh/uv.git', CASE['B'], 'refs/tags/0.12.13:refs/tags/0.12.13'], env=git_env, stdout=(OUT / 'git-fetch.stdout').open('wb'))
assert subprocess.check_output(['git', '-C', GIT, 'rev-parse', CASE['B'] + '^'], env=git_env, text=True).strip() == CASE['A']
archives = {}
for phase in 'AB':
    expected = json.loads((HERE / f'source-{phase}.json').read_text())
    tree = subprocess.check_output(['git', '-C', GIT, 'rev-parse', CASE[phase] + '^{tree}'], env=git_env, text=True).strip()
    assert tree == expected['actual_tree']
    path = ROOT / f'inputs/source-{phase}.tar.zst'
    archive = subprocess.Popen(['git', '-C', GIT, 'archive', '--format=tar', CASE[phase]], env=git_env, stdout=subprocess.PIPE, stderr=(OUT / f'archive-{phase}.stderr').open('wb'))
    with path.open('xb') as output:
        zipped = subprocess.run(['zstd', '-q', '-1', '-T2'], stdin=archive.stdout, stdout=output, check=True)
    archive.stdout.close()
    assert archive.wait() == 0
    archives[phase] = {'commit': CASE[phase], 'tree': tree, 'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
SOURCE.mkdir()
run(['tar', '-I', 'zstd -dq', '-xf', ROOT / 'inputs/source-A.tar.zst', '-C', SOURCE], stdout=subprocess.DEVNULL)
assert not (SOURCE / '.git').exists()
assert hashlib.sha256((SOURCE / 'Cargo.lock').read_bytes()).hexdigest() == CASE['lock']
for rel, digest in json.loads((HERE / 'source-A.json').read_text())['files'].items():
    assert hashlib.sha256((SOURCE / rel).read_bytes()).hexdigest() == digest
parent = ROOT / 'parent357/sdk/trait-25-production-357'
(ROOT / 'sdk').symlink_to(parent, target_is_directory=True)
for name in ('home', 'cargo-home'):
    (ROOT / name).mkdir()
env = {'HOME': str(ROOT / 'home'), 'CARGO_HOME': str(ROOT / 'cargo-home'), 'CARGO_TARGET_DIR': str(ROOT / 'target'), 'CARGO_NET_OFFLINE': 'true', 'GIT_ALLOW_PROTOCOL': 'file', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_NO_LAZY_FETCH': '1', 'LC_ALL': 'C', 'PATH': str(ROOT / 'sdk/bin') + ':/usr/bin:/bin', 'RUSTC': str(ROOT / 'sdk/bin/rustc'), 'RUSTDOC': str(ROOT / 'sdk/bin/rustdoc')}
cargo = ROOT / 'parent357/sdk/trait-25-owner-formatted/bin/cargo'
assert hashlib.sha256(cargo.read_bytes()).hexdigest() == 'e095525d408717c5ca32f808177e2c0f0620f0d66b2e20ca6077b5bdbd989a87'
fetch_env = dict(env, CARGO_NET_OFFLINE='false', GIT_ALLOW_PROTOCOL='https:file')
for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY', 'ALL_PROXY', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'CURL_CA_BUNDLE', 'REQUESTS_CA_BUNDLE', 'CARGO_HTTP_CAINFO'):
    if name in os.environ:
        fetch_env[name] = os.environ[name]
with (OUT / 'fetch.stdout').open('wb') as stdout:
    command = [str(cargo), 'fetch', '--locked', '--manifest-path', str(SOURCE / 'Cargo.toml')]
    run(command, env=fetch_env, stdout=stdout)
registry = json.loads((HERE / 'registry.json').read_text())['packages']
cache, = (ROOT / 'cargo-home/registry/cache').iterdir()
for filename, row in registry.items():
    path = cache / filename
    assert path.stat().st_size == row['size']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256']
assert hashlib.sha256((SOURCE / 'Cargo.lock').read_bytes()).hexdigest() == CASE['lock']
(OUT / 'environment.json').write_text(json.dumps(env, indent=2) + '\n')
proof = {'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'archives': archives, 'registry_archives': len(registry), 'cargo_sha256': hashlib.sha256(cargo.read_bytes()).hexdigest(), 'source_is_immutable_git_archive_fixture': True, 'input_worker_sha256': hashlib.sha256((ROOT / 'inputs/351-original-worker.zip').read_bytes()).hexdigest()}
(OUT / 'verified.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps(proof))
