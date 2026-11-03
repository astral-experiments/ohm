"""One unscored P/C admission on Ruff #19021's ordinary test-build command."""
import collections
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import tomllib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import native_asm as kit

w = kit.w
REG = json.loads((HERE / 'native-test-registration.json').read_bytes())
CONFIRM = json.loads((HERE / 'native-test-confirmation.json').read_bytes())
CMD = REG['command']
PLATFORM = 'x86_64-unknown-linux-gnu'
PKG = w.work / 'crates/ruff_linter'
FIXTURE = 'crates/ruff_linter/resources/test/fixtures/ruff/RUF009_attrs.py'
SNAP = 'crates/ruff_linter/src/rules/ruff/snapshots/ruff_linter__rules__ruff__tests__RUF009_RUF009_attrs.py.snap'
EDIT = 'crates/ruff_linter/src/rules/ruff/helpers.rs'
TESTS = ('test', 'benchmark')
MARKER = b'/dev/null/ohm-untracked-relink-inputs:'
TOOLS = w.root / 'qa-tools'
LIMIT_NS = 15 * 60 * 1_000_000_000


def write(path, obj):
    with path.open('x') as out:
        json.dump(obj, out, sort_keys=True, indent=1)
        out.write('\n')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def command(argv, cwd, env, dst):
    w.guard()
    start = time.monotonic_ns()
    with (dst / 'stdout').open('xb') as out, (dst / 'stderr').open('xb') as err:
        child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True)
        try:
            while child.poll() is None:
                w.guard()
                if time.monotonic_ns() - start > LIMIT_NS:
                    raise RuntimeError('per-command time limit')
                time.sleep(0.25)
        finally:
            if child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                child.wait()
    return child.returncode


def artifacts(destination):
    """Measure physical stored files once per inode, excluding the separate QA archives."""
    out = collections.defaultdict(lambda: [0, 0])
    seen = set()
    ledger = []
    for root in (w.target, w.shared):
        for parent, dirs, files in os.walk(root):
            for file in files:
                path = Path(parent) / file
                st = path.lstat()
                if path.is_symlink() or (st.st_dev, st.st_ino) in seen:
                    continue
                seen.add((st.st_dev, st.st_ino))
                groups = out[path.suffix if path.suffix in ('.o', '.rlib', '.rmeta', '.rlink') else 'other']
                groups[0] += 1
                groups[1] += st.st_size
                ledger.append([str(path.relative_to(w.root)), st.st_dev, st.st_ino, st.st_size, st.st_blocks * 512])
    (destination / 'stored-files.json.gz').write_bytes(gzip.compress(json.dumps(ledger, separators=(',', ':')).encode(), mtime=0))
    return dict(out)


def sources():
    return {p: w.hf(w.work / p) for p in (FIXTURE, SNAP, EDIT, 'Cargo.lock')}


def harness(exe, evidence, env, wrong=False):
    # Test execution and snapshots always occur after the timed Cargo process exits.
    tenv = dict(env, INSTA_UPDATE='no', INSTA_FORCE_PASS='0', INSTA_OUTPUT='diff', INSTA_WORKSPACE_ROOT=str(w.work), NO_COLOR='1')
    listed = subprocess.run([exe, '--list', '--format', 'terse'], cwd=PKG, env=tenv, check=True, capture_output=True)
    assert not listed.stderr
    inventory = listed.stdout
    rows = [line.rsplit(': ', 1) for line in inventory.decode().splitlines() if line.strip()]
    assert len(rows) > 300 and all(len(row) == 2 and row[1] in TESTS for row in rows)
    assert len({x[0] for x in rows}) == len(rows)
    named, = [row[0] for row in rows if row[0].startswith('rules::ruff::tests::rules::') and 'ruf009_attrs_py' in row[0].lower()]
    shared = w.proof / (sha(inventory) + '.test-names')
    if not shared.is_file():
        shared.write_bytes(inventory)
    assert shared.read_bytes() == inventory
    actual = subprocess.run([exe, '--exact', named, '--nocapture', '--color', 'never'], cwd=PKG, env=tenv, capture_output=True, timeout=90)
    raw = actual.stdout + b'\n' + actual.stderr
    (evidence / 'named.stdout').write_bytes(actual.stdout)
    (evidence / 'named.stderr').write_bytes(actual.stderr)
    assert named.encode() in raw and b'running 1 test' in raw
    if wrong:
        assert actual.returncode == 101 and b'0 passed; 1 failed;' in raw, raw[-2500:]
        assert b'RUF009_attrs.py' in raw and b'snapshot' in raw
        assert any(token in raw for token in (b'attr_field_factory', b'attr_field_default', b'attr_attrib')), raw[-4000:]
        assert b'RUF009_attrs.py:144:20' in raw or b'TestAttrAttributes' in raw, raw[-4000:]
    else:
        assert actual.returncode == 0 and b'1 passed; 0 failed;' in raw, raw[-2100:]
    assert not w.git('status', '--porcelain'), w.git('status', '--porcelain')
    return dict(name=named, count=len(rows), inventory=sha(inventory), code=actual.returncode, stdout=sha(actual.stdout), stderr=sha(actual.stderr))


def checkout(rev):
    w.git('switch', '--detach', rev)
    assert w.git('rev-parse', 'HEAD') == rev and not w.git('status', '--porcelain')
    assert sources() == REG['source'][rev] and w.hf(w.work / 'Cargo.lock') == w.OLDLOCK


def entries(work):
    """Authenticate the newly filled private registry, including unused locked package archives."""
    locked = tomllib.loads((w.work / 'Cargo.lock').read_text())['package']
    archive = {(p['name'], p['version']): p['checksum'] for p in locked if p.get('source', '').startswith('registry+')}
    assert len(archive) == 445
    caches = list((w.home / 'registry/cache').glob('*/*.crate'))
    assert len(caches) == 445
    want = {n + '-' + v + '.crate': digest for (n, v), digest in archive.items()}
    assert {p.name: w.hf(p) for p in caches} == want
    git_repos = set()
    for folder in (w.home / 'git/checkouts').glob('*/*'):
        if (folder / '.git').exists():
            git_repos.add(subprocess.check_output(['git', '-C', folder, 'rev-parse', 'HEAD'], text=True).strip())
    assert git_repos == {p['source'].split('#')[-1] for p in locked if p.get('source', '').startswith('git+')}, git_repos
    write(work / 'private-inputs.json', {'crates': want, 'git': sorted(git_repos), 'source': sources()})


def start(role, history, env, rev):
    assert not any(p.exists() for p in (w.home, w.shared, w.target))
    checkout(rev)
    d = w.proof / f'{role}-{history}'; d.mkdir()
    e = dict(env); e.pop('CARGO_NET_OFFLINE')
    p = command(['cargo', '+ohm', 'fetch', '--locked'], w.work, e, d)
    assert p == 0, (d / 'stderr').read_text()[-700:]
    entries(d)
    assert all(not any(base.rglob("*.rlib")) and not any(base.rglob("*.rmeta")) for base in (w.target, w.shared))


def clear():
    # Only the disposable, mutually independent experiment roots on this runner.
    for path in (w.target, w.shared, w.home):
        assert path.parent == w.root and path.is_dir() and not path.is_symlink()
        shutil.rmtree(path)


def roster(directory, env):
    wild = (w.sdk / 'lib/rustlib' / PLATFORM / 'bin/wild-ld/ld.bfd')
    identities = {}
    for label, exe in [('rustc', w.sdk / 'bin/rustc'), ('cargo', w.sdk / 'bin/cargo'), ('wild', wild)]:
        st = exe.stat(); identities[(st.st_dev, st.st_ino)] = label
    rows = []
    for entry in (directory / 'epochs.tsv').read_text().splitlines():
        if not entry.startswith('I ') or not entry.endswith(' exec'):
            continue
        _, seq, tgid, tid, clock, _ = entry.split()
        nul = directory / f'{int(seq):05d}.nul'
        fields = nul.read_bytes().split(b'\0'); assert fields[-1] == b'' and int(fields[0]) == int(tgid) == int(tid)
        path = Path(os.fsdecode(fields[3]))
        role = identities.get((int(fields[1]), int(fields[2])), path.name)
        args = [os.fsdecode(s) for s in fields[4:-1]]
        owner = args[args.index('--crate-name') + 1] if '--crate-name' in args else None
        mode = None
        if role == 'rustc':
            mode = 'link-only' if any('link-only' in s for s in args) or any(s.endswith('.rlink') for s in args) else 'test' if '--test' in args else 'full' if owner else 'config'
        output = args[args.index('-o') + 1] if '-o' in args else None
        rows.append(dict(role=role, crate=owner, mode=mode, path=str(path), output=output, pid=int(tgid), dev=int(fields[1]), ino=int(fields[2]), argv=nul.name, sha256=w.hf(nul)))
    assert sum(r['role'] == 'cargo' for r in rows) == 1
    return rows


def marker():
    # Several compiler depfiles can coexist. Preserve exactly the external portable-atomic paths.
    files = []
    for base in (w.target, w.shared):
        for path in base.rglob('portable_atomic*.d'):
            raw = path.read_bytes()
            if b'portable-atomic-1.11.0/' in raw and path.stat().st_size < 2**21:
                hash_ = sha(raw); sink = w.proof / (hash_ + '.dep-info')
                if not sink.is_file():
                    sink.write_bytes(raw)
                files.append([str(path), hash_, MARKER in raw.splitlines()])
    return files


def phase(role, name, env, mode, negative=False):
    dest = w.proof / f'{role}-{name}'; dest.mkdir()
    actual = list(CMD)
    hw = dest / 'whole.json'
    if mode == 'whole':
        actual = [str(TOOLS / 'whole_count'), str(hw), shutil.which('cargo', path=env['PATH']), *CMD]
    if mode == 'census':
        tasks = dest / 'tasks'; tasks.mkdir()
        wild = w.sdk / 'lib/rustlib' / PLATFORM / 'bin/wild-ld/ld.bfd'
        actual = [str(TOOLS / 'exec_count'), '--link-inputs', str(wild), sys.executable, str(HERE / 'test_link_inputs.py'), str(tasks), *CMD]
    status = command(actual, w.work, env, dest)
    err = (dest / 'stderr').read_text()
    matches = re.findall(r'^\s*Executable unittests src/lib\.rs \(([^\n]+)\)\s*$', err, re.M)
    if negative:
        assert status == 101 and not matches and re.search(r'error\[E0308\]:', err), err[-1200:]
        result = dict(status=status, sources=sources(), accepted_test_executables=matches)
        write(dest / 'result.json', result)
        return result
    assert status == 0 and len(matches) == 1, (name, status, err[-1400:])
    exe = (w.work / matches[0]).resolve(strict=True)
    assert exe.is_relative_to(w.target) or exe.is_relative_to(w.shared)
    with exe.open('rb') as f: assert f.read(6) == b'\x7fELF\x02\x01'
    state = w.git('rev-parse', 'HEAD')
    result = dict(state=state, sources=sources(), executable=str(exe), elf=w.hf(exe), bytes=exe.stat().st_size,
                  harness=harness(exe, dest, env), nominal=sorted(re.findall(r'^\s*(?:Compiling|Checking) (\S+) v(\S+)', err, re.M)))
    if mode == 'whole':
        clock = json.loads(hw.read_bytes())
        result['clock'] = clock
        result['clock_ok'] = clock['status'] == 0 and clock['instructions'] > 0 and clock['running'] == clock['enabled'] > 0
    if mode == 'census':
        result['roster'] = roster(tasks, env)
        result['native'] = [p.name for p in sorted(tasks.glob('*.wild.json'))]
        assert len(result['native']) == sum(r['role'] == 'wild' and r['output'] is not None and re.fullmatch(r'ruff_linter(?:-[0-9a-f]+)?', Path(r['output']).name) is not None for r in result['roster'])
    if name in ('old', 'edit', 'warm2', 'repair', 'clean', 'census-edit', 'census-cold', 'census-warm'):
        result['binary'] = kit.preserve(exe)
        result['portable'] = marker()
        if name in ('old', 'warm2', 'clean'):
            result['stored_native'] = artifacts(dest)
    write(dest / 'result.json', result)
    print(role, name, 'verdict', result['harness']['code'], 'elf', result['elf'], 'nominal', len(result['nominal']), 'hardware', 'saved' if mode == 'whole' else mode, flush=True)
    return result


def stale(role, env, old):
    d = w.proof / f'{role}-withheld'; d.mkdir()
    exe = Path(old['executable'])
    assert w.hf(exe) == old['elf'] and w.git('rev-parse', 'HEAD') == w.NEW
    ans = harness(exe, d, env, wrong=True)
    assert ans['name'] == old['harness']['name'] and ans['inventory'] == old['harness']['inventory']
    write(d / 'result.json', dict(elf=old['elf'], source=sources(), verdict=ans))


def main():
    assert os.environ['GITHUB_SHA'] == os.environ['REVIEWED_HEAD'] and os.environ['GITHUB_RUN_ATTEMPT'] == '1'
    assert os.uname().machine == 'x86_64' and w.git('rev-parse', 'HEAD') == w.NEW and w.git('rev-parse', 'HEAD^') == w.OLD
    assert set(w.git('diff', '--name-only', w.OLD, w.NEW).splitlines()) == {FIXTURE, SNAP, EDIT}
    assert REG['P'] == kit.R['P'] and REG['C'] == kit.R['C']
    TOOLS.mkdir()
    for name in ('whole_count', 'exec_count'):
        subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', HERE/(name+'.c'), '-o', TOOLS/name], check=True)
    rank = int(os.environ['CONFIRM_RANK'])
    assert 0 <= rank < 6 and len(CONFIRM['roles']) == 6
    order = CONFIRM['roles'][rank]
    info = dict(registration=REG, confirmation=CONFIRM, rank=rank, order=order, sdk=kit.R, head=os.environ['GITHUB_SHA'], run=os.environ['GITHUB_RUN_ID'],
                boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(), runner=os.environ['RUNNER_NAME'], cpu=os.uname().machine,
                affinity=sorted(os.sched_getaffinity(0)), kernel=os.uname().release)
    write(w.proof / 'enrollment.json', info)
    mani = kit.intake()
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'LANG', 'USER') if k in os.environ}
    env.update(RUSTUP_HOME=str(w.ru), RUSTUP_TOOLCHAIN='ohm', CARGO_HOME=str(w.home), CARGO_TARGET_DIR=str(w.target), CARGO_BUILD_BUILD_DIR=str(w.shared), CARGO_NET_GIT_FETCH_WITH_CLI='true', CARGO_NET_OFFLINE='true', LD_LIBRARY_PATH=str(w.sdk/'lib'))
    write(w.proof / 'cargo-environment.json', env)
    (w.ru/'toolchains').mkdir(parents=True); (w.ru/'toolchains/ohm').symlink_to(w.sdk, True)
    histories = {}
    for role in order:
        arm = mani['arms']['normal' if role == 'P' else 'defer']; ordinary = Path(arm['root'])
        ordinary.rename(w.sdk)
        tools = {}
        for name in ('cargo', 'rustc', 'rustdoc'):
            p = Path(subprocess.check_output(['rustup','which','--toolchain','ohm',name],env=env,text=True).strip())
            assert p.samefile(w.sdk/'bin'/name) and w.hf(p) == arm['files']['bin/' + name]
            tools[name] = w.hf(p)
        driver, = (w.sdk/'lib').glob('librustc_driver-*.so'); assert w.hf(driver) == arm['files']['lib/'+driver.name]
        write(w.proof / (role+'-sdk.json'), {'bin':tools,'driver':w.hf(driver),'llvm_wild_std':arm['files']})
        hist = {}
        start(role, 'measured', env, w.OLD)
        hist['old'] = phase(role, 'old', env, 'whole')
        checkout(w.NEW); stale(role, env, hist['old'])
        for tag in ('edit','first','warm0','warm1','warm2'):
            hist[tag] = phase(role, tag, env, 'whole')
        source = w.work / EDIT
        orig = source.read_bytes(); source.write_bytes(orig + b'\nconst _: u8 = "intentionally ill-typed ruff";\n')
        try: phase(role, 'invalid', env, 'ordinary', negative=True)
        finally: source.write_bytes(orig)
        hist['repair'] = phase(role, 'repair', env, 'ordinary')
        clear()
        start(role, 'empty', env, w.NEW)
        hist['clean'] = phase(role, 'clean', env, 'whole')
        clear()
        # Independent installation of all dependencies, same literal Cargo argv/paths and a
        # separate genuine OLD->NEW. No ptrace or link copying in an ordinary measured process.
        start(role, 'rosters', env, w.OLD)
        hist['census-cold'] = phase(role, 'census-cold', env, 'census')
        checkout(w.NEW)
        hist['census-edit'] = phase(role, 'census-edit', env, 'census')
        hist['census-warm'] = phase(role, 'census-warm', env, 'census')
        clear(); w.sdk.rename(ordinary)
        histories[role] = hist
    gates, data = {}, {}
    for role, hist in histories.items():
        old = hist['old']['elf']; new = hist['clean']['elf']
        gates[role + '/old-new'] = old != new
        gates[role + '/source-ELFs'] = all(x['elf'] == (old if x['state'] == w.OLD else new) for x in hist.values())
        gates[role + '/marker'] = all(any(row[2] for row in result['portable']) == (role == 'P') and len(result['portable']) > 0 for result in hist.values() if 'portable' in result)
        gates[role + '/clocks'] = all(x.get('clock_ok', True) for x in hist.values())
        gates[role + '/roster-controls'] = (hist['old']['nominal'] == hist['census-cold']['nominal'] and hist['edit']['nominal'] == hist['census-edit']['nominal'] and hist['first']['nominal'] == hist['census-warm']['nominal'])
        gates[role + '/real-edit'] = all(any(x['crate'] == 'ruff_linter' and x['mode'] == 'test' for x in hist[tag]['roster']) and len(hist[tag]['native']) == 1 for tag in ('census-cold','census-edit'))
    for label in histories['P']:
        p, c = histories['P'][label], histories['C'][label]
        gates[label + '/ELF'] = p['elf'] == c['elf']
        gates[label + '/inventory'] = p['harness']['inventory'] == c['harness']['inventory'] == histories['P']['old']['harness']['inventory']
        if 'clock' in p:
            data[label] = dict(P=p['clock']['instructions'], C=c['clock']['instructions'])
    gates['warm-price-room'] = all(data[tag]['C'] <= 0.80 * data[tag]['P'] for tag in ('first','warm0','warm1','warm2'))
    expected = {'full': [('full', 'portable_atomic'), ('full', 'ruff_db'), ('full', 'salsa'), ('test', 'ruff_linter')], 'one': [('test', 'ruff_linter')], 'zero': []}
    for role, hist in histories.items():
        gates[role+'/frozen-binaries-and-names'] = all(x['elf'] == CONFIRM['sources']['old' if x['state'] == w.OLD else 'new']
            and x['harness']['inventory'] == CONFIRM['inventory'] and x['harness']['name'] == CONFIRM['named']
            and x['harness']['count'] == CONFIRM['test_count'] for x in hist.values())
        for label in ('census-edit','census-warm'):
            census = hist[label]['roster']
            actual = sorted((x['mode'], x['crate']) for x in census if x['role'] == 'rustc' and x['mode'] != 'config')
            selection = 'full' if role == 'P' else 'one' if label == 'census-edit' else 'zero'
            gates[role+'/'+label+'/selected-processes'] = actual == expected[selection] and sum(x['role'] == 'wild' for x in census) == int(selection != 'zero')
    gates['genuine-edit-improves'] = data['edit']['C'] < data['edit']['P']
    gates['cold-guards'] = all(data[tag]['C'] <= 1.02 * data[tag]['P'] for tag in ('old','clean'))
    gates['stored-native-products'] = all(histories['P']['warm2']['stored_native'][ext] == histories['C']['warm2']['stored_native'][ext] for ext in ('.o','.rlib','.rmeta')) and all(histories[r]['warm2']['stored_native']['.rlink'][0] == 1 for r in ('P','C'))
    write(w.proof / 'decision.json', {'gates':gates, 'counts':data, 'admitted':all(gates.values())})
    assert all(gates.values()), [k for k,v in gates.items() if not v]


if __name__ == '__main__':
    main()
