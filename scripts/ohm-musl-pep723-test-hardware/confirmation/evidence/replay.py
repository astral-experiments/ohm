"""Recompute the paired instruction endpoints and storage from the retained original records."""

import gzip
import hashlib
import json
import sys
import tarfile
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import read as confirmation

score = confirmation.score


def replay(phase):
    folder = HERE / phase
    official = json.loads((folder / 'originals.json').read_bytes())
    report = json.loads((folder / 'report.json').read_bytes())
    assert official['status'] == 'completed' and official['conclusion'] == 'success'
    assert official['phase'] == report['phase'] == phase and official['head'] == report['head']
    positions = [(b, p) for b in range(1, 7) for p in (1, 2)]
    assert [(r['block'], r['position']) for r in official['positions']] == positions
    assert len(report['positions']) == 12
    for field in ('boot', 'runner', 'host'):
        assert len({v[field] for v in report['positions']}) == 12
    deltas = []
    with tarfile.open(folder / 'counters.tar.gz') as tar:
        names = tar.getnames()
        assert len(set(names)) == len(names) and all(i.isfile() for i in tar.getmembers())
        for ref, row in zip(official['positions'], report['positions'], strict=True):
            prefix = f"{ref['block']:02}-{ref['position']}/"
            def member(name):
                return tar.extractfile(prefix + name).read()
            manifest = dict(line.split('  ', 1)[::-1] for line in member('POSITION.sha256').decode().splitlines())
            def raw(name):
                data = member(name)
                assert hashlib.sha256(data).hexdigest() == manifest[name]
                return data
            def doc(name):
                return json.loads(raw(name))
            assert row['source_zip'] == ref['sha256'] and ref['job_conclusion'] == 'success'
            enrollment = doc('counts/confirmation-host.json')
            assert all(enrollment[k] == row[k] for k in ('block', 'position', 'boot', 'head', 'order'))
            assert enrollment['order'] == {1: 'PC', 2: 'CP'}[ref['position']]
            assert enrollment['run'] == official['run'] == report['run'] and enrollment['phase'] == phase
            score.calibration(lambda name: raw('counts/calibration/' + name))
            pair = doc('counts/pair.json')
            assert pair['argv'] == score.q.REG['ordinary_argv'] and pair['boot_id'] == row['boot']
            counts = {}
            bodies = []
            found = {'warm': {}, 'empty': {}}
            for arm in 'PC':
                base = f'counts/{arm}/'
                term = doc(base + 'terminal.json')
                bodies.append(term['body'])
                counts[arm] = {}
                for visit in ('edit', 'repeat'):
                    where = base + visit + '/'
                    counts[arm][visit] = score.clock(doc(where + 'clock.json'))
                    typed, _ = score.q.typed(raw(where + 'stdout.raw'))
                    assert typed == term['typed'][visit] and typed['typed'] == 36
                    trace = term['native'][visit]
                    expected = ['compact_str', 'ruff_python_ast', 'zmij'] if arm == 'P' else ['ruff_python_ast'] if visit == 'edit' else []
                    assert trace['full'] == expected and trace['cached'] == (['ruff_python_ast'] if (arm, visit) == ('C', 'repeat') else [])
                    assert trace['target_ld_pid'] > 0 and term['body']['edit'] == trace['elf']
                counts[arm]['edit+repeat'] = counts[arm]['edit'] + counts[arm]['repeat']
                inventories = {}
                for visit in ('old', 'edit', 'wrong', 'repair', 'empty-new'):
                    stream = f'flanks/{arm}/{visit}/native-'
                    tests = gzip.decompress(raw(stream + 'list.stdout.gz')).decode().splitlines()
                    inventories[visit] = {s.removesuffix(': test') for s in tests if s.endswith(': test')}
                    run = gzip.decompress(raw(stream + 'full.stdout.gz')).decode()
                    passed = 49 if visit == 'old' else 52 if visit == 'wrong' else 53
                    failed = int(visit == 'wrong')
                    assert len(inventories[visit]) == passed + failed
                    assert f'{passed} passed; {failed} failed;' in run
                    failed_tests = [line for line in run.splitlines() if line.startswith('test ') and line.endswith(' ... FAILED')]
                    assert failed_tests == (['test script::tests::last_closing_delimiter_discards_following_comments ... FAILED'] if failed else [])
                assert inventories['old'] < inventories['edit'] == inventories['wrong'] == inventories['repair'] == inventories['empty-new']
                invalid = [json.loads(s) for s in gzip.decompress(raw(f'flanks/{arm}/invalid/stdout.gz')).splitlines()]
                errors = [r['message'] for r in invalid if r['reason'] == 'compiler-message' and r['message']['level'] == 'error']
                assert invalid[-1] == {'reason': 'build-finished', 'success': False} and len(errors) == 1
                assert errors[0]['code']['code'] == 'E0308'
                [span] = [sp for sp in errors[0]['spans'] if sp['is_primary']]
                assert [span[k] for k in ('file_name', 'line_start', 'byte_start', 'byte_end')] == ['crates/ruff_python_ast/src/script.rs', 300, 9295, 9317]
                for stage, location in [('warm', base + 'measured-final/'), ('empty', f'flanks/{arm}/empty-new/')]:
                    allocation = score.allocated(json.loads(gzip.decompress(raw(location + 'allocated-inodes.json.gz'))))
                    assert allocation['allocated_unique'] == pair['storage'][stage][arm]
                    found[stage][arm] = allocation['physical_payloads']
            assert bodies[0] == bodies[1] and counts == row['counts']
            assert len({bodies[0][state] for state in ('old', 'edit', 'wrong')}) == 3
            for stage, arms in found.items():
                growth = {k: arms['C'].get(k, 0) - arms['P'].get(k, 0) for k in arms['P'].keys() | arms['C'].keys()}
                assert growth == pair['storage'][stage]['physical_payload_count_delta'] and all(n <= 0 for n in growth.values())
            deltas.append({stage: v['C'] - v['P'] for stage, v in pair['storage'].items()})
    for metric in ('edit', 'repeat', 'edit+repeat'):
        result = confirmation.endpoint(report['positions'], metric)
        assert result == report['metrics'][metric]
        lo, hi = [x['decimal'] for x in result['interval_96_14']]
        print(f"{phase:12} {metric:12} {result['median']['decimal']:.5f}x ({lo:.5f}, {hi:.5f})")
    assert deltas == report['storage_C_minus_P'] and report['qualifies']
    print(f"{'':12} warm bytes   {median(s['warm'] for s in deltas):+.0f}, empty bytes {median(s['empty'] for s in deltas):+.0f}")
    boots = {p['boot'] for p in report['positions']}
    assert len(boots) == 12
    return boots


if __name__ == '__main__':
    if not __debug__:
        raise RuntimeError('use Python without -O')
    phases = sys.argv[1:] or ['primary', 'independent']
    assert phases in (['primary'], ['independent'], ['primary', 'independent'])
    seen = set()
    for phase in phases:
        boots = replay(phase)
        assert seen.isdisjoint(boots)
        seen.update(boots)
