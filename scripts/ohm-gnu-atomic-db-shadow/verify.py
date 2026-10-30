"""Independently verify the downloaded GitHub ZIP (takes a path or a pipe on stdin)."""
import argparse
import ast
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import zipfile


STATES = ('absent', 'higher83', 'same-stamp47', 'malformed', 'removed')
EXPECTED = dict(zip(STATES, [0, 83, 47, None, 0]))


def verify_rows(rows):
    fails = []
    def require(label, condition):
        if not condition:
            fails.append(label)
    training = rows['training-edit']
    names = training['qemu']['tests']
    healthy = training['product']['sha256']
    require('training inventory', len(names) == 129 and len(rows['training-old']['qemu']['tests']) == 126)
    require('source edit rebuilt', any(r[0] == 'ruff_db' and not r[1] for r in training['rustcs']))
    checks = {'indexed_nodes_round_trip', 'indexed_nodes_relative_tail_bounds',
              'indexed_nodes_wide_tail_bounds', 'indexed_nodes_chunk_boundary'}
    for family in ('ordinary', 'forced', 'empty'):
        for state in STATES:
            label = family + '-' + state
            r = rows[label]
            require(label + ' own input intact', r['pre_slot'] == r['post_slot'])
            require(label + ' actual root GNU ld', r['root_ld'] is not None)
            require(label + ' actual path', bool(r['selected'] if state in ('higher83', 'same-stamp47', 'malformed') else r['missing']))
            if family in ('forced', 'empty'):
                require(label + ' real root compile', any(n == 'ruff_db' and not cached for n, cached, *_ in r['rustcs']))
            if family == 'forced':
                require(label + ' root fingerprint invalidated', bool(r['forced_short']) and
                        all(value is not None or (state == 'removed' and rows['forced-malformed']['exit'] == 101)
                            for _, value in r['forced_short']))
            if state == 'malformed':
                require(label + ' native error', r['exit'] == 101 and r['invalid_text'] and r['product'] is None
                        and bool(r['root_ld']) and r['root_ld'][2] != [0])
                continue
            require(label + ' actual system library', bool(r['lower_selected']))
            require(label + ' Cargo/QEMU', r['exit'] == 0 and r['qemu'] and r['qemu']['list']['exit'] == EXPECTED[state])
            if r['exit'] != 0:
                continue
            require(label + ' complete unit stream', r['typed'] == 188)
            reference = rows['empty-' + state]['product']
            require(label + ' empty ELF', reference and r['product']['sha256'] == reference['sha256'])
            if state in ('absent', 'removed'):
                require(label + ' restored original', r['product']['sha256'] == healthy and r['qemu']['tests'] == names)
                require(label + ' four real tests', set(r['qemu']['checks']) == checks and
                        all(record[0]['exit'] == 0 and record[1] for record in r['qemu']['checks'].values()))
            else:
                require(label + ' different native program', r['product']['sha256'] != healthy and not r['qemu']['tests'])
        r83, r47 = (rows[family + '-' + s] for s in ('higher83', 'same-stamp47'))
        require(family + ' unique selected code', r83['product'] and r47['product'] and r83['product']['sha256'] != r47['product']['sha256'])
        if family != 'empty':
            ids = [rows[family + '-' + s]['pre_slot'] for s in ('higher83', 'same-stamp47', 'malformed')]
            require(family + ' preserved physical stamp', all(ids) and len({tuple(i[:4]) for i in ids}) == 1
                    and len({i[4] for i in ids}) == 3)
    return {'phases': len(rows), 'failures': fails, 'initial_edited_elf': healthy,
            'state_products': {s: (rows['empty-' + s]['product'] or {}).get('sha256') for s in STATES},
            'states': {k: [v['exit'], (v['qemu'] or {}).get('list', {}).get('exit'), len(v['selected']),
                            len(v['missing']), sum(not r[1] for r in v['rustcs']),
                            sum(r[1] for r in v['rustcs']), bool(v['root_ld'])] for k, v in rows.items()}}


def digest(b):
    return hashlib.sha256(b).hexdigest()


def audit(data, partial=False):
    z = zipfile.ZipFile(io.BytesIO(data))
    enrolled_path, = [n for n in z.namelist() if n.split('/')[-1] == 'enrolled.json']
    prefix = enrolled_path[:-len('enrolled.json')]
    def raw(path):
        return z.read(prefix + path)
    def obj(path):
        return json.loads(raw(path))
    enrolled = obj('enrolled.json')
    if partial:
        assert prefix + 'terminal.json' not in z.namelist()
        visits = {n.split('/')[-2]:json.loads(z.read(n)) for n in z.namelist()
                  if n.startswith(prefix+'visits/') and n.endswith('/verdict.json')}
        assert visits
        d = {'rows': visits, 'cmd': enrolled['cli'], 'compiler': enrolled['compiler']}
    else:
        d = obj('observation.json')
        assert len(d['rows']) == 17 and d['states'] == list(STATES)
    rows = d['rows']
    assert d['compiler']['reviewed'] == 'cfb921896461bc6e19f43b5d04355752e78cfba7'
    assert d['compiler']['source'] == '4ed3e4d1fa1da4e93f8c761751b3c81dd55ff6cd'
    assert enrolled['compiler']['driver'][0] == '45d8737f938d6ed97be5903342718f087d0af6ea710dd3c2416babc8c570d4b7'
    assert enrolled['lock_sha256'] == 'e37036fd781578faeafa15fc0a09b938dd78bd160c8e3be958dfb74eb975f61c'
    assert enrolled['trees']['49bf50b1c782a4e443ae3edce2fdb6d81c2df562'] == 'cf34a6e6988e47cea33e0d708ce66d3097788101'
    assert enrolled['cargo_sha'] and enrolled['cli'] == d['cmd']
    mini = obj('provider-bytes/preflight.json')
    assert digest(raw('provider-bytes/system-libgcc_s.input')) == mini['inputs']['lower']['id'][-1]
    for count in (47, 83):
        r = mini['inputs'][str(count)]
        b = raw(f'provider-bytes/p{count}.o')
        assert digest(b) == r['sha256'] and len(b) == r['size'] and b[18:20] == b'\xb7\x00'
    for state, rc in EXPECTED.items():
        m = mini['states'][state]
        assert m['link'] != 0 if rc is None else m['link'] == 0 and m['qemu']['exit'] == rc
    elfs = {}
    for label, r in rows.items():
        base = 'visits/' + label + '/'
        assert r == obj(base + 'verdict.json')
        c = obj(base + 'command.json')
        assert c['exit'] == r['exit'] and c['argv'][-len(d['cmd']):] == d['cmd']
        stdout = gzip.decompress(raw(base + 'stdout.gz'))
        stderr = gzip.decompress(raw(base + 'stderr.gz'))
        messages = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        assert digest(stdout) == c['stdout'] and digest(stderr) == c['stderr']
        assert messages[-1] == {'reason': 'build-finished', 'success': r['exit'] == 0}
        assert sum(m.get('reason') == 'compiler-artifact' for m in messages) == r['typed']
        if r['exit']:
            diagnostics = stderr.decode(errors='replace') + '\n'.join(str(m.get('message', '')) for m in messages)
            assert 'libgcc_s.so' in diagnostics and ('syntax error' in diagnostics or 'file format not recognized' in diagnostics)
        k = obj(base + 'kernel.json')
        e = tarfile.open(fileobj=io.BytesIO(raw(base + 'physical-execs.tar.gz')), mode='r:gz')
        for ev in k['cargo'] + k['rustcs'] + k['link_tools']:
            lines = e.extractfile('proc.' + str(ev['pid'])).read().decode(errors='replace').splitlines()
            ok = False
            for line in lines:
                m = re.fullmatch(r'execve\(("(?:[^"\\]|\\.)*"), (\[.*\]), (?:NULL|0x[^)]*)\)\s+= 0', line)
                if m and ast.literal_eval(m[2]) == ev['argv'] and (
                        ast.literal_eval(m[1]) == ev['path'] or not Path(ast.literal_eval(m[1])).is_absolute()):
                    ok = True
                    break
            assert ok, (label, ev['pid'], ev['path'])
            assert all(f'+++ exited with {v} +++' in lines for v in ev['terminal'])
        if r['root_ld']:
            pid, path, codes = r['root_ld']
            ev, = [v for v in k['link_tools'] if v['pid'] == pid and v['path'] == path]
            assert '-maarch64linux' in ev['argv'] and '-lgcc_s' in ev['argv'] and codes == ev['terminal']
            slot = Path(r['slot_path'])
            assert '-L' + str(slot.parent) in ev['argv'] and '/psm/' in str(slot.parent)
            owned = obj(base + 'link-search.json')
            rel = obj(base + 'ancestry.json')
            assert all(rel[str(ch)] == pr for ch, pr in zip(owned['ancestors'], owned['ancestors'][1:]))
            for name in ('aarch64-linux-gnu-gcc', 'collect2', 'ld'):
                assert any(i in owned['ancestors'] and Path(p).name == name for i, p, _ in owned['owners'])
            assert any(v['crate'] == 'ruff_db' and v['pid'] in owned['ancestors'] for v in k['rustcs'])
            traces = tarfile.open(fileobj=io.BytesIO(raw(base + 'native-files.tar.gz')), mode='r:gz')
            lines = traces.extractfile('proc.' + str(pid)).read().decode(errors='replace').splitlines()
            for line in r['selected'] + r['missing'] + r['lower_selected']:
                assert line in lines and line.startswith(('open(', 'openat(', 'openat2('))
            for line in r['missing']:
                assert '"' + str(slot) + '"' in line and '= -1 ENOENT' in line
            for line in r['selected']:
                assert '"' + str(slot) + '"' in line and re.search(r'=\s*\d+<', line)
            if r['state'] in ('higher83', 'same-stamp47') and not r['exit']:
                n = str(EXPECTED[r['state']])
                assert any('"' + mini['inputs'][n]['object'] + '"' in line and re.search(r'=\s*\d+<',line)
                           for line in lines), (label, n)
            if r['pre_slot']:
                assert r['pre_slot'][4] == digest(raw('provider-bytes/' + r['state'] + '.script'))
        if r['product']:
            f = r['product']
            if f['sha256'] not in elfs:
                zstd = raw('elf/' + f['sha256'] + '.zst')
                assert digest(zstd) == f['zstd_sha256']
                body = subprocess.check_output(['zstd', '-qdc'], input=zstd)
                assert len(body) == f['size'] and body[:7] == bytes.fromhex('7f454c46020101') and body[18:20] == b'\xb7\x00'
                assert digest(body) == f['sha256']
                elfs[f['sha256']] = f['size']
            q = r['qemu']
            for name, rr in [('list', q['list']), *[(s, v[0]) for s, v in q['checks'].items()]]:
                for stream in ('stdout', 'stderr'):
                    assert digest(gzip.decompress(raw(base + name + '.' + stream + '.gz'))) == rr[stream]
            listed = gzip.decompress(raw(base + 'list.stdout.gz')).decode().splitlines()
            assert sorted(s.removesuffix(': test') for s in listed if s.endswith(': test')) == q['tests']
    verdict = {'incomplete': True, 'observed': sorted(rows)} if partial else verify_rows(rows)
    if not partial:
        assert verdict == obj('terminal.json')
    return {'zip_sha256': digest(data), 'zip_size': len(data), 'files': len(z.namelist()), 'elfs': elfs, 'verdict': verdict}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('zip', nargs='?', default='-')
    p.add_argument('--partial', action='store_true', help='Verify completed raw visits of a failed job only')
    a = p.parse_args()
    result = audit(sys.stdin.buffer.read() if a.zip == '-' else Path(a.zip).read_bytes(), a.partial)
    print(json.dumps(result, indent=2, sort_keys=True))
    if not a.partial and result['verdict']['failures']:
        raise SystemExit(1)
