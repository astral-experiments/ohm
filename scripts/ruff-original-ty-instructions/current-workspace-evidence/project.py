"""Project the authenticated receiver's original clock, process and ELF verdicts into a small report."""
from collections import Counter
from pathlib import Path
import hashlib
import json
import sys

with Path(sys.argv[1]).open('rb') as raw:
    data = json.load(raw)
assert data['archive']['digest'] == 'sha256:2ab6618f9f643f0c2ef9c192192c3b4955fe02f378432c8c28f01f8f8718f677'
result = {k:data[k] for k in ('run','head','job','runner','boot','archive','signed_sdk','graph','published_by_type','timers','verdicts','full_e2e','changed_workspace_libraries','decision','clean_section_diffs')}
result['paths'] = {p:u[0:3] for p,u in data['native_inventory'].items()}
result['processes'] = {}
for visit, trace in sorted(data['traces'].items()):
    assert not trace['unequal_counters']
    launch = Counter(row[0] for row in trace['real_execs'])
    scoped = Counter()
    for trigger,mode,name,count in trace['by_image']:
        scoped[trigger+'/'+mode] += count
    result['processes'][visit] = {
        'physical_launches': dict(sorted(launch.items())),
        'image_instructions': dict(sorted(scoped.items())),
        'fork_or_start_epochs': len(trace['inherited']),
        'outer': trace['outer'],
        'compiler_epochs': [row[:6] for row in trace['compilers']],
        'native_destinations': [[row['owner_mode'],row['owner'],row['output'].split('/ohm-foreign-join/',1)[1]]
                                for row in trace['native_linkers']],
        'cargo_dirty_units': len(data['dirty_units'][visit]),
    }
keys = ['unchanged-observed','repeat-observed']
for key in keys:
    assert result['processes'][key]['physical_launches'] == {'Wild':50,'full':1,'link-only':50}
    assert [(r[0],r[1]) for r in data['traces'][key]['compilers'] if r[0] != 'link-only'] == [('full','ron')]
    assert all(m == 'link-only' for m,_,_ in result['processes'][key]['native_destinations'])
assert data['graph']['members'] == 55 and len(result['paths']) == 102
assert len({x[0] for x in data['verdicts'].values()}) == 1
for v in ('edited_to_first','first_to_repeat','first_to_observed'): assert data['decision'][v] == []
assert len(data['decision']['edited_to_clean']) == 1
ordinary_diff, = data['clean_section_diffs'].values()
assert ordinary_diff['names'] == ['.note.gnu.build-id']
print(json.dumps(result,sort_keys=True,indent=1))
