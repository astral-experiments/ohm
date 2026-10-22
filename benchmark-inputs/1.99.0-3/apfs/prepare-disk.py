"""Prepare immutable source objects for the published APFS study."""
import hashlib, json, os, subprocess, sys
from pathlib import Path

root=Path('/private/tmp/ohm-benchmarks-1.99.0-3/apfs/disk')
repo=Path('/private/tmp/ohm-benchmarks-1.99.0-3/ohm')
sys.path.insert(0,str(repo/'scripts'))
import replay_sessions as replay
root.mkdir(exist_ok=True)
(root/'repos').mkdir(exist_ok=True)
def command(args,**kw):return subprocess.check_output(args,**kw).decode().strip()
def git(source,*args,**kw):return command(['git','-C',str(source),*args],**kw)
proof={}
for project,fixture in [('ruff','disk-1.99.0-1-ruff.json'),('uv','disk-1.99.0-1-uv.json')]:
    original=Path('/Users/charliemarsh/code/oss')/project
    assert git(original,'rev-parse','--show-toplevel')==str(original)
    assert git(original,'config','user.email')=='charlie.r.marsh@gmail.com'
    source=root/'repos'/(project+'.git')
    if not source.exists():command(['git','clone','--bare','--shared',str(original),str(source)])
    git(source,'config','user.name','Charlie Marsh')
    git(source,'config','user.email','charlie.r.marsh@gmail.com')
    git(source,'config','maintenance.auto','false')
    scenario=replay.load_scenario(repo/'scripts/session_replays'/fixture)
    if project=='uv':
        prior=json.loads((repo/'scripts/benchmark_results/disk-1.98.1-2.json').read_text())['uv_runtime_setup']
        patch=(repo/'scripts/session_replays/patches/uv-runtime-bin-path.patch').read_bytes()
        assert hashlib.sha256(patch).hexdigest()==prior['setup_patch_sha256']
        index=root/'uv-setup-index';env=os.environ|{'GIT_INDEX_FILE':str(index)}
        for key in ('derived_base','derived_first_edit'):
            item=prior[key]
            git(source,'read-tree',item['original_revision'],env=env)
            git(source,'apply','--cached','-',input=patch,env=env)
            assert git(source,'write-tree',env=env)==item['tree']
            assert hashlib.sha256(item['commit_object'].encode()).hexdigest()==item['commit_object_sha256']
            assert git(source,'hash-object','-t','commit','-w','--stdin',input=item['commit_object'].encode())==item['derived_revision']
    setup=json.loads((repo/'scripts/session_replays/disk-1.99.0-1-setup.json').read_text())['projects'][project]
    patch=(repo/'scripts/session_replays'/setup['formatting_patch']['patch']).read_bytes()
    assert hashlib.sha256(patch).hexdigest()==setup['formatting_patch']['sha256']
    env=os.environ|{'GIT_INDEX_FILE':str(root/(project+'-formatting-index'))}
    for item in setup['derived'].values():
        git(source,'read-tree',item['original_revision'],env=env)
        git(source,'apply','--cached','-',input=patch,env=env)
        assert git(source,'write-tree',env=env)==item['tree']
        assert hashlib.sha256(item['commit_object'].encode()).hexdigest()==item['commit_object_sha256']
        assert git(source,'hash-object','-t','commit','-w','--stdin',input=item['commit_object'].encode())==item['derived_revision']
    for revision in sorted(replay.Replay.required_commits(None,scenario)):
        assert git(source,'cat-file','-t',revision)=='commit'
    proof[project]={'source':str(source),'fixture':fixture,'fixture_sha256':hashlib.sha256(scenario.path.read_bytes()).hexdigest(),'required_commits':sorted(replay.Replay.required_commits(None,scenario))}
    for name in ('AGENTS.md','rust-toolchain.toml'):
        result=subprocess.run(['git','-C',str(source),'show',scenario.base_revision+':'+name],capture_output=True)
        if result.returncode==0:(root/(project+'-'+name)).write_bytes(result.stdout)
(root/'source-preparation.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof,indent=2))
