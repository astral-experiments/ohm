"""Independently enumerate *every* successful Linux exec event in the real Ruff Cargo phases."""
from collections import Counter
from hashlib import sha256
import ast
import copy
import io
import json
from pathlib import Path
import re
import sys
import tarfile
import zipfile

EXEC = re.compile(rb'^execve\(("(?:[^"\\]|\\.)*"), (\[.*\]), (?:NULL|0x[^)]*)\)\s+= 0$')
END = re.compile(rb'^\+\+\+ exited with (\d+) \+\+\+$', re.M)

def inspect(z, phase, rows):
    actual = Counter()
    kinds = Counter()
    wrappers, builds = set(), set()
    with tarfile.open(fileobj=io.BytesIO(z.read(phase + '/exec.tar.gz'))) as parts:
        for file in parts:
            if not file.isfile():
                continue
            pid = int(file.name.rsplit('.', 1)[1])
            data = parts.extractfile(file).read()
            status = tuple(map(int, END.findall(data)))
            for line in data.splitlines():
                if not line.startswith((b'execve(', b'execveat(')) or not line.rstrip().endswith(b'= 0'):
                    continue
                match = EXEC.fullmatch(line)
                assert match, line[:240]
                path, argv = (ast.literal_eval(p.decode()) for p in match.groups())
                name = Path(path).name
                if path.endswith('/rustup/toolchains/ohm/bin/rustc'):
                    kind = 'rustcs' if '--crate-name' in argv and any(x == '--emit' or x.startswith('--emit=') for x in argv) else 'compiler_probes'
                elif path.endswith('/rustup/toolchains/ohm/bin/cargo'):
                    kind = 'cargo'
                elif name in {'cc', 'gcc', 'ld', 'ld.bfd', 'ld.lld', 'collect2', 'wild', 'rust-lld'} or name.startswith('aarch64-linux-gnu-') or '/wild-ld/' in path:
                    kind = 'link_tools'
                elif path.endswith('/.cargo/bin/cargo'):
                    assert len(argv) >= 2 and argv[1] == '+ohm'
                    wrappers.add(pid)
                    kinds['rustup-dispatch'] += 1
                    continue
                elif name == 'build_script_build' and '/build/' in path:
                    assert argv == [path] and status == (0,)
                    builds.add(pid)
                    kinds['Cargo build script'] += 1
                    continue
                else:
                    raise AssertionError(('unclassified successful exec', path, pid))
                actual[(kind, pid, path, tuple(argv), status)] += 1
                kinds[kind] += 1
    recorded = Counter((kind, r['pid'], r['path'], tuple(r['argv']), tuple(r['terminal'])) for kind, events in rows.items() for r in events)
    assert actual == recorded and wrappers == {r['pid'] for r in rows['cargo']}
    assert len(wrappers) == 1 and len(builds) == kinds['Cargo build script']
    return dict(sorted(kinds.items()))

def main(filename, out=None):
    with zipfile.ZipFile(filename) as z:
        phases = sorted(n.removesuffix('/native.json') for n in z.namelist() if n.startswith('mirror') and n.endswith('/native.json'))
        assert len(phases) in (28, 36)
        table = {}
        for phase in phases:
            rows = json.loads(z.read(phase + '/native.json'))
            table[phase] = inspect(z, phase, rows)
        fixture = 'mirror1-P/unchanged-1'
        for mutation in ('drop', 'invent'):
            rows = json.loads(z.read(fixture + '/native.json'))
            if mutation == 'drop':
                assert rows['rustcs'].pop()
            else:
                invented = copy.deepcopy(rows['rustcs'][0])
                invented['pid'] += 1000000
                rows['rustcs'].append(invented)
            try:
                inspect(z, fixture, rows)
            except AssertionError:
                pass
            else:
                raise AssertionError(('accepted corruption', mutation))
    bound = {'source': sha256(Path(__file__).read_bytes()).hexdigest(), 'phases': table, 'missing_or_invented_process_rejected': True}
    wire = (json.dumps(bound, indent=2, sort_keys=True) + '\n').encode()
    if out:
        Path(out).open('xb').write(wire)
    print('phases',len(phases),'sha256',sha256(wire).hexdigest())
if __name__ == '__main__':
    main(*sys.argv[1:])
