"""Verify frozen fixture and edit identities without running a release formatter or workload."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT/'ohm'
sys.path.insert(0,str(REPO/'scripts'))
import replay_sessions as replay
PRIOR = Path('/private/tmp/ohm-benchmarks-1.99.0-6/apfs/bench/fixture-validation.json')
prior = json.loads(PRIOR.read_text())
assert prior['passed'] and prior['release'] == 'ohm-1.99.0-6'
proof = []
indexes = ROOT/'apfs/disk/source-indexes'
indexes.mkdir(exist_ok=True)
for item in prior['formatting_compatibility']:
    fixture = REPO/'scripts/session_replays'/item['fixture']
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == item['fixture_sha256']
    scenario = replay.load_scenario(fixture)
    assert 'CARGO_UNSTABLE_OHM_READY_TESTS' not in scenario.environment
    source = ROOT/'apfs/disk/repos'/(scenario.project+'.git')
    env = os.environ|{'GIT_INDEX_FILE':str(indexes/fixture.stem)}
    def git(*args,**kw):
        return subprocess.check_output(['git','-C',str(source),*args],env=env,**kw)
    git('read-tree',scenario.base_revision)
    for setup in scenario.setup_patches:
        git('apply','--cached','-',input=replay.setup_patch_bytes(fixture.parent,setup))
    base_tree = git('write-tree').decode().strip()
    study = replay.Replay(replay.parser().parse_args(['--project',scenario.project,'--scenario',str(fixture),'--output-dir',str(ROOT/'apfs/metadata-probe')]))
    edits=[];canonical=[]
    for step in scenario.steps:
        if step['kind'] != 'edit':continue
        patch=study.patch_bytes(scenario,source,step)
        edits.append(hashlib.sha256(patch).hexdigest())
        value=re.sub(rb'(?m)^index ([0-9a-f]+)\.\.([0-9a-f]+)(.*)$',lambda m:b'index '+m[1][:9]+b'..'+m[2][:9]+m[3],patch)
        canonical.append(hashlib.sha256(value).hexdigest())
        git('apply','--cached','-',input=patch)
    assert all(a==old or c==old for a,c,old in zip(edits,canonical,item['replay_edit_sha256'],strict=True))
    proof.append({'fixture':item['fixture'],'fixture_sha256':item['fixture_sha256'],'base_tree':base_tree,'final_tree':git('write-tree').decode().strip(),'edit_sha256':edits,'canonical_edit_sha256':canonical,'source_edits_unchanged':True})
receipt={'passed':True,'checked_at':time.time(),'scope':'Fixture and edit metadata only; no formatting or measured workload commands executed','prior_reference':str(PRIOR),'prior_reference_sha256':hashlib.sha256(PRIOR.read_bytes()).hexdigest(),'fixtures':proof}
(ROOT/'apfs/fixture-metadata.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('Fixture metadata validated:',len(proof))
