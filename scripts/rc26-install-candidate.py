import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

ROOT = Path(os.environ['RC26_ROOT'])
BOOT = os.environ['RC26_EXPECTED_BOOT']
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT and os.getuid() == int(os.environ['RC26_EXPECTED_UID'])
request = json.loads((ROOT / 'inputs/candidate-request.json').read_text())
assert request['run'] == 42107067758 and request['head'] == '405f059f80442e076d69c900805045581d5b9075'
archive = ROOT / 'inputs/ohm-1.99.0-26-x86_64-unknown-linux-gnu.tar.gz'


def sha(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


assert archive.stat().st_size == request['bytes'] and sha(archive) == request['sha256']
out = ROOT / 'candidate-install'
out.mkdir()
dist = ROOT / 'candidate-dist'
dist.mkdir()
prefix = ROOT / 'candidate-sdk'
assert not prefix.exists()
with tarfile.open(archive, 'r:gz') as tar:
    members = tar.getmembers()
    roots = {PurePosixPath(row.name).parts[0] for row in members}
    assert len(roots) == 1
    for member in members:
        path = PurePosixPath(member.name)
        assert not path.is_absolute() and '..' not in path.parts
    tar.extractall(dist, filter='data')
    root, = roots
    driver_members = [row for row in members if row.isfile() and '/lib/librustc_driver-' in row.name and row.name.endswith('.so')]
    assert len(driver_members) == 1
    with tar.extractfile(driver_members[0]) as file:
        driver_source_sha = hashlib.file_digest(file, 'sha256').hexdigest()
env = {'HOME': str(ROOT / 'home'), 'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}
command = [str(dist / root / 'install.sh'), '--prefix=' + str(prefix), '--disable-ldconfig']
with (out / 'stdout').open('xb') as stdout, (out / 'stderr').open('xb') as stderr:
    result = subprocess.run(command, cwd=dist / root, env=env, stdout=stdout, stderr=stderr)
(out / 'command.json').write_text(json.dumps({'command': command, 'env': env, 'exit': result.returncode}, indent=2) + '\n')
assert result.returncode == 0
driver, = prefix.glob('lib/librustc_driver-*.so')
assert sha(driver) == driver_source_sha
banners = {}
for name in ('rustc', 'cargo', 'rustfmt', 'clippy-driver'):
    flag = '-vV' if name in ('rustc', 'cargo') else '--version'
    banners[name] = subprocess.check_output([str(prefix / 'bin' / name), flag], env=env, text=True)
assert 'commit-hash: 9d17d61278fa0e01a092e45aa8126e2c02eb196f' in banners['rustc']
inventory = {}
for path in sorted(prefix.rglob('*')):
    name = str(path.relative_to(prefix))
    if path.is_symlink():
        assert path.resolve().is_relative_to(prefix)
        inventory[name] = {'symlink': os.readlink(path)}
    elif path.is_file():
        inventory[name] = {'bytes': path.stat().st_size, 'mode': path.stat().st_mode & 0o777, 'sha256': sha(path)}
with (out / 'inventory.json').open('x') as file:
    json.dump(inventory, file, indent=2, sort_keys=True)
    file.write('\n')
proof = {'boot': BOOT, 'request': request, 'driver_sha256': sha(driver), 'driver_tar_member': driver_members[0].name, 'banners': banners, 'sdk': str(prefix), 'inventory_sha256': sha(out / 'inventory.json'), 'members': len(inventory)}
with (ROOT / 'candidate-verified.json').open('x') as file:
    json.dump(proof, file, indent=2)
    file.write('\n')
print(json.dumps({'installed': str(prefix), 'driver_sha256': proof['driver_sha256'], 'members': len(inventory), 'passed': True}))
