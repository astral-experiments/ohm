"""Offline readback of the unedited native artifact archives, including negative controls."""
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import verify

REGISTRY=json.loads((HERE/'artifacts.json').read_bytes())
RUNS={41147017442,41147709004,41148107094,41148393603,41148948376}
ORIGINAL=json.loads((HERE.parent/'failed-original.json').read_bytes())
raw_failures=(HERE/'original-integration-failures.txt').read_bytes()
assert sorted(x.decode() for x in re.findall(rb'(?m)^\S+ test (\S+) \.\.\. FAILED\r?$',raw_failures))==ORIGINAL['names']
assert len(REGISTRY)==11 and {v['workflow_run'] for v in REGISTRY.values()}==RUNS
proof=[]
for name,reg in sorted(REGISTRY.items()):
    path=HERE/'raw'/(name+'.zip')
    assert path.stat().st_size==reg['archive_size']
    gh=json.loads((HERE/'actions'/(str(reg['workflow_run'])+'.json')).read_bytes())
    meta,=[v for v in gh['artifacts'] if v['id']==reg['artifact_id']]
    assert meta['name']==name and meta['size_in_bytes']==reg['archive_size']
    assert meta['digest']=='sha256:'+reg['archive_sha256'] and hashlib.sha256(path.read_bytes()).hexdigest()==reg['archive_sha256']
    assert (meta['workflow_run']['id'],meta['workflow_run']['head_sha'],meta['workflow_run']['repository_id'])==(reg['workflow_run'],reg['workflow_sha'],1319437234)
    row=verify.row(path)
    if name in ('candidate-overlay-standalone','candidate-overlay-combined'):
        with zipfile.ZipFile(path) as z:
            cmd=json.loads(z.read('build-cert/official-build.json'));assert cmd['exit']==101
            raw=gzip.decompress(z.read('build-cert/official-build.stdout.gz'))
            assert hashlib.sha256(raw).hexdigest()==cmd['stdout']
            errors=[v['message'] for line in raw.splitlines() if (v:=json.loads(line)).get('message',{}).get('level')=='error']
            assert len(errors)==2
            assert {e['spans'][0]['line_start'] for e in errors}=={1938,2023} and all(e['message']=='custom attribute panicked' and e['spans'][0]['file_name']=='tests/testsuite/global_cache_tracker.rs' and 'stable-registry/bin/cargo' in e['children'][0]['message'] for e in errors)
            row['test_setup_exit']=101
    proof.append(row)
print(json.dumps(proof,sort_keys=True,indent=2))
