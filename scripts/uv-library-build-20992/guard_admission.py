"""Check both independent admissions before a hosted build can start."""
from pathlib import Path
from hashlib import sha256
import json, os, subprocess, sys

HERE=Path(__file__).resolve().parent
BRANCH='charlie/codex-20992-trait-origin-production-build-guard'
CHECK_BRANCH='charlie/codex-21041-trait-origin-production-check'
P='ac67101cb973e35ce8ff044cc8014c2c76bab69e';C='e4edbdd943f2ceac098ddde880e8f97a3bb3270f'
PAIR_ORDER=('parent-1','candidate-1','candidate-2','parent-2')
def sha(path): return sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_bytes())
def need(ok,msg):
    if not ok:raise ValueError(msg)
def git(path,*args): return subprocess.check_output(['git','-C',path,*args],text=True).strip()
def build(record,tag,proto,lock):
    observed=record['observed']; accepted=record['accepted']; role=tag[:-2];ids=lock['roles'][role];actual=accepted['source']
    need(accepted==observed|{'source':actual,'physical_sha256':record['digests']['physical']} and accepted['accepted'] is True and (accepted['label'],accepted['role'])==(tag,role),'build acceptance differs')
    need(actual['commit']==ids['pair_arm']['source']['commit'] and actual['tree']==ids['pair_arm']['source']['tree'] and actual['epoch']==ids['pair_arm']['source']['epoch'],'build source differs')
    need(record['sdk'][role]=={'source':actual['commit'],'driver':ids['driver'],'cargo':proto['signed_cargo_sha256']},'wrong production compiler')
    clk=record['clock']; need(clk['exit']==0 and clk['argv']==['/tmp/ohm-over18-named-test/sdk/bin/cargo',*proto['ordinary_cargo_argv']] and clk['wall_ns']==observed['wall_ns']>0,'local build command differs')
    need(accepted['bare_clock']==record['digests']['clock'] and accepted['independent_native']==record['digests']['cold'] and accepted['seed']==record['seed'] and 0<record['seed']['bytes']<=1<<30,'cold or ordinary control changed')
    need(record['physical']['exit']==0 and record['edit']['changed']==proto['fresh_registration']['changed'] and record['edit']['head']==proto['fresh_registration']['uv_A'],'local source guard failed')
    need(accepted['dirty']==['build_script_build','uv_cli','uv_python'] and accepted['products']==1794 and accepted['warm_and_cold_B_sidecars']==448 and accepted['kernel']==record['kernel_sha'],'local kernel or products differ')
    need(accepted['linked_transition']['A_objects']>0 and accepted['linked_transition']['B_objects']>0 and all(bool(x)for x in record['digests'].values()),'missing linked proof')
def activate(here,readers):
    gate=read(here/'activation.json');lock=read(here/'physical-roles.json');proto=read(here/'protocol.json')
    need(gate['active'] is True and gate['local_builds_order']==list(PAIR_ORDER),'approval closed')
    need(sha(here/'check-pilot.json')==gate['check_sha256'] and sha(here/'local-builds.json')==gate['builds_sha256'],'upstream prior gates changed')
    need(sha(here/'format-compatibility.json')==lock['native_two_way_sha256'] and sha(here/'owning-native-proof.json')==lock['native_owning_fixture_sha256'],'different native epoch or fixture')
    m=read(here/'format-compatibility.json');need(m['rmeta_epochs']==[43319,43319] and m['physical_sdk_receipts']=={k:v['pair_arm']['installed_sdk_receipt']for k,v in lock['roles'].items()},'wrong installed compilers')
    g=read(here/'local-builds.json');need(set(g)==set(PAIR_ORDER),'four genuine local builds required')
    for tag in PAIR_ORDER:build(g[tag],tag,proto,lock)
    score=read(here/'local-build-score.json')
    ratios=[g['candidate-'+str(i)]['observed']['wall_ns']/g['parent-'+str(i)]['observed']['wall_ns']for i in (1,2)]
    need(sha(here/'local-build-score.json')==gate['local_build_score_sha256'] and score['registration']==proto['fresh_registration']['pilot_registration'] and score['independent_native']is True and score['paired_candidate_over_parent']==ratios and score['repeated_three_percent_regression']==all(v>1.03 for v in ratios),'wrong original paired local build score')
    need(len({g[t]['seed']['sha256']for t in PAIR_ORDER})==4,'duplicate independent local seed')
    package=readers/'scripts/uv-callables-21041';sys.path.insert(0,str(package));from origin import enrollment
    official=read(package/'pair.json');study=read(package/'study.json');enrollment.admit(study,official)
    need(sha(package/'pair.json')==lock['pair_sha256'] and sha(package/'origin/pilot.json')==gate['check_sha256'] and sha(package/'origin/services.json')==lock['services_sha256'],'wrong neighboring SDK enrollment')
    need(git(readers,'rev-parse','HEAD')==gate['reader_commit'] and git(readers,'rev-parse','HEAD:scripts/uv-callables-21041')==lock['reader_trees']['scripts/uv-callables-21041'] and not git(readers,'status','--porcelain','--untracked-files=no'),'reader checkout changed')
    need(official['roles']==enrollment.ROLES and all(official['arms'][role]==lock['roles'][name]['pair_arm'] for name,role in zip(('parent','candidate'),enrollment.ROLES,strict=True)),'different two SDKs')
    enrollment.pilot(read(here/'check-pilot.json'),[lock['roles'][r]['driver']for r in ('parent','candidate')])
    return gate
if __name__=='__main__':
    e=os.environ;need(e['GITHUB_REPOSITORY']=='astral-experiments/ohm'and e['GITHUB_EVENT_NAME']=='workflow_dispatch'and e['GITHUB_REF']=='refs/heads/'+BRANCH and e['GITHUB_RUN_ATTEMPT']=='1'and e['GITHUB_SHA']==e['INPUT_SOURCE'],'wrong physical route')
    gate=activate(HERE,Path(e['GITHUB_WORKSPACE'])/'sdk-readers');need(gate['reader_commit']==e['CHECK_READER_HEAD'] and sha(HERE/'activation.json')==e['ACTIVATION_SHA256'],'wrong official workflow inputs')
    print('Four real build states and independently accepted check pilot verified')
