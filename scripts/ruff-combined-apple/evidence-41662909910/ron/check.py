"""Reopen the original compiler reports, saved archive members, and native clients."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
summaries = {}
for dirname in sys.argv[2:]:
    run = root / dirname
    record = json.loads((run / 'result.json').read_bytes())
    role = record['role']
    assert role not in summaries
    steps = record['steps']
    for name, step in steps.items():
        if 'rc' not in step:
            continue
        stdout = (run / (name + '.stdout')).read_bytes()
        messages = [json.loads(line) for line in stdout.splitlines() if line.startswith(b'{')]
        assert messages[-1] == {'reason': 'build-finished', 'success': step['rc'] == 0}
        raw = (run / (name + '.stderr')).read_text()
        drivers = [line for line in raw.splitlines() if 'Running ' in line and '--crate-name ron ' in line]
        assert len(drivers) == step['ron_drivers']
        if drivers:
            assert len(drivers) == 1 and 'incremental=' in drivers[0] and 'embed-metadata=no' in drivers[0]
        if name in ('warm','missing-product') and role == 'signed':
            assert step['rc'] == 101 and any('failed to create encoded metadata from file' in e for e in step['errors'])
        elif name == 'invalid-client':
            assert step['rc'] == 101 and 'E0308' in step['errors']
        else:
            assert step['rc'] == 0
    images = {}
    for name, field in [('cold','cold'),('before-missing','missing_donor'),('repaired','repaired'),('clean','empty')]:
        image = record[field]
        if image is None:
            assert name == 'repaired' and role == 'signed'
            continue
        file = run / 'archives' / (name + '.rlib')
        assert hashlib.sha256(file.read_bytes()).hexdigest() == image['rlib']
        assert hashlib.sha256(file.with_suffix('.rmeta').read_bytes()).hexdigest() == image['rmeta']
        names = subprocess.check_output(['ar','t',str(file)], text=True).splitlines()
        objects = {}
        for member in names:
            if not member.endswith('.rcgu.o'):
                continue
            key = re.fullmatch(r'(.+)\.[a-z0-9]{7}\.rcgu\.o', member).group(1)
            assert key not in objects
            data = subprocess.check_output(['ar','p',str(file),member])
            objects[key] = hashlib.sha256(data).hexdigest()
        assert objects == image['native'] and len(objects) == 157
        images[name] = objects
    assert images['cold'] == images['clean']
    if role != 'signed':
        assert images['before-missing'] == images['repaired']
        assert steps['invalid-client']['rc'] == 101 and steps['edited-client']['rc'] == 0
    assert subprocess.check_output([run / 'original-executable']) == b'[17, 29]\n'
    assert subprocess.check_output([run / 'target/debug/green_stub_ron_replay']) == b'[17, 31]\n'
    summaries[role] = {'cargo': record['tools']['cargo'].splitlines()[0],
        'cold_warm_missing': [steps[name]['rc'] for name in ('cold','warm','missing-product')],
        'ron_rustcs': [steps[name]['ron_drivers'] for name in ('cold','warm','missing-product')],
        'independent_members':len(images['cold']), 'repaired_members':len(images.get('repaired', {})),
        'original_executable':steps['original-runtime']['sha256'], 'new_executable':steps['clean-runtime']['sha256']}
print(json.dumps(summaries, indent=2))
