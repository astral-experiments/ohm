"""One real GNU linker namespace, one Ruff test target, one source-built compiler."""
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path[:0] = [str(HERE), str(BASE / 'ohm-gnu-atomic-db'), str(BASE / 'ohm-gnu-ty-input-census')]
import census
import screen
import sdk
from observe import save, sha, sha_bytes, stat_id, trace

CMD = ['cargo', '+ohm', 'test', '-p', 'ruff_db', '--lib', '--no-run', '--target', census.TARGET,
       '--locked', '--offline', '-j4', '--message-format=json']
STATES = ('absent', 'higher83', 'same-stamp47', 'malformed', 'removed')
EXIT = {'absent': 0, 'higher83': 83, 'same-stamp47': 47, 'malformed': None, 'removed': 0}


def run(argv, src, env):
    return subprocess.run(list(map(str, argv)), cwd=src, env=env, capture_output=True, timeout=180)


def protect_registry(env):
    registry = Path(env['CARGO_HOME']) / 'registry'
    archives = {}
    for key in ('cache', 'src', 'index'):
        where = registry / key
        assert where.is_dir()
        for p in [where, *where.rglob('*')]:
            if not p.is_symlink():
                p.chmod(stat.S_IMODE(p.stat().st_mode) & ~0o222)
            if key == 'cache' and p.name.endswith('.crate'):
                archives[str(p.relative_to(registry))] = sha(p)
    assert archives
    return archives


def qemu(program, option, cwd, env, dest, name):
    argv = ['qemu-aarch64', '-L', '/usr/aarch64-linux-gnu', str(program), *option]
    p = run(argv, cwd, env)
    census.blob(dest / (name + '.stdout.gz'), p.stdout)
    census.blob(dest / (name + '.stderr.gz'), p.stderr)
    return {'argv': argv, 'exit': p.returncode, 'stdout': sha_bytes(p.stdout), 'stderr': sha_bytes(p.stderr)}, p.stdout


def qemu_test(exe, src, env, dest):
    cwd = src / 'crates/ruff_db'
    obs, text = qemu(exe, ['--list', '--format', 'terse'], cwd, env, dest, 'list')
    tests = sorted(x.removesuffix(': test') for x in text.decode().splitlines() if x.endswith(': test'))
    checks = {}
    if obs['exit'] == 0:
        for n in tests:
            short = n.rsplit('::', 1)[-1]
            if short in screen.ADDED | {screen.CONTROL}:
                r, out = qemu(exe, ['--exact', n, '--test-threads=1'], cwd, env, dest, short)
                checks[short] = [r, b'1 passed; 0 failed' in out]
    return {'list': obs, 'tests': tests, 'checks': checks}


def file_read(opens, p, success):
    exact = []
    for o in opens:
        req = Path(o['path'])
        if not req.is_absolute():
            continue
        if success:
            if o['fd'] >= 0 and (req == p or req.resolve() == p.resolve()):
                exact.append(o['line'])
        elif req == p and o['fd'] == -1 and o['errno'] == 'ENOENT':
            exact.append(o['line'])
    return exact


def retained(exe, out):
    raw = exe.read_bytes()
    assert raw[:7] == bytes.fromhex('7f454c46020101') and raw[18:20] == b'\xb7\x00'
    h = sha_bytes(raw)
    z = out / 'elf' / (h + '.zst')
    z.parent.mkdir(exist_ok=True)
    if not z.exists():
        subprocess.run(['zstd', '-q', '-T1', '-3', str(exe), '-o', str(z)], check=True)
        assert sha_bytes(subprocess.check_output(['zstd', '-qdc', z])) == h
    return {'path': str(exe), 'sha256': h, 'size': len(raw), 'zstd_sha256': sha(z)}


def mark(slot, state, contents):
    assert not slot.is_symlink()
    if state in ('absent', 'removed'):
        if slot.exists():
            assert slot.read_bytes() in contents.values()
            slot.unlink()
        return None
    if not slot.exists():
        slot.parent.mkdir(parents=True, exist_ok=True)
        with slot.open('xb') as dest:
            dest.write(contents[state])
        return stat_id(slot)
    assert slot.is_file() and slot.read_bytes() in contents.values()
    prior = stat_id(slot)
    atime = slot.stat().st_atime_ns
    with slot.open('r+b') as dest:
        dest.write(contents[state])
        dest.flush()
        os.fsync(dest.fileno())
    os.utime(slot, ns=(atime, prior[3]))
    after = stat_id(slot)
    assert prior[:4] == after[:4] and prior[4] != after[4], (prior, after)
    return after


def make_inputs(work, out, src, env):
    support = work / 'provider'
    support.mkdir()
    manifest = {}
    gcc = Path('/usr/bin/aarch64-linux-gnu-gcc')
    lower = Path(census.command([gcc, '-print-file-name=libgcc_s.so'], src, env))
    assert lower.is_absolute() and lower.is_file() and not lower.is_relative_to(work)
    manifest['lower'] = {'path': str(lower), 'canonical': str(lower.resolve()), 'id': stat_id(lower)}
    artifacts = out / 'provider-bytes'
    artifacts.mkdir()
    for name, binary in [('gcc', gcc), ('qemu', Path(shutil.which('qemu-aarch64')))]:
        manifest[name] = [str(binary.resolve()), *stat_id(binary)]
    shutil.copyfile(HERE / 'provider.S', artifacts / 'provider.S')
    shutil.copyfile(lower, artifacts / 'system-libgcc_s.input')
    assembled = []
    for value in (83, 47):
        obj = support / f'p{value}.o'
        cmd = [gcc, '-c', f'-DEXIT_CODE={value}', HERE / 'provider.S', '-o', obj]
        subprocess.run(cmd, cwd=src, env=env, check=True)
        data = obj.read_bytes()
        assert data[:7] == bytes.fromhex('7f454c46020101') and data[18:20] == b'\xb7\x00'
        shutil.copyfile(obj, artifacts / obj.name)
        assembled.append(len(data))
        manifest[str(value)] = {'object': str(obj), 'sha256': sha(obj), 'size': len(data),
                                'assembler_command': list(map(str, cmd))}
    assert assembled[0] == assembled[1] and manifest['83']['sha256'] != manifest['47']['sha256']
    assert all(not re.search(r'[\s()"]', str(p)) for p in (lower, support))
    args = lambda n: f'INPUT ( {support}/p{n}.o {lower} )\n'.encode()
    contents = {'higher83': args(83), 'same-stamp47': args(47)}
    malformed = b'OHM_RUFF_SHADOW_MALFORMED (\n'
    contents['malformed'] = malformed.ljust(len(args(83)), b' ')
    assert len({len(v) for v in contents.values()}) == 1
    for k, data in contents.items():
        (artifacts / (k + '.script')).write_bytes(data)
    small = support / 'mini'
    small.mkdir()
    (small / 'main.c').write_text('int main(void) { return 0; }\n')
    control = {}
    for state in STATES:
        slot = small / 'libgcc_s.so'
        st = mark(slot, state, contents)
        exe = small / 'exe'
        p = run([gcc, small / 'main.c', '-L' + str(small), '-Wl,--as-needed', '-lgcc_s', '-o', exe], src, env)
        row = {'link': p.returncode, 'slot': st, 'stderr': p.stderr.decode(errors='replace')}
        if not p.returncode:
            row['qemu'], _ = qemu(exe, [], src, env, artifacts, 'mini-' + state)
            row['sha256'] = sha(exe)
        control[state] = row
    save(artifacts / 'preflight.json', {'inputs': manifest, 'states': control})
    for s in STATES:
        assert (control[s]['link'] != 0 and 'libgcc_s.so' in control[s]['stderr']) if s == 'malformed' else (
            control[s]['link'] == 0 and control[s]['qemu']['exit'] == EXIT[s]), (s, control[s])
    assert control['absent']['sha256'] == control['removed']['sha256']
    return lower, contents, manifest


def main():
    work, out, src, env = sdk.acquire('C', CMD)
    assert shutil.disk_usage(work).free > 12 * 1024**3
    lower, contents, identity = make_inputs(work, out, src, env)
    roots = tuple(Path(env[k]) for k in ('CARGO_TARGET_DIR', 'CARGO_BUILD_BUILD_DIR'))
    assert roots == (work / 'target', work / 'shared')
    slot = None
    status = {}

    def visit(label, state, family, owner=None, old=False):
        nonlocal slot
        at = out / 'visits' / label
        if slot is not None:
            before = mark(slot, state, contents)
        else:
            before = None
            assert state == 'absent'
        assert shutil.disk_usage(work).free > 5 * 1024**3
        p, messages, kernel, ld, opens = trace(CMD, src, env, at)
        if ld:
            a = ld['argv']
            search, = [Path(v[2:]) for v in a if v.startswith('-L') and '/psm/' in v and v.endswith('/out')]
            observed = search / 'libgcc_s.so'
            assert any(observed.is_relative_to(x) for x in roots) and search.is_dir()
            assert slot is None or observed == slot, (slot, observed)
            slot = observed
            assert '-lgcc_s' in a and len([v for v in a if v.startswith('-L')]) >= 2
        assert slot is not None
        row = {'family': family, 'state': state, 'exit': p.returncode, 'pre_slot': before,
               'post_slot': stat_id(slot) if slot.is_file() else None, 'slot_path': str(slot),
               'typed': sum(v.get('reason') == 'compiler-artifact' for v in messages),
               'rustcs': [[v['crate'], v['link_only'], v['pid'], v['terminal']] for v in kernel['rustcs']],
               'root_ld': None if not ld else [ld['pid'], ld['path'], ld['terminal']],
               'missing': file_read(opens, slot, False), 'selected': file_read(opens, slot, True),
               'lower_selected': file_read(opens, lower, True), 'invalid_text': False,
               'forced_short': owner, 'product': None, 'qemu': None}
        if p.returncode == 0:
            selected, = [m['executable'] for m in messages if m.get('reason') == 'compiler-artifact' and
                         m['target']['name'] == 'ruff_db' and m['target']['kind'] == ['lib'] and
                         m['profile']['test'] and m['executable']]
            row['product'] = retained(Path(selected), out)
            row['qemu'] = qemu_test(Path(selected), src, env, at)
        else:
            text = p.stderr.decode(errors='replace') + '\n' + '\n'.join(
                m['message'].get('rendered') or '' for m in messages if m.get('reason') == 'compiler-message')
            row['invalid_text'] = 'libgcc_s.so' in text and ('syntax error' in text or 'file format not recognized' in text)
        save(at / 'verdict.json', row)
        status[label] = row
        print(label, 'cargo', row['exit'], 'typed', row['typed'], 'qemu', (row['qemu'] or {}).get('list', {}).get('exit'),
              'ld', row['root_ld'], 'negative', len(row['missing']), 'selected', len(row['selected']), flush=True)
        if old:
            assert row['qemu']['list']['exit'] == 0 and len(row['qemu']['tests']) == 126

    visit('training-old', 'absent', 'training', old=True)
    registry = protect_registry(env)
    save(out / 'registry.json', registry)
    census.command(['git', 'restore', '--source', screen.NEW, '--staged', '--worktree', '--', '.'], src, env)
    assert census.command(['git', 'write-tree'], src, env) == screen.TREES[screen.NEW]
    visit('training-edit', 'absent', 'training')
    for state in STATES:
        visit('ordinary-' + state, state, 'ordinary')
    previous_markers = []
    for state in STATES:
        # An unsuccessful *forced* compile may leave its previously removed marker absent.
        matches = sorted(p for root in roots if root.exists() for p in root.rglob('test-lib-ruff_db')
                         if p.is_file() and not p.is_symlink() and p.with_suffix('.json').is_file())
        removed = []
        if matches:
            for f in matches:
                data = f.read_bytes()
                assert re.fullmatch(rb'[0-9a-f]{16}', data) or data == b'', (f, data)
                removed.append([str(f), data.decode()])
                f.unlink()
            previous_markers = matches
        else:
            assert state == 'removed' and status['forced-malformed']['exit'] == 101
            assert previous_markers and all(not os.path.lexists(f) for f in previous_markers)
            removed = [[str(f), None] for f in previous_markers]
        visit('forced-' + state, state, 'forced', removed)
    for state in STATES:
        for r in roots:
            assert not r.is_symlink() and r.parent == work
            if r.exists():
                shutil.rmtree(r)
        assert all(not r.exists() for r in roots)
        visit('empty-' + state, state, 'empty')
    assert sha(lower) == identity['lower']['id'][-1]
    assert all(sha(Path(env['CARGO_HOME']) / 'registry' / name) == h for name, h in registry.items())
    expected_sdk = json.loads((sdk.preparation()[0] / 'C-sdk.json').read_text())
    actual_sdk = sdk.preparation()[2]
    assert {p.relative_to(actual_sdk).as_posix(): [sha(p), p.stat().st_size, p.stat().st_mode & 0o777]
            for p in actual_sdk.rglob('*') if p.is_file()} == expected_sdk
    save(out / 'observation.json', {'cmd': CMD, 'compiler': sdk.SOURCE['candidate'], 'states': STATES,
                                    'system_provider': identity['lower'], 'rows': status})
    from verify import verify_rows
    result = verify_rows(status)
    save(out / 'terminal.json', result)
    print(json.dumps(result), flush=True)
    assert not result['failures']


if __name__ == '__main__':
    main()
