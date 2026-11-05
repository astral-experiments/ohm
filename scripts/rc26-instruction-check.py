import ast
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import shutil
import statistics
import subprocess
import sys
import time
import tomllib

ROOT = Path(os.environ['RC26_ROOT'])
BOOT = os.environ['RC26_EXPECTED_BOOT']
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT and os.getuid() == int(os.environ['RC26_EXPECTED_UID'])
AFFINITY = sorted(os.sched_getaffinity(0))[:8]
assert len(AFFINITY) == 8
os.sched_setaffinity(0, AFFINITY)
HERE = ROOT / 'frozen351/scripts/driver-bind-21577'
SOURCE, TARGET = ROOT / 'source', ROOT / 'target'
OUT = ROOT / 'native-instruction-results'
OUT.mkdir(exist_ok=True)
ENV = json.loads((ROOT / 'input-preparation/environment.json').read_text())
CASE = json.loads((HERE / 'case.json').read_text())
CARGO = ROOT / 'parent357/sdk/trait-25-owner-formatted/bin/cargo'
COMMAND = [str(CARGO), 'check', '-p', 'uv-warnings', '--lib', '--locked', '--offline', '-j8']
NORMALIZE = runpy.run_path(str(HERE.parent / 'uv-check-21134/sessions.py'))['inventory']
EXPECTED = {'uv_errors', 'uv_warnings'}


def sha(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def save(path, value):
    with path.open('x') as file:
        json.dump(value, file, indent=2, sort_keys=True)
        file.write('\n')


def select(role):
    sdk = ROOT / ('parent357/sdk/trait-25-production-357' if role == 'baseline' else 'candidate-sdk')
    expected = '6ab4bae4bc84fec24043384f4de3de08f48d781891144707c0f8c37ab0495590' if role == 'baseline' else json.loads((ROOT / 'candidate-verified.json').read_text())['driver_sha256']
    driver, = sdk.glob('lib/librustc_driver-*.so')
    assert sha(driver) == expected and sha(CARGO) == 'e095525d408717c5ca32f808177e2c0f0620f0d66b2e20ca6077b5bdbd989a87'
    link = ROOT / 'sdk'
    assert link.is_symlink() and link.resolve().is_relative_to(ROOT)
    link.unlink()
    link.symlink_to(sdk, target_is_directory=True)
    banner = subprocess.check_output([str(link / 'bin/rustc'), '-vV'], env=ENV, text=True)
    expected_source = 'e87d0573445ccd21818f319a15d126ac0c4362c2' if role == 'baseline' else '9d17d61278fa0e01a092e45aa8126e2c02eb196f'
    assert 'commit-hash: ' + expected_source in banner
    return {'role': role, 'sdk': str(sdk), 'driver_sha256': expected, 'source': expected_source, 'banner': banner, 'cargo_sha256': sha(CARGO), 'affinity': AFFINITY}


def phase(which):
    assert which in 'AB'
    wanted = json.loads((HERE / f'source-{which}.json').read_text())
    other = json.loads((HERE / f'source-{"B" if which == "A" else "A"}.json').read_text())
    for name, digest in wanted['files'].items():
        path = SOURCE / name
        assert sha(path) in (digest, other['files'][name])
        if sha(path) != digest:
            content = subprocess.check_output(['git', '-C', str(ROOT / 'inputs/uv.git'), 'show', CASE[which] + ':' + name], env=ENV)
            assert hashlib.sha256(content).hexdigest() == digest
            path.write_bytes(content)
    assert sha(SOURCE / 'Cargo.lock') == CASE['lock']


def command(path, argv=COMMAND, trace=True, cwd=SOURCE, env=ENV):
    path.mkdir(parents=True)
    actual = list(map(str, argv))
    if trace:
        actual = ['strace', '-f', '-z', '-s', '131072', '-e', 'trace=execve', '-o', str(path / 'execve.log'), '--', *actual]
    start = time.time_ns()
    with (path / 'stdout').open('xb') as out, (path / 'stderr').open('xb') as err:
        result = subprocess.run(actual, cwd=cwd, env=env, stdout=out, stderr=err)
    save(path / 'command.json', {'argv': actual, 'cwd': str(cwd), 'env': env, 'start_ns': start, 'finish_ns': time.time_ns(), 'exit': result.returncode})
    assert result.returncode == 0, (path, result.returncode)
    if not trace:
        return None
    images = []
    for line in (path / 'execve.log').read_text().splitlines():
        match = re.search(r'execve\("(?:[^"\\]|\\.)*", (\[.*\]), .*\) = 0$', line)
        if match:
            images.append(ast.literal_eval(match[1]))
    assert images and images[0] == list(map(str, argv))
    compiled = [args for args in images if '--crate-name' in args and any(part.startswith('--emit=') for part in args)]
    names = [args[args.index('--crate-name') + 1] for args in compiled]
    save(path / 'images.json', {'all': images, 'compilers': compiled, 'crates': names})
    return names


def surface(path):
    path.mkdir(exist_ok=True)
    blobs = OUT / 'blobs'
    blobs.mkdir(exist_ok=True)
    raw = {}
    for file in sorted(TARGET.rglob('*.rmeta')):
        digest = sha(file)
        raw[str(file.relative_to(TARGET))] = [file.stat().st_size, digest]
        stored = blobs / (digest + '.rmeta.gz')
        if not stored.exists():
            stored.write_bytes(gzip.compress(file.read_bytes(), mtime=0))
    normalized, literal = NORMALIZE(raw)
    sidecars = {}
    for file in sorted(TARGET.rglob('*.public-api-hash')):
        digest = sha(file)
        sidecars[str(file.relative_to(TARGET))] = [file.stat().st_size, digest]
        stored = blobs / (digest + '.public-api-hash')
        if not stored.exists():
            stored.write_bytes(file.read_bytes())
    assert len(normalized) == 39 and len(sidecars) == 30, (len(normalized), len(sidecars))
    value = {'rmeta': normalized, 'sidecars': sidecars}
    save(path / 'products.json', value)
    save(path / 'literal-paths.json', literal)
    return value


def clear_target():
    assert TARGET.parent == ROOT and not TARGET.is_symlink()
    if TARGET.exists():
        shutil.rmtree(TARGET)


def snapshot(path):
    assert not path.exists()
    subprocess.run(['tar', '--format=pax', '--xattrs', '--acls', '-I', 'zstd -q -1 -T2', '-cf', str(path), '-C', str(ROOT), 'target'], check=True)
    return {'bytes': path.stat().st_size, 'sha256': sha(path)}


def restore(path, proof):
    assert path.stat().st_size == proof['bytes'] and sha(path) == proof['sha256']
    clear_target()
    subprocess.run(['tar', '--xattrs', '--acls', '-I', 'zstd -dq', '-xf', str(path), '-C', str(ROOT)], check=True)


def behavior(out, resume=False):
    package = out / 'behavior-case'
    (package / 'src').mkdir(parents=True, exist_ok=resume)
    manifest = '[package]\nname="warning-order-witness"\nversion="0.0.0"\nedition="2024"\n[dependencies]\n'
    for name in ('uv-errors', 'uv-warnings'):
        manifest += name + '={path=' + json.dumps(str(SOURCE / 'crates' / name)) + '}\n'
    if resume:
        assert (package / 'Cargo.toml').read_text() == manifest
        assert sha(package / 'Cargo.lock') == CASE['lock']
        assert json.loads((out / 'behavior-metadata/command.json').read_text())['exit'] == 101
    else:
        (package / 'Cargo.toml').write_text(manifest)
        shutil.copyfile(SOURCE / 'Cargo.lock', package / 'Cargo.lock')
    phase('A')
    shutil.copyfile(HERE / 'behavior-A.rs', package / 'src/main.rs')
    env = dict(ENV, CARGO_TARGET_DIR=str(out / 'behavior-target'), CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_DEV_INCREMENTAL='false')
    command(out / ('behavior-metadata-resume' if resume else 'behavior-metadata'), [CARGO, 'metadata', '--offline', '--format-version=1'], trace=False, cwd=package, env=env)
    packages = lambda path: {(row['name'], row['version'], row.get('source'), row.get('checksum')) for row in tomllib.loads(path.read_text())['package']}
    actual = {row for row in packages(package / 'Cargo.lock') if row[0] != 'warning-order-witness'}
    assert len(actual) == 53 and actual <= packages(SOURCE / 'Cargo.lock')
    results = {}
    for which in 'AB':
        phase(which)
        shutil.copyfile(HERE / f'behavior-{which}.rs', package / 'src/main.rs')
        command(out / f'behavior-{which}', [CARGO, 'build', '--locked', '--offline', '-j4', '--message-format=json'], trace=False, cwd=package, env=env)
        events = [json.loads(line) for line in (out / f'behavior-{which}/stdout').read_bytes().splitlines() if line.startswith(b'{')]
        executable, = [row['executable'] for row in events if row.get('target', {}).get('name') == 'warning-order-witness']
        result = subprocess.run([executable], env=env, capture_output=True)
        (out / f'behavior-{which}/program.stdout').write_bytes(result.stdout)
        (out / f'behavior-{which}/program.stderr').write_bytes(result.stderr)
        assert result.returncode == 0 and not result.stdout
        assert all(result.stderr.count(text) == 1 for text in (b'original warning', b'general-last', b'specific-first'))
        assert (result.stderr.index(b'general-last') < result.stderr.index(b'specific-first')) == (which == 'A')
        results[which] = {'executable_sha256': sha(Path(executable)), 'output': result.stderr.decode(), 'fixture_sha256': sha(package / 'src/main.rs')}
    save(out / 'behavior.json', results)


def opening(role, history):
    selected = select(role)
    out = OUT / f'history-{history}' / role
    out.mkdir(parents=True)
    save(out / 'selected.json', selected)
    phase('A')
    clear_target()
    assert command(out / 'cold-A')
    before = surface(out / 'cold-A')
    assert command(out / 'unchanged-A') == []
    seed = out / 'seed-A.tar.zst'
    frozen = snapshot(seed)
    save(out / 'seed.json', frozen)
    phase('B')
    assert set(command(out / 'first-B')) == EXPECTED
    warm = surface(out / 'first-B')
    assert command(out / 'unchanged-B') == []
    clear_target()
    assert command(out / 'cold-B')
    cold = surface(out / 'cold-B')
    assert cold == warm, (out, 'cold B differs from ordinary first edit')
    assert command(out / 'unchanged-cold-B') == []
    behavior(out)
    save(out / 'verified.json', {'selected': selected, 'seed': frozen, 'before': before, 'after': warm, 'source_before': CASE['A'], 'source_after': CASE['B'], 'same_cold_and_warm_B': True})
    print(json.dumps({'opening': role, 'history': history, 'passed': True}), flush=True)


def counted(role, history, pair):
    selected = select(role)
    opening_path = OUT / f'history-{history}' / role
    proof = json.loads((opening_path / 'verified.json').read_text())
    assert proof['selected'] == selected
    phase('B')
    restore(opening_path / 'seed-A.tar.zst', proof['seed'])
    path = OUT / 'pairs' / str(pair) / role
    path.mkdir(parents=True)
    meter = ROOT / 'inputs/native-counter'
    args = [str(meter), str(path / 'counter.json'), '--', *COMMAND]
    assert set(command(path / 'run', args)) == EXPECTED
    counter = json.loads((path / 'counter.json').read_text())
    assert counter['raw_wait_status'] == 0 and counter['instructions'] > 0
    assert counter['time_enabled'] == counter['time_running'] > 0
    images = json.loads((path / 'run/images.json').read_text())['all']
    native = json.loads((opening_path / 'first-B/images.json').read_text())['all']
    assert images[0] == args
    assert sorted(map(tuple, images[1:])) == sorted(map(tuple, native))
    assert surface(path) == proof['after']
    assert command(path / 'unchanged-B') == []
    result = {'role': role, 'history': history, 'pair': pair,
              'whole_cargo_instructions': counter['instructions'],
              'counter': counter, 'selected': selected,
              'meter_sha256': sha(meter), 'native_process_graph_matches': True}
    save(path / 'counted.json', result)
    print(json.dumps({key: result[key] for key in ('role', 'history', 'pair', 'whole_cargo_instructions')}), flush=True)


if __name__ == '__main__':
    history = int(sys.argv[1])
    assert history in (1, 2)
    for role in ('baseline', 'treatment'):
        opening(role, history)
    orders = [('baseline', 'treatment'), ('treatment', 'baseline')] * 2
    if history == 2:
        orders = [tuple(reversed(order)) for order in orders]
    results = []
    for index, order in enumerate(orders, 1):
        pair = index + 4 * (history - 1)
        for role in order:
            counted(role, history, pair)
        a, b = [json.loads((OUT / 'pairs' / str(pair) / role / 'counted.json').read_text()) for role in ('baseline', 'treatment')]
        results.append({'pair': pair, 'history': history, 'baseline': a['whole_cargo_instructions'],
                        'treatment': b['whole_cargo_instructions'], 'ratio': b['whole_cargo_instructions'] / a['whole_cargo_instructions']})
    assert all(row['ratio'] < 1 for row in results), results
    save(OUT / 'verified.json', {'metric': 'Native PMU user-space instructions, Cargo and all descendants',
                               'boot': BOOT, 'history': history, 'pairs': results,
                               'median_reduction': 1 - statistics.median(row['ratio'] for row in results),
                               'wall_time_gate': False, 'scaled': False})
    print((OUT / 'verified.json').read_text(), flush=True)
