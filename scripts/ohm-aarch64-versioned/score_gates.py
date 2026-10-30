"""Bind the new statistical cohort to its two immutable native acquisitions and independently re-opened outputs."""
from hashlib import sha256
import json
import os
from pathlib import Path
import runpy
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from seal_native import FIRST,FRESH,state
from ruff_subjects import DEFAULT_SOURCE,DEFAULT_DRIVERS,REG,rt
base=runpy.run_path(str(HERE.parent/'ohm-aarch64-fallback/score_gates.py'))
def get(p):return json.loads(p.read_bytes())
def main(stage):
    assert stage in ('pilot','confirmation')
    protocol=get(HERE/'admissible-native.json')
    assert protocol['cargo_elf']==REG['cargo_elf'] and protocol['sources']==DEFAULT_SOURCE and protocol['drivers']==DEFAULT_DRIVERS
    for source in (FIRST,FRESH):
        actual=state('gh',*source)
        if source==FIRST:
            assert json.loads(json.dumps(actual))==protocol['inherited_native_run']
        else:
            assert actual['workflow']=='success' and actual['artifacts']==protocol['immutable_artifacts']
            assert all(row[0]=='success' for row in actual['jobs'].values())
    proof=HERE/'qualified';ruff=get(proof/'ruff.json');providers=get(proof/'providers.json')
    assert sha256((proof/'ruff.json').read_bytes()).hexdigest()==protocol['native_readback']
    assert sha256((proof/'providers.json').read_bytes()).hexdigest()==protocol['provider_readback']
    assert providers['all_independent_readbacks']=={k:v for k,v in protocol['native_members'].items() if k!='ruff'}
    assert providers['native_command_counts']=={'signed':108,'classic':108,'aware':108,'migrate-signed':42,'migrate-classic':42,'legacy-writer':36}
    assert ruff['reference']==protocol['reference'] and ruff['sources']==DEFAULT_SOURCE and ruff['drivers']==DEFAULT_DRIVERS and ruff['cargo']==REG['cargo_elf']
    assert ruff['terminal']==protocol['native_terminal'] and ruff['argv_count']==protocol['actual_argc'] and ruff['namespace_positions']==protocol['namespace_positions']
    info={'sources':ruff['sources'],'cargo':ruff['cargo'],'admitted':protocol,'native_gate':ruff,'normalized_argv_sha256':ruff['normalized_argv_sha256'],
          'native_readback':protocol['native_readback'],'provider_readback':protocol['provider_readback']}
    (rt.LOG/'independent-admissions.json').open('x').write(json.dumps(info,indent=2,sort_keys=True)+'\n')
    if stage=='confirmation':
        pilot=get(HERE/'qualified-pilot.json')
        raw=base['install'](pilot,'gnu-versioned-pilot-readback','analysis.json')
        assert sha256(raw).hexdigest()==pilot['analysis'] and json.loads(raw)['all_twelve_pilot_ratios_strictly_above_two']
        (rt.LOG/'independent-pilot.json').open('xb').write(raw)
if __name__=='__main__':main(sys.argv[1])
