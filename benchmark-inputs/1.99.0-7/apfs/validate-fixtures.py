"""Check the unchanged published fixtures with both installed release formatters."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from release_guard import verify_release
verify_release()

ROOT = Path('/private/tmp/ohm-benchmarks-1.99.0-7')
REPO = ROOT / 'ohm'
sys.path.insert(0, str(REPO / 'scripts'))
import replay_sessions as replay

probe = ROOT / 'apfs/format-probe/validation-2'
probe.mkdir(parents=True,exist_ok=True)
prior = json.loads((Path('/private/tmp/ohm-benchmarks-1.99.0-6/apfs/bench/fixture-validation.json')).read_text())
rows = []
env = {k:v for k,v in os.environ.items() if not k.startswith(('CARGO_', '__CARGO_', 'RUST')) and k != 'PYTHONSAFEPATH'}
env.update(CARGO_HOME='/private/tmp/codex-cargo-home', CARGO_NET_OFFLINE='true')
for item in prior['formatting_compatibility']:
    fixture = REPO / 'scripts/session_replays' / item['fixture']
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == item['fixture_sha256']
    scenario = replay.load_scenario(fixture)
    source = ROOT / 'apfs/disk/repos' / (scenario.project + '.git')
    worktree = probe / fixture.stem
    subprocess.run(['git', '-C', str(source), 'worktree', 'add', '--detach', str(worktree), scenario.base_revision], check=True)
    for setup in scenario.setup_patches:
        subprocess.run(['git', 'apply', '-'], cwd=worktree, input=replay.setup_patch_bytes(fixture.parent, setup), check=True)
    study = replay.Replay(replay.parser().parse_args(['--project',scenario.project,'--scenario',str(fixture),'--output-dir',str(probe/(fixture.stem+'-replay'))]))
    edits = []
    canonical_edits = []
    checks = []
    for endpoint in ['base', 'final']:
        if endpoint == 'final':
            for step in scenario.steps:
                if step['kind'] == 'edit':
                    patch = study.patch_bytes(scenario, source, step)
                    edits.append(hashlib.sha256(patch).hexdigest())
                    # Git now chooses ten-digit IDs for the larger uv object
                    # store. Compare the complete patch with the old nine-digit
                    # index headers; neither the source edit nor runner changes.
                    canonical = re.sub(rb'(?m)^index ([0-9a-f]+)\.\.([0-9a-f]+)(.*)$', lambda m: b'index '+m[1][:9]+b'..'+m[2][:9]+m[3], patch)
                    canonical_edits.append(hashlib.sha256(canonical).hexdigest())
                    subprocess.run(['git','apply','-'], cwd=worktree, input=patch, check=True)
            assert all(actual == old or canonical == old for actual,canonical,old in zip(edits,canonical_edits,item['replay_edit_sha256'],strict=True))
        for selector in ['1.99.0','ohm-1.99.0-7']:
            env['CARGO_TARGET_DIR'] = '/private/tmp/codex-cargo-targets/ohm/isolated/release-1.99.0-7/format-probe/' + fixture.stem
            command = ['cargo','+'+selector,'fmt','--all','--','--check']
            result = subprocess.run(command, cwd=worktree, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            log = probe / (fixture.stem+'-'+endpoint+'-'+selector+'.log')
            log.write_text(result.stdout)
            assert result.returncode == 0, str(log)
            checks.append({'endpoint':endpoint,'selector':selector,'returncode':0,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
    rows.append({'fixture':fixture.name,'fixture_sha256':item['fixture_sha256'],'replay_edit_sha256':edits,'previous_replay_edit_sha256':item['replay_edit_sha256'],'nine_digit_index_header_sha256':canonical_edits,'source_edits_unchanged_from_previous_release':True,'checks':checks})
(ROOT/'apfs/bench/fixture-validation.json').write_text(json.dumps({'passed':True,'checked_at':time.time(),'release':'ohm-1.99.0-7','formatting_compatibility':rows},indent=2)+'\n')
print('All three fixtures passed base and final formatting checks with both toolchains', flush=True)
