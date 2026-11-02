"""Hosted intake. Reuse the published SDK and signature readers without any workload or score from their original experiment."""
from pathlib import Path
import gzip,json,os,shutil,subprocess,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from basis import CASE,HERE,LOCK,PLAN,Env,digest,filehash,read,write,setup
PARENT='5182899ebd032b193efe2cf7ebf37c4c0a6e2e88';BRANCH='charlie/codex-22536-source-session-check'
def git(d,*v):return subprocess.check_output(['git','-C',d,*v],text=True).strip()
def checked_binding():
    e=os.environ;assert e['GITHUB_REPOSITORY']=='astral-experiments/ohm'and e['GITHUB_REPOSITORY_ID']=='1319437234'and e['GITHUB_EVENT_NAME']=='workflow_dispatch'and e['GITHUB_REF']=='refs/heads/'+BRANCH and e['GITHUB_WORKFLOW_REF']==e['GITHUB_REPOSITORY']+'/.github/workflows/ci.yml@'+e['GITHUB_REF']and e['GITHUB_RUN_ATTEMPT']=='1'
    w=Path(e['GITHUB_WORKSPACE']).resolve();t=Path(e['RUNNER_TEMP']).resolve();co=w/'coordinator'
    assert git(co,'rev-parse','HEAD')==e['GITHUB_SHA']==e['REVIEWED_HEAD']and git(co,'rev-parse','HEAD^')==PARENT
    assert not git(co,'status','--porcelain','--untracked-files=no')and not git(co,'diff',PARENT,'HEAD','--','scripts/uv-client-22958','scripts/uv-callables-21041','scripts/handwritten-panel')
    assert HERE==co/'scripts/uv-check-22536';en=read(HERE/'dispatch-enrollment.json')
    assert en.get('local_native_gates_accepted')is True and en['submit_authority']=='explicit workflow_dispatch of the operator-reviewed exact SHA' and en['protocol']==CASE['protocol']and en['prior_public_case']==CASE['frozen_initial_case']
    assert len(en['excluded_boots'])==len(set(en['excluded_boots']))==26 and en['local_native']['held_out_signed_control']=='R' and en['local_native']['treatment']=='F'
    assert en['local_native']['typed_graph']['live_raw_argv_differences']==[0,0,0]and en['local_native']['typed_graph']['previous_separate_path_raw_differences']==6942
    return w,t,en
def scope():
    w,t,en=checked_binding()
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot not in en['excluded_boots'];return w,t,boot
def oracle():
    w,t,_=scope();donor=w/'coordinator/scripts/uv-client-22958';assert filehash(donor/'release-lock.json')==LOCK['locks']['SF']
    sys.path.insert(0,str(donor));import service as svc,release_intake as intake
    # The source, archive, release signatures, producer service contents and two-role
    # inventory checks remain in the original reader. Only this job's coordinator
    # and boot admission belongs to the session that is now doing the import.
    svc.host=scope
    return intake
def acquire():
    w,t,boot=scope();fresh=oracle();proof=w/'trait-results';proof.mkdir()
    write(proof/'unscored-start.json',{'reviewed':os.environ['REVIEWED_HEAD'],'boot':boot,'frozen_case':CASE['protocol'],'expected_release':LOCK['release']['tag']})
    current=fresh.transport().gh_json('api','--method','GET','repos/astral-experiments/ohm/releases/latest');write(proof/'release-observed.json',{k:current[k]for k in('id','tag_name','immutable','published_at','draft','prerelease','target_commitish')});assert current['id']==LOCK['release']['release_id']and current['tag_name']==LOCK['release']['tag'],'signed release changed; independent projection intake is required'
    assert min(shutil.disk_usage(f).free for f in(t,w))>=80<<30
    fresh.admit();incoming=t/'release-22958-incoming';signed,=(incoming/'signed').glob('*.tar.gz');assert filehash(signed)==LOCK['release']['sha256']
    pool=t/'ctfe22-root-sdks';fresh.s.lock['raw']['R']=LOCK['roles']['R']['runtime'];fresh.install_archive(signed,pool/'R','R')
    scan=t/'uv22536-registry';scan.mkdir();uv=w/'uv-source';env={'PATH':str(pool/'R/bin')+':/usr/bin:/bin','HOME':str(t),'CARGO_HOME':str(scan),'RUSTC':str(pool/'R/bin/rustc'),'GIT_TERMINAL_PROMPT':'0','LC_ALL':'C.UTF-8'}
    assert git(uv,'rev-parse','HEAD')==CASE['states']['D']['source'];subprocess.run([pool/'R/bin/cargo','fetch','--locked'],cwd=uv,env=env,check=True)
    root=t/'uv22536-canonical';res=w/'session-results';root.mkdir();res.mkdir();en=read(HERE/'dispatch-enrollment.json')
    cfg={'root':str(root),'results':str(res),'source_donor':str(uv),'sdks':{r:str(pool/r)for r in ('R','S','F')},'cargo_home':str(scan),'control_candidate_source_inputs':CASE['role_authority'],'fresh_private_sdk_pool':str(pool),'require_source_tag':True,'excluded_boots':en['excluded_boots']}
    setup(Env(cfg));write(w/'session-config.json',cfg);write(res/'transport.json',{'source_lock':filehash(HERE/'production-inputs.json.gz'),'original_release':filehash(proof/'intake/latest.json'),'reopened_producer_pair':filehash(proof/'intake.json'),'host_inputs':filehash(res/'actual-inputs.json'),'new_head':os.environ['GITHUB_SHA'],'run_id':os.environ['GITHUB_RUN_ID']})
def latest():
    w,t,_=scope();fresh=oracle();fresh.latest(w/'session-results/fresh-publication.json')
if __name__=='__main__':{'acquire':acquire,'latest':latest}[sys.argv[1]]()
