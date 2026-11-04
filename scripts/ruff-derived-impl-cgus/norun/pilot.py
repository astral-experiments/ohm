"""Measure the ordinary package-wide test build. Run native behavior checks after the counter exits."""
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess as sp
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import release_adapter as trained

p = trained.paired
b = p.b
registered = json.loads((HERE / 'registered.json').read_bytes())
CMD = registered['ordinary']
ROOTS = {row[3]: row[0] for row in registered['eligibility']['full']['roots']}
OUT = b.ROOT.parent / 'ruff-norun-evidence'
CACHE = b.ROOT.parent / 'trained-norun-sdks'
REF = 'charlie/qa-ruff-cli-help-norun-stage2-20261104'


def read_json(path):
    return json.loads(path.read_bytes())


def native_root_paths(log):
    found = {}
    for line in log.read_text().splitlines():
        match = re.fullmatch(r'\s*Executable (.+?) \((.+)\)', line)
        if not match:
            continue
        desc, spelling = match.groups()
        names = [name for name in ROOTS if desc.endswith(name)]
        b.need(len(names) == 1, ('unrecognized test source', desc))
        name = names[0]
        exe = (b.WORK / spelling).resolve(strict=True)
        b.need(name not in found and exe.is_file() and os.access(exe, os.X_OK)
               and any(exe.is_relative_to(root.resolve()) for root in (b.TARGET, b.BUILD)), ('unbound test executable', name, str(exe)))
        found[name] = exe
    b.need(set(found) == set(ROOTS) and len(set(found.values())) == 8, ('different real test roots', sorted(found)))
    return found


def verdicts(td, state):
    exes = native_root_paths(td / 'stderr')
    rows = {}
    work = b.WORK / 'crates/ruff'
    cli = b.TARGET / 'debug/ruff'
    b.need(cli.is_file() and os.access(cli, os.X_OK), 'missing ordinary binary for integration tests')
    env = b.env() | {'CARGO_MANIFEST_DIR': str(work), 'CARGO_BIN_EXE_ruff': str(cli),
                     'NO_COLOR': '1', 'LC_ALL': 'C', 'TERM': 'dumb', 'RUFF_NO_CACHE': 'true', 'INSTA_UPDATE': 'no'}
    outputs = td / 'out-of-counter'
    outputs.mkdir()
    for name, exe in sorted(exes.items()):
        tag = name.replace('/', '_')
        listed = sp.run([exe, '--list', '--format', 'terse'], cwd=work, env=env, capture_output=True, timeout=90)
        (outputs / (tag + '.list')).write_bytes(listed.stdout)
        (outputs / (tag + '.stderr')).write_bytes(listed.stderr)
        b.need(listed.returncode == 0 and not listed.stderr, ('incomplete test inventory', name, listed.returncode))
        cases = listed.stdout.decode().splitlines()
        b.need(len(cases) == len(set(cases)) and all(re.fullmatch(r'.+: (test|benchmark)', v) for v in cases),
               ('invalid or repeated test name', name))
        for test in {'tests/config.rs': ['lint_select', 'lint_select_json'], 'tests/integration_test.rs': ['stdin_success']}.get(name, []):
            b.need(test + ': test' in cases, ('missing selected native test', name, test))
            ran = sp.run([exe, '--exact', test, '--test-threads=1'], cwd=work, env=env, capture_output=True, timeout=90)
            (outputs / (tag + '-' + test + '.stdout')).write_bytes(ran.stdout)
            (outputs / (tag + '-' + test + '.stderr')).write_bytes(ran.stderr)
            b.need(ran.returncode == 0 and b'1 passed; 0 failed' in ran.stdout and ('test ' + test + ' ... ok').encode() in ran.stdout,
                   ('actual native test failed', test, ran.stderr[-500:], ran.stdout[-500:]))
        rows[name] = {'bytes': exe.stat().st_size, 'sha256': b.zsave(exe, b.PUB / 'native-bodies'),
                      'inventory_count': len(cases), 'inventory': hashlib.sha256(listed.stdout).hexdigest()}
    b.need(sum(v['inventory_count'] for v in rows.values()) > 100, 'empty native test inventory')
    result = {'roots': rows, 'cli': {'bytes': cli.stat().st_size, 'sha256': b.zsave(cli, b.PUB / 'native-bodies')},
              'verdict': b.verdict(cli, outputs, state)}
    b.put(td / 'native.json', result)
    return result


def task_rows(kernel):
    image = {}
    rows = []
    rust = p.isource(b.SDK / 'bin/rustc')
    wild = p.isource(b.SDK / b.WILD)
    for line in (kernel / 'epochs.tsv').read_text().splitlines():
        f = line.split()
        if f[0] == 'I':
            ident = int(f[1])
            fields = (kernel / f'{ident:05}.nul').read_bytes().split(b'\0')
            b.need(fields.pop() == b'' and int(fields[0]) == int(f[2]), 'bad kernel exec')
            image[ident] = ([int(fields[1]), int(fields[2])], list(map(os.fsdecode, fields[4:])))
        elif f[0] == 'R':
            ident, pid, n, enabled, running, status = map(int, f[1:])
            b.need(n > 0 and running == enabled > 0 and status == 0, 'invalid task counter')
            owner, argv = image[ident]
            if owner == rust and '--crate-name' in argv:
                crate = b.crate_arg(argv, '--crate-name')
                src = [word for word in argv if word.endswith('.rs') and not word.startswith('-')]
                b.need(len(src) == 1, ('missing full rustc source argv', argv))
                path = Path(src[0]).as_posix()
                matches = [name for name in ROOTS if path == name or path.endswith('/crates/ruff/' + name) or path == 'crates/ruff/' + name]
                root = matches[0] if len(matches) == 1 else path
                kind = 'test-harness' if '--test' in argv else b.crate_arg(argv, '--crate-type')
                rows.append({'pid': pid, 'source': root, 'crate': crate, 'kind': kind, 'link_only': any(v.startswith('-Zlink-only') for v in argv),
                             'instructions': n, 'argv': argv})
            elif owner == wild:
                rows.append({'pid': pid, 'kind': 'wild', 'instructions': n, 'argv': argv})
    verified = p.lifetimes(kernel)
    b.need(sum(x['kind'] != 'wild' for x in rows) == len(verified['rustcs']) and sum(x['kind'] == 'wild' for x in rows) == len(verified['wild_lifetimes']),
           'unaccounted kernel lifetime')
    return rows


def cgu_bodies(td):
    # Previous and edited stat identities distinguish retained work from independently identical output.
    allowed = set(ROOTS.values())
    sessions = {}
    for graph in b.TARGET.rglob('dep-graph.bin'):
        session = graph.parent
        bucket = session.parent
        crate = bucket.name.partition('-')[0]
        if crate not in allowed or not (session / 'work-products.bin').is_file():
            continue
        files = {}
        for member in sorted(session.glob('*.o')):
            st = member.stat()
            b.need(st.st_size < 128*2**20 and len(files) < 1000, 'oversized test native inventory')
            files[member.name] = [st.st_dev, st.st_ino, st.st_mtime_ns, st.st_size, b.hf(member)]
        if files:
            sessions[str(session.relative_to(b.TARGET))] = files
    b.put(td / 'cgu-bodies.json', sessions)


def phase(label, state, kind='ordinary'):
    b.guard()
    td = b.PUB / label
    td.mkdir()
    cargo = shutil.which('cargo', path=b.env()['PATH'])
    args = [b.ROOT / 'whole_count', td / 'counter.json', cargo, *CMD]
    if kind == 'tasks':
        k = p.rawtd(td)
        args = [b.ROOT / 'exec_count', '--lifetime', b.SDK / 'bin/rustc', '--also', b.SDK / b.WILD, k, *args]
    with (td / 'stdout').open('xb') as stdout, (td / 'stderr').open('xb') as stderr:
        ran = sp.run(args, cwd=b.WORK, env=b.env(), stdout=stdout, stderr=stderr)
    b.need(ran.returncode == 0, ('ordinary Cargo command failed', label, (td / 'stderr').read_text(errors='replace')[-1600:]))
    h = read_json(td / 'counter.json')
    b.need(h['status'] == 0 and h['instructions'] > 0 and h['enabled'] == h['running'] > 0, ('bad whole Cargo event', label))
    if kind == 'tasks':
        rows = task_rows(k)
        b.put(td / 'task-instructions.json', rows)
        if label.endswith('unchanged'):
            b.need(not rows, ('settled rustc or link', label, [(r['pid'],r['kind']) for r in rows]))
        else:
            typed = {(r['source'], r['kind']) for r in rows if r['kind'] != 'wild'}
            b.need(('src/lib.rs', 'lib') in typed and ('src/lib.rs', 'test-harness') in typed and
                   all(r['source'] in ROOTS for r in rows if r['kind'] != 'wild'), ('unrecognized full edited rustc roster', sorted(typed)))
    result = verdicts(td, state)
    if label in ('cold-old', 'edit', 'empty-new'):
        b.put(td / 'footprint.json', p.footprint())
        cgu_bodies(td)
    print(b.PUB.name, label, h['instructions'], 'instructions;', sum(v['inventory_count'] for v in result['roots'].values()), 'test cases', flush=True)
    return result


def same(a, b_, reason):
    changed = [name for name in ROOTS if a['roots'][name] != b_['roots'][name]]
    b.need(a == b_, (reason, changed, a['cli'] == b_['cli'], a['verdict'] == b_['verdict']))


def invalid():
    src = b.SRC.read_bytes()
    try:
        b.SRC.write_bytes(src + b'\nfn owner_cgu_invalid_test_build() -> usize { "E0308" }\n')
        for label in ('invalid', 'invalid-unchanged'):
            dst = b.PUB / label
            dst.mkdir()
            with (dst / 'stdout').open('xb') as stdout, (dst / 'stderr').open('xb') as stderr:
                ran = sp.run(CMD, cwd=b.WORK, env=b.env(), stdout=stdout, stderr=stderr)
            log = (dst / 'stderr').read_bytes()
            b.need(ran.returncode == 101 and b'error[E0308]' in log and b'owner_cgu_invalid_test_build' in log,
                   ('missing error from actual test compilation', label, ran.returncode))
    finally:
        b.SRC.write_bytes(src)


def run_role(role, saved, proof):
    b.ROOT.mkdir()
    b.guard()
    b.PUB = OUT / role
    b.PUB.mkdir()
    path, compiled = trained.fetch(role, CACHE, b.PUB / 'factory')
    trained.transport.install(path, compiled, b.SDK, b.RUSTUP / 'toolchains/ohm')
    for name in ('rustc', 'cargo'):
        b.need(sp.check_output([name, '+ohm', '-vV'], env=b.env(), text=True) == compiled['versions'][name], 'different active toolchain')
    for name in ('whole_count', 'exec_count'):
        sp.run(['cc', '-O2', '-pthread', '-Wall', '-Wextra', '-Werror', p.frozen / (name + '.c'), '-o', b.ROOT / name], check=True)
    b.need(b.git('rev-parse', 'HEAD') == b.OLD and b.hf(b.SRC) == b.SRCS[b.OLD], 'wrong first source')
    b.prepare()
    old = phase('cold-old', b.OLD)
    same(old, phase('old-unchanged', b.OLD), 'cold→unchanged OLD')
    b.select(b.NEW)
    edited = phase('edit', b.NEW)
    b.need({n:v['inventory'] for n,v in old['roots'].items()} == {n:v['inventory'] for n,v in edited['roots'].items()}, 'test identity changed between OLD and NEW')
    b.need(old['cli'] != edited['cli'] and old['verdict'] != edited['verdict'], 'same actual CLI after real help edit')
    same(edited, phase('new-unchanged', b.NEW), 'edited→unchanged NEW')
    invalid()
    same(edited, phase('repair', b.NEW), 'repair did not reproduce all test executables')
    p.empty_outputs()
    b.prepare()
    clean = phase('empty-new', b.NEW)
    same(edited, clean, 'independent fresh NEW did not reproduce all actual native outputs')
    b.put(b.PUB / 'ordinary-admission.json', {'role': role, 'whole': read_json(b.PUB / 'edit/counter.json')['instructions'], 'all_native_roots': len(clean['roots'])})
    # Recreate the original source and Git state at the identical path, including mtimes.
    p.empty_outputs()
    b.put(b.PUB / 'restored-source.json', p.old_namespace.restore_checkout(b.WORK, saved, proof))
    b.prepare()
    seed = phase('second-cold-old', b.OLD)
    same(old, seed, 'independent OLD namespace differs before repeat pricing')
    same(seed, phase('observed-old-unchanged', b.OLD, 'tasks'), 'OLD no-op changed output')
    b.select(b.NEW)
    replay = phase('observed-edit', b.NEW, 'tasks')
    same(edited, replay, 'traced ordinary edit changed native output')
    same(replay, phase('observed-new-unchanged', b.NEW, 'tasks'), 'NEW no-op changed output')
    b.need(not b.git('status', '--porcelain'), 'dirty Ruff checkout')
    b.put(b.PUB / 'complete.json', {'all_controls': True, 'role': role, 'source': b.NEW, 'ordinary': CMD})
    p.empty_outputs()
    b.need(b.ROOT.name == 'ohm-clap-cli' and b.ROOT.parent == OUT.parent and not b.ROOT.is_symlink(), 'unaudited temporary root')
    shutil.rmtree(b.ROOT)


def main():
    b.need(os.environ['GITHUB_REF_NAME'] == REF and os.environ['GITHUB_RUN_ATTEMPT'] == '1' and
           os.environ['GITHUB_SHA'] == os.environ['REVIEWED_HEAD'] and b.git('rev-parse','HEAD') == b.NEW and
           b.git('rev-parse','HEAD^') == b.OLD and len(ROOTS) == 8, 'unregistered pilot')
    OUT.mkdir()
    b.put(OUT / 'registration.json', {'plan': registered, 'factory': trained.spec,
          'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'receiver': os.environ['REVIEWED_HEAD']})
    b.select(b.OLD)
    saved = OUT.parent / 'original-ruff-checkout'
    proof = p.old_namespace.save_checkout(b.WORK, saved)
    b.put(OUT / 'source-original.json', proof)
    errors = {}
    for i, role in enumerate('PC'):
        if i:
            p.old_namespace.restore_checkout(b.WORK, saved, proof)
        try:
            run_role(role, saved, proof)
        except Exception as exc:
            errors[role] = repr(exc)
            b.put(OUT / ('refusal-' + role + '.json'), {'reason': repr(exc)})
            print(role, repr(exc), flush=True)
            if b.ROOT.is_dir():
                b.ROOT.rename(OUT.parent / ('refused-norun-' + role))
    if errors:
        raise RuntimeError(errors)
    for label in ('cold-old','edit','empty-new','repair'):
        first = read_json(OUT / 'P' / label / 'native.json')
        second = read_json(OUT / 'C' / label / 'native.json')
        b.need(first['verdict'] == second['verdict'] and
               {n:v['inventory'] for n,v in first['roots'].items()} == {n:v['inventory'] for n,v in second['roots'].items()},
               ('cross-compiler runtime or test inventory differs', label))
    def roster(role):
        return collections.Counter((r['kind'], r.get('source'), r.get('link_only', False))
               for r in read_json(OUT / role / 'observed-edit/task-instructions.json'))
    b.need(roster('P') == roster('C'), 'different kernel compile/link roster')
    b.put(OUT / 'terminal.json', {'ordinary': CMD, 'order':'PC', 'all_cases':True})


if __name__ == '__main__':
    main()
