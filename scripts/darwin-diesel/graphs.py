"""Record the closed native Diesel session before and after a forensic rustc invocation."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def require(ok, why):
    if not ok:
        raise ValueError(why)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def put(path, value):
    with path.open('x') as f:
        json.dump(value, f, sort_keys=True, indent=2)
        f.write('\n')


def clone(source, dest):
    require(source.is_dir() and not dest.exists(), 'wrong private snapshot destination')
    require(shutil.disk_usage(dest.parent).free >= 5 << 30, 'less than 5 GiB available before copying the native workspace')
    if sys.platform == 'darwin':
        subprocess.run(['/bin/cp', '-cRp', source, dest], check=True)
    else:
        shutil.copytree(source, dest, symlinks=True)


def tables(root, evidence, retain=True):
    rows = []
    if root is None or not root.is_dir():
        return rows
    for session in sorted(root.glob('diesel-*/s-*')):
        if not session.is_dir() or session.name.endswith('-working'):
            continue
        for p in sorted(session.glob('*.bin')):
            stat = p.stat()
            require(p.is_file() and not p.is_symlink() and 0 <= stat.st_size < 512 << 20, ('unexpected session file', p))
            body = sha(p)
            if retain and p.name in ('dep-graph.bin', 'ohm-packed-dep-graph.bin'):
                saved = evidence / 'bodies' / body
                saved.parent.mkdir(exist_ok=True)
                if not saved.exists():
                    require(shutil.disk_usage(saved.parent).free >= (4 << 30) + stat.st_size, 'session escrow space')
                    shutil.copyfile(p, saved)
                    require(sha(saved) == body, 'source graph changed while recording')
            end = p.stat()
            require((stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns) ==
                    (end.st_dev, end.st_ino, end.st_size, end.st_mtime_ns), 'finalized session file was replaced')
            with p.open('rb') as f:
                first = f.read(128).hex()
                f.seek(max(stat.st_size - 128, 0))
                last = f.read().hex()
            rows.append({'path': str(p.relative_to(root)), 'name': p.name, 'sha256': body, 'bytes': stat.st_size,
                         'dev': stat.st_dev, 'ino': stat.st_ino, 'mtime_ns': stat.st_mtime_ns, 'first': first, 'last': last})
    return rows


def observe(phase, code, command):
    if '--crate-name' not in command or command[command.index('--crate-name') + 1] != 'diesel' or 'opt-level=3' not in command:
        return
    cwd = Path.cwd().resolve()
    stage = Path(os.environ['OHM_DIESEL_STAGE'])
    require(cwd.parent == (stage / 'tmp').resolve() and cwd.name.startswith('.tmp'), ('unexpected collector workspace', cwd))
    results = Path(os.environ['OHM_DIESEL_RESULTS'])
    require(os.environ['RUSTC_FORCE_RUSTC_VERSION'] == os.environ['RUSTC_FORCE_INCR_COMP_ARTIFACT_HEADER'] == 'rustc-perf',
            'different compiler/dep-graph encoding context')
    require('-Zincremental-verify-ich' in command and [a for a in command if a.startswith('-Zthreads=')][-1:] == ['-Zthreads=1'],
            'different actual rustc-perf verification or worker-thread mode')
    active = results / 'observations'; active.mkdir(exist_ok=True)
    incs = [t.split('=', 1)[1] for t in command if t.startswith('incremental=')]
    require(len(incs) <= 1, 'ambiguous incremental argument')
    inc = Path(incs[0]).resolve() if incs else None
    require(inc is None or inc == cwd / 'incremental-state', 'different physical incremental root')
    source = cwd / 'src/query_dsl/mod.rs'
    inputs = json.loads((results.parent / 'inputs.json').read_bytes())
    variant = {v: k for k, v in inputs['source_hashes'].items()}.get(sha(source))
    require(variant in ('A', 'B'), 'different Diesel source')
    if phase == 'before':
        number = len(list(active.glob('*-before.json'))) + 1
    else:
        number = len(list(active.glob('*-before.json')))
    require(1 <= number <= 6 and phase in ('before', 'after'), 'unexpected number of real opt rustcs')
    row = {'phase': phase, 'index': number, 'exit': int(code), 'cwd': str(cwd), 'argv': command,
           'source': variant, 'source_sha256': sha(source), 'incremental': str(inc) if inc else None,
           'tables': tables(inc, results), 'env': dict(os.environ)}
    require(all(not any(w in k.upper() for w in ('TOKEN', 'PASSWORD', 'SECRET', 'CREDENTIAL', 'AUTHORIZATION')) for k in row['env']),
            'unexpected credentials in compiler environment')
    if phase == 'before' and variant == 'B' and inc is not None:
        template = stage / 'patched-input'
        clone(cwd, template)
        source_tables = [(x['path'], x['sha256']) for x in row['tables']]
        require(source_tables and source_tables == [(x['path'], x['sha256']) for x in tables(template / 'incremental-state', results, False)],
                'private replay template did not preserve the complete incoming tables')
    put(active / f'{number:02}-{phase}.json', row)


if __name__ == '__main__':
    observe(sys.argv[1], sys.argv[2], sys.argv[3:])
