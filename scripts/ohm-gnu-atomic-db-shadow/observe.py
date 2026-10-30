"""Retain authentic Cargo/exec traces and the complete root GNU linker search."""
import ast
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

import census


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def save(path, data):
    census.save(path, data)


def stat_id(path):
    st = path.stat()
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, sha(path)]


FORK = re.compile(r'^(?:(?:clone3?|vfork|fork)\(|<\.\.\. (?:clone3?|vfork|fork) resumed>).*=\s*(\d+)\s*$')
PROBE = re.compile(r'^open(?:at2?)?\((?:(?:[^,"]+),\s*)?("(?:[^"\\]|\\.)*").*\)\s+=\s*(-?\d+)(?:<([^>]*)>)?(?:\s+(\w+))?')


def root_ld(row):
    a = row['argv']
    if Path(row['path']).name not in ('ld', 'ld.bfd') or '-maarch64linux' not in a or '-o' not in a:
        return False
    return re.fullmatch(r'ruff_db-[0-9a-f]{16}', Path(a[a.index('-o') + 1]).name) is not None


def collect(raw, at, src):
    events = at / 'exec'
    events.mkdir()
    ancestry = {}
    for f in sorted(raw.glob('proc.*')):
        pid = int(f.suffix[1:])
        with f.open(errors='surrogateescape') as inp, (events / f.name).open('w', errors='surrogateescape') as out:
            for s in inp:
                if s.startswith(('execve', '+++', '---', 'clone', 'fork', 'vfork', '<...')):
                    out.write(s)
                    m = FORK.match(s)
                    if m and (child := int(m[1])) != 0:
                        assert child not in ancestry or ancestry[child] == pid, (child, pid)
                        ancestry[child] = pid
    kernel = census.qualify.native(events, src)
    save(at / 'kernel.json', kernel)
    save(at / 'ancestry.json', ancestry)
    with tarfile.open(at / 'physical-execs.tar.gz', 'x:gz', compresslevel=2) as bundle:
        for f in sorted(events.iterdir()):
            if f.stat().st_size:
                bundle.add(f, arcname=f.name)
    shutil.rmtree(events)
    roots = [row for row in kernel['link_tools'] if root_ld(row)]
    assert len(roots) <= 1, [(r['path'], r['pid']) for r in roots]
    root = roots[0] if roots else None
    opens = []
    owned = []
    chain = []
    binaries = {}
    if root:
        current = root['pid']
        while current not in chain:
            chain.append(current)
            if current not in ancestry:
                break
            current = ancestry[current]
        images = [*kernel['rustcs'], *kernel['link_tools'], *kernel['cargo']]
        for row in images:
            if row['pid'] in chain:
                owned.append([row['pid'], row['path'], row['terminal']])
                p = Path(row['path'])
                binaries[str(p)] = [str(p.resolve()), *stat_id(p)]
        # Retain the original complete strace for each genuine native tool in this link.
        with tarfile.open(at / 'native-files.tar.gz', 'x:gz', compresslevel=3) as bundle:
            for pid, name, _ in owned:
                if name != root['path'] and Path(name).name not in ('collect2', 'aarch64-linux-gnu-gcc'):
                    continue
                f = raw / f'proc.{pid}'
                bundle.add(f, arcname=f.name)
                if pid == root['pid']:
                    for line in f.read_text(errors='backslashreplace').splitlines():
                        m = PROBE.match(line)
                        if m:
                            opens.append({'path': ast.literal_eval(m[1]), 'fd': int(m[2]),
                                          'resolved': m[3], 'errno': m[4], 'line': line})
    save(at / 'link-search.json', {'root': root, 'ancestors': chain, 'owners': owned,
                                  'tools': binaries, 'opens': opens})
    # Retain full original streams for any incomplete chain before reporting it.
    if root:
        assert any(Path(x[1]).name == 'collect2' for x in owned) and any(
            Path(x[1]).name == 'aarch64-linux-gnu-gcc' for x in owned), owned
        assert any(r['pid'] in chain and r['crate'] == 'ruff_db' for r in kernel['rustcs']), owned
        assert any(r['pid'] in chain for r in kernel['cargo']), owned
        assert opens, root['path']
    shutil.rmtree(raw)
    return kernel, root, opens


def trace(command, cwd, env, at):
    at.mkdir(parents=True)
    # Raw source and env remain identical. The observer is the parent of the real rustup command.
    raw = at / 'live-trace'
    raw.mkdir()
    argv = ['strace', '-ff', '-q', '-y', '-s', '262144',
            '-e', 'trace=execve,execveat,clone,clone3,fork,vfork,open,openat,openat2',
            '-o', str(raw / 'proc'), *command]
    p = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, timeout=4000)
    for name, body in [('stdout', p.stdout), ('stderr', p.stderr)]:
        census.blob(at / (name + '.gz'), body)
    save(at / 'command.json', {'argv': argv, 'exit': p.returncode, 'stdout': sha_bytes(p.stdout),
                              'stderr': sha_bytes(p.stderr)})
    kernel, ld, opens = collect(raw, at, cwd)
    typed = [json.loads(line) for line in p.stdout.splitlines() if line.strip()]
    assert p.returncode in (0, 101) and typed[-1] == {'reason': 'build-finished', 'success': p.returncode == 0}
    assert kernel['cargo'][0]['terminal'] == [p.returncode]
    return p, typed, kernel, ld, opens
