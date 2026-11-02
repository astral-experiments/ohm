"""Exercise the genuine child, pthread, fork and exec lineage without requiring a PMU."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import struct
import sys

here = Path(__file__).resolve().parent
out = Path(sys.argv[1]).resolve()
out.mkdir()
p = runpy.run_path(str(here / 'per_rustc.py'))
read = p['read_counter']
assert read(struct.pack('=4Q', 1200, 100, 100, 2))['instructions'] == 1200
for invalid in [b'', (0,100,100,2), (1,100,99,2), (1,0,0,2), (1,1,1,0)]:
    try:
        read(invalid if isinstance(invalid, bytes) else struct.pack('=4Q', *invalid))
    except ValueError:
        pass
    else:
        raise ValueError('malformed counter accepted')
events = p['EVENTS']
workload = here / 'workload'
observed = {}
for mode, expected_execs in [('serial',1), ('threads',1), ('fork',1), ('reexec',2)]:
    visit = out / mode
    visit.mkdir()
    successes = []
    events['capture'](visit, [str(workload), mode, '10000'], {'LC_ALL':'C','PATH':'/usr/bin:/bin'},
                      str(visit), events['file_id'](workload), lambda pid, old, snapshot: successes.append(pid))
    raw = json.loads((visit / 'kernel-events.json').read_bytes())
    tree = events['decode'](raw)
    assert len(successes) == expected_execs and tree['exits'][raw['root']] == 0
    observed[mode] = [r[1] >> 16 for r in raw['events'] if isinstance(r[1], int) and os.WIFSTOPPED(r[1])]
assert observed['threads'].count(3) == 3 and observed['fork'].count(1) == 1
result = {'real_kernel_events': observed, 'negative_raw_reads': 5, 'scores': False,
          'sources': {n:hashlib.sha256((here/n).read_bytes()).hexdigest() for n in
                      ('exec_events.py','pmu.c','per_rustc.py','workload.c')}}
(out / 'verified.json').write_text(json.dumps(result, sort_keys=True, indent=2))
print(json.dumps(result))
