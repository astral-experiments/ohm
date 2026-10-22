"""Check each recipient uv CLI after the APFS allocation endpoint is recorded."""
import hashlib, json, os, re, shlex, subprocess, sys
from pathlib import Path
from private_layout import binary_scope
root=Path('/private/tmp/ohm-benchmarks-1.99.0-6/apfs-ready-tests/disk')
evidence=Path(sys.argv[1]).resolve()
assert evidence.is_relative_to(root/'evidence')
state=json.loads((evidence/'results.json').read_text())
assert state['state']=='complete' and state['cell'].startswith('uv-')
assert state['idle']['idle_seconds']>=30
volume=json.loads((evidence/'volume.json').read_text());mount=Path(volume['mount'])
proof=[];test_scopes=set()
for row in state['completed_worktrees']:
    number=row['number'];target=mount/'targets'/str(number);worktree=mount/'worktrees'/str(number)
    binary=target/'debug/uv'
    assert binary.is_file() and os.access(binary,os.X_OK)
    # Select the executable Cargo actually ran at this worktree's last integration step.
    invocations=[s['detail'] for s in state['steps'] if s['kind']=='command' and s['worktree']==number and '--test' in s['detail']['command'] and 'pip_install' in s['detail']['command']]
    assert invocations, 'No recorded integration-test command'
    selection_log=Path(invocations[-1]['log'])
    assert hashlib.sha256(selection_log.read_bytes()).hexdigest()==invocations[-1]['log_sha256']
    candidates=[]
    for line in selection_log.read_text().splitlines():
        match=re.fullmatch(r"\s*Running `(.+)`",line)
        if match:
            arguments=shlex.split(match.group(1))
            if arguments and Path(arguments[0]).name.startswith('pip_install-'):
                candidates.append(Path(arguments[0]))
    assert len(candidates)==1,candidates
    test_binary=candidates[0]
    assert test_binary.is_file() and os.access(test_binary,os.X_OK)
    assert test_binary.resolve().is_relative_to(mount.resolve())
    scope=binary_scope(target,test_binary)
    if scope.startswith('workspace/'):
        assert state['selector']=='ohm-1.99.0-6'
        assert scope in state['private_inode_audit']['namespaces']
    assert scope not in test_scopes, 'Different worktrees selected the same private test namespace'
    test_scopes.add(scope)
    env=os.environ.copy()
    env.update(state['environment'])
    env['CARGO_BIN_EXE_uv']=str(binary);env['NEXTEST_BIN_EXE_uv']=str(binary)
    env['CARGO_MANIFEST_DIR']=str(worktree/'crates/uv')
    env['CARGO_TARGET_DIR']=str(target)
    env.pop('PYTHONSAFEPATH',None)
    arguments=[str(test_binary),'pip_install::registry_wheel_size_is_advisory','--exact','--nocapture']
    result=subprocess.run(arguments,cwd=worktree/'crates/uv',env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=180)
    log=evidence/('runtime-'+str(number)+'.log');log.write_text(result.stdout)
    assert result.returncode==0 and re.search(r'test result: ok\. 1 passed; 0 failed;',result.stdout),str(log)
    proof.append({'worktree':number,'binary':str(binary),'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'selection_log':str(selection_log),'selection_log_sha256':hashlib.sha256(selection_log.read_bytes()).hexdigest(),'test_binary':str(test_binary),'test_binary_scope':scope,'test_binary_sha256':hashlib.sha256(test_binary.read_bytes()).hexdigest(),'log':str(log),'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),'returncode':result.returncode,'tests':1})
    (evidence/'runtime-checks.json').write_text(json.dumps({'scope':'Post-endpoint correctness only; no build commands or allocation claims','checks':proof},indent=2)+'\n')
print('Post-endpoint uv runtime checks passed:',len(proof))
