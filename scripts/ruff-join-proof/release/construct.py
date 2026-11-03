from pathlib import Path
import hashlib,json,shutil,subprocess

src=Path(__file__).resolve().parent
plan=json.loads((src/'plan.json').read_bytes())
def build_matched(sdk,environment,root,run):
    git=lambda *args:subprocess.check_output(['git','-C',root,*args],text=True).strip()
    extra=src/'ci-green.bundle'
    assert git('rev-parse','HEAD')==plan['diagnostic_child'] and sdk.hf(extra)==plan['bundle']
    git('fetch',str(extra),'HEAD:refs/qa/ci-correct-test')
    assert git('rev-parse',plan['child']+'^{tree}')==plan['tree']
    delta=subprocess.check_output(['git','-C',root,'diff-tree','--no-commit-id','--raw','--no-abbrev','--no-renames','-r','-z',plan['diagnostic_child'],plan['child']])
    assert hashlib.sha256(delta).hexdigest()==plan['test_only_delta_tree'] and git('merge-base',plan['diagnostic_child'],plan['child'])==plan['diagnostic_child']
    env={**environment,'CARGO_PROFILE_RELEASE_DEBUG':'0','CARGO_PROFILE_RELEASE_CODEGEN_UNITS':'1','CARGO_PROFILE_RELEASE_LTO':'thin','CARGO_INCREMENTAL':'0','CFG_RELEASE_CHANNEL':'dev'}
    argv=['cargo','+ohm','-Zohm-defaults=no','build','--locked','--release','-p','cargo','--bin','cargo','--features','ohm-defaults,all-static','-j8','--message-format=json-render-diagnostics']
    bodies={'signed':sdk.sdk/'bin/cargo'};receipts={}
    for role,commit in [('release-parent',plan['parent']),('release-child',plan['child'])]:
        env.update(CARGO_TARGET_DIR=str(sdk.root/(role+'-isolated-target')),CARGO_BUILD_BUILD_DIR=str(sdk.root/(role+'-isolated-shared')))
        assert all(not Path(env[k]).exists() for k in ('CARGO_TARGET_DIR','CARGO_BUILD_BUILD_DIR'))
        git('switch','--detach',commit);assert git('rev-parse','HEAD')==commit and not git('status','--porcelain')
        log=run(sdk,env,'factory-'+role,argv,root)
        rows=[json.loads(l)for l in log.read_text().splitlines()if l.startswith('{')]
        exe,=[Path(r['executable'])for r in rows if r['reason']=='compiler-artifact'and r.get('executable')and r['target']['name']=='cargo'and'bin'in r['target']['kind']]
        assert any(exe.resolve().is_relative_to(Path(env[k]))for k in('CARGO_TARGET_DIR','CARGO_BUILD_BUILD_DIR'))
        dst=sdk.proof/('cargo-'+role);shutil.copy2(exe,dst);v=subprocess.check_output([dst,'-vV'],env=env,text=True)
        assert commit in v
        bodies[role]=dst;receipts[role]={'cargo_source':commit,'tree':git('rev-parse','HEAD^{tree}'),'version':v,'bytes':dst.stat().st_size,'sha256':sdk.hf(dst),'argv':argv,'profile':{k:env[k] for k in env if k.startswith('CARGO_PROFILE_RELEASE')or k in('CARGO_INCREMENTAL','CFG_RELEASE_CHANNEL')},'rustc':subprocess.check_output(['rustc','+ohm','-vV'],env=env,text=True)}
        sdk.put(sdk.proof/'release-factories.json',receipts)
    return bodies
