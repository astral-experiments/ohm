"""Reopen the complete native observation from 41145570612, including its failed reporter."""
import hashlib
import io
import json
from pathlib import Path
import runpy
import sys
import zipfile


def readback(data):
    sha = lambda x: hashlib.sha256(x).hexdigest()
    assert len(data) == 63867556 and sha(data) == 'bdd043c55996b4c05410f572b3122661990f7d75e38b2ed2d374ba409e5e5d11'
    frozen = Path(__file__).with_name('verify.py')
    assert sha(frozen.read_bytes()) == 'abbbdebcc4bdf0c5cfac4a14f6266d9b4046773f29bf55e9535b76df0ef1636e'
    verifier = runpy.run_path(str(frozen))
    physical = verifier['audit'](data, partial=True)
    z = zipfile.ZipFile(io.BytesIO(data))
    assert z.testzip() is None and len(z.namelist()) == 267
    parent, child = (json.loads(z.read('atomic-subjects/' + key + '-sdk.json')) for key in ('P', 'C'))
    build = json.loads(z.read('atomic-subjects/atomic-candidate.json'))
    assert len(parent) == len(child) == 119 and parent.keys() == child.keys()
    assert [k for k in child if child[k] != parent[k]] == [build['driver_path']]
    assert child[build['driver_path']] == build['driver'] and parent[build['driver_path']] == build['parent_driver']
    assert child['bin/cargo'][0] == '9fb29f6abecad05acb6015990615c5fbb435a5907543f0bd33cf88cada4f5826'
    base = 'observed-ruff-db/receipts/'
    original = json.loads(z.read(base + 'observation.json'))
    rows = original['rows']
    assert len(rows) == 17 and sorted(rows) == physical['verdict']['observed']
    assert all(row == json.loads(z.read(base + 'visits/' + label + '/verdict.json')) for label, row in rows.items())
    outcome = verifier['verify_rows'](rows)
    assert not outcome['failures']
    expected = {'absent': 0, 'higher83': 83, 'same-stamp47': 47, 'malformed': None, 'removed': 0}
    phases = {}
    for family in ('ordinary', 'forced', 'empty'):
        phases[family] = {}
        for state, exit_code in expected.items():
            name = family + '-' + state
            row = rows[name]
            actual = json.loads(z.read(base + 'visits/' + name + '/link-search.json'))
            assert actual['root']['terminal'] == ([1] if exit_code is None else [0])
            assert row['exit'] == (101 if exit_code is None else 0)
            assert ((row['qemu'] or {}).get('list') or {}).get('exit') == exit_code
            assert len(row['missing']) == (1 if state in ('absent', 'removed') else 0)
            assert len(row['selected']) == (0 if state in ('absent', 'removed') else 4)
            if row['product']:
                assert row['product']['sha256'] == rows['empty-' + state]['product']['sha256']
            phases[family][state] = {
                'cargo': row['exit'], 'qemu': exit_code, 'typed': row['typed'],
                'full_rustc': sum(not r[1] for r in row['rustcs']),
                'link_only_rustc': sum(r[1] for r in row['rustcs']),
                'root_gnu_ld': [actual['root']['pid'], *actual['root']['terminal']],
                'lookup_open_success': len(row['selected']), 'lookup_ENOENT': len(row['missing']),
                'total_fd_open_calls': len(actual['opens']),
                'all_ENOENT': sum(o['errno'] == 'ENOENT' for o in actual['opens']),
                'complete_elf': (row['product'] or {}).get('sha256'),
            }
    return {'official_run': 41145570612, 'official_job_conclusion': 'failure in Python report import after all native commands',
            'artifact': 13021026409, 'zip_sha256': physical['zip_sha256'], 'files': physical['files'],
            'reviewed_rust': original['compiler']['reviewed'], 'source_built_rust': original['compiler']['source'],
            'cargo': 'c18e91b514b2c4e4966c9ab03232c804af3e1b57', 'phases': 17,
            'failed_registered_gates_on_offline_replay': outcome['failures'], 'elf_bytes': physical['elfs'],
            'ordinary_same_stamp': [rows['ordinary-' + s]['pre_slot'] for s in ('higher83', 'same-stamp47', 'malformed')],
            'directions': phases}


if __name__ == '__main__':
    source, = sys.argv[1:]
    result = readback(sys.stdin.buffer.read() if source == '-' else Path(source).read_bytes())
    print(json.dumps(result, sort_keys=True, indent=2))
