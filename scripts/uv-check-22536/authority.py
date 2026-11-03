"""Hosted intake. Reuse the published SDK and signature readers without any workload or score from their original experiment."""
from pathlib import Path
import gzip,json,os,shutil,subprocess,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parent))
from basis import CASE,HERE,LOCK,PLAN,Env,digest,filehash,read,write,setup
import replication
PARENT='ca8b83712b881b45cbb8e8b0513d0811971e4a98';PREVIOUS='b9396475c5c973c931fabd8c95ab9548104dbdc4';BRANCH='charlie/codex-22536-instruction-replica-22'
def git(d,*v):return subprocess.check_output(['git','-C',d,*v],text=True).strip()
def historical_enrollment(co,en,guard):
    add=read(HERE/'same-mode-eligibility.json');p=add['previous_source_enrollment'];path='scripts/uv-check-22536/dispatch-enrollment.json'
    assert git(co,'rev-parse',PARENT+'^^^')==guard['original_parent'] and git(co,'rev-parse',PARENT+'^^')==guard['previous_head']
    assert add['closed_run']['head']==PREVIOUS and guard['true_prior_calibrated_boots']==27 and add['protocol']==CASE['protocol'] and add['score']==filehash(HERE/'score.py')
    assert en['same_mode_eligibility']==filehash(HERE/'same-mode-eligibility.json') and filehash(HERE/p['file'])==p['compressed']
    historic=gzip.decompress((HERE/p['file']).read_bytes());assert digest(historic)==p['sha256']==guard['scientific_enrollment']
    import hashlib
    h=hashlib.sha1(b'blob '+str(len(historic)).encode()+bytes([0])+historic).hexdigest()
    assert git(co,'ls-tree',PREVIOUS,'--',path).split()==['100644','blob',h,path] and h==p['oid']
    prior=json.loads(historic);extra=add['closed_run']['native_calibration']
    assert extra['head']==PREVIOUS and extra['prior']==p['sha256'] and extra['boot']==add['closed_run']['machine']['boot']
    assert en==prior|{'excluded_boots':prior['excluded_boots']+[extra['boot']],'adjacent_originals':prior['adjacent_originals']+[extra],'same_mode_eligibility':filehash(HERE/'same-mode-eligibility.json')}
    assert add['admission']['prospective_sources']=={n:filehash(HERE/n)for n in ('session.py','live_metadata.py','live_review.py','fixed_input.py')}
    # The depth-five blobless checkout authenticates the two grandfathered registrations. The
    # compressed member preserves the historical bytes without a credentialed fetch.
    for rev,oid in [(guard['previous_head'],guard['previous_workflow_blob']),(PREVIOUS,guard['depth3_workflow_blob']),(PARENT,add['workflow_blob'])]:
        assert git(co,'ls-tree',rev,'--','.github/workflows/ci.yml').split()==['100644','blob',oid,'.github/workflows/ci.yml']
    row=git(co,'ls-tree',guard['original_parent'],'--',path).split()
    b=gzip.decompress((HERE/guard['source_bytes_from_content_member']).read_bytes())
    oid=hashlib.sha1(b'blob '+str(len(b)).encode()+bytes([0])+b).hexdigest()
    assert row==['100644','blob',oid,path]and oid==guard['original_enrollment_git_blob']
    assert digest(b)==en['prior_enrollment']==guard['original_enrollment_sha256']
    return json.loads(b)
def assigned_runner(read_jobs,run,head,name,prior,job_name,pause=time.sleep):
    """Await only publication of the correct live service identity, up to 55 seconds."""
    observations=[];seen=None
    for attempt in range(12):
        data=read_jobs();rows=data['jobs']
        assert data['total_count']==len(rows)and len(rows)<=1
        if rows:
            row,=rows;job=row['id'];rid=row['runner_id'];actual=row['runner_name']
            assert row['run_id']==int(run)and row['head_sha']==head and row['name']==job_name and row['run_attempt']==1
            assert type(job)is int and job>0 and job!=prior['previous_job']and seen in (None,job)
            assert row['status']in ('queued','in_progress')and rid!=prior['previous_runner_id']and actual!=prior['previous_runner_name']
            if 'additional_host' in prior:
                old=prior['additional_host'];assert job!=old['job'] and rid!=old['machine']['runner'] and actual!=old['machine']['name']
            assert job!=replication.FIRST['job'] and rid!=replication.FIRST['runner_id'] and actual!=replication.FIRST['runner_name']
            seen=job;observations.append({'job':job,'status':row['status'],'runner_id':rid,'runner_name':actual})
            if type(rid)is int and rid>0:
                assert actual==name and name
                return {k:row[k]for k in ('run_id','id','head_sha','runner_id','runner_name','name')},observations
            assert (rid is None or(type(rid)is int and rid==0))and actual in ('',None)
        else:observations.append({'unindexed':True})
        if attempt<11:pause(5)
    raise RuntimeError('Actions did not publish the required nonzero runner identity within 55 seconds')
def checked_binding():
    e=os.environ;assert e['GITHUB_REPOSITORY']=='astral-experiments/ohm'and e['GITHUB_REPOSITORY_ID']=='1319437234'and e['GITHUB_EVENT_NAME']=='workflow_dispatch'and e['GITHUB_REF']=='refs/heads/'+BRANCH and e['GITHUB_WORKFLOW_REF']==e['GITHUB_REPOSITORY']+'/.github/workflows/ci.yml@'+e['GITHUB_REF']and e['GITHUB_RUN_ATTEMPT']=='1'
    w=Path(e['GITHUB_WORKSPACE']).resolve();t=Path(e['RUNNER_TEMP']).resolve();co=w/'coordinator'
    assert git(co,'rev-parse','HEAD')==e['GITHUB_SHA']==e['REVIEWED_HEAD']and git(co,'rev-parse','HEAD^')==PARENT
    assert not git(co,'status','--porcelain','--untracked-files=no')and not git(co,'diff','--name-only','--no-renames',PARENT,'HEAD','--','scripts/uv-client-22958','scripts/uv-callables-21041','scripts/handwritten-panel')
    assert HERE==co/'scripts/uv-check-22536';en=read(HERE/'dispatch-enrollment.json')
    assert filehash(HERE/'dispatch-enrollment.json')==replication.FIRST['original_source_enrollment_sha256']
    assert git(co,'rev-parse',PARENT+'^')==PREVIOUS and replication.FIRST['head']==PARENT
    assert en.get('local_native_gates_accepted')is True and en['submit_authority']=='explicit workflow_dispatch of the operator-reviewed exact SHA' and en['protocol']==CASE['protocol']and en['prior_public_case']==CASE['frozen_initial_case']
    assert len(en['excluded_boots'])==len(set(en['excluded_boots']))==28 and en['local_native']['held_out_signed_control']=='R' and en['local_native']['treatment']=='F'
    assert en['local_native']['typed_graph']['live_raw_argv_differences']==[0,0,0]and en['local_native']['typed_graph']['previous_separate_path_raw_differences']==6942
    guard=read(HERE/'partial-checkout-authority.json');prior=historical_enrollment(co,en,guard);add=read(HERE/'eligibility-addendum.json')
    assert en['eligibility_addendum']==filehash(HERE/'eligibility-addendum.json')and en['excluded_boots'][:-1]==prior['excluded_boots']+[add['prospective_panel']['new_boot_exclusion']['boot']]and add['previous']['head']==guard['original_parent']
    recent=read(HERE/'same-mode-eligibility.json')['closed_run']
    assert e['GITHUB_RUN_ID'] not in (str(guard['previous_run']),str(recent['id']),str(replication.FIRST['run'])) and e['RUNNER_NAME'] not in (guard['previous_runner_name'],recent['machine']['name'],replication.FIRST['runner_name'])
    assert en['local_native']['true_role_source']=={n:LOCK['roles'][n]['source']for n in ('R','F')}and en['local_native']['runtime_inventory_sha256']=={n:LOCK['roles'][n]['hash']for n in ('R','F')}
    assert not git(co,'diff','--name-only','--no-renames',PARENT,'HEAD','--',*['scripts/uv-check-22536/'+n for n in ('protocol.json','score.py','instruments.json','case.json','production-inputs.json.gz','metadata-kit.json','producer_map.py','fixed-layout-rule.json','opening.py','science.py','semantics.py','compatibility.py','fixed_products.py')])
    return w,t,en|{'excluded_boots':replication.excluded(en['excluded_boots'])}
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
    enhost=read(HERE/'partial-checkout-authority.json')|{'additional_host':read(HERE/'same-mode-eligibility.json')['closed_run']};transport=fresh.transport()
    endpoint='repos/astral-experiments/ohm/actions/runs/'+os.environ['GITHUB_RUN_ID']+'/attempts/1/jobs?per_page=10'
    host,observations=assigned_runner(lambda:transport.gh_json('api','--method','GET','-H','Cache-Control: no-cache',endpoint),os.environ['GITHUB_RUN_ID'],os.environ['GITHUB_SHA'],os.environ['RUNNER_NAME'],enhost,'eight-real-session-pairs')
    write(proof/'previous-unmeasured-runner-exclusion.json',{'observed':host,'observations':observations,'closed_pre_intake_original':enhost,'fresh_calibrated_boot_checked_separately':True})
    current=fresh.transport().gh_json('api','--method','GET','repos/astral-experiments/ohm/releases/latest');write(proof/'release-observed.json',{k:current[k]for k in('id','tag_name','immutable','published_at','draft','prerelease','target_commitish')});assert current['id']==LOCK['release']['release_id']and current['tag_name']==LOCK['release']['tag'],'signed release changed; independent projection intake is required'
    assert min(shutil.disk_usage(f).free for f in(t,w))>=80<<30
    fresh.admit();incoming=t/'release-22958-incoming';signed,=(incoming/'signed').glob('*.tar.gz');assert filehash(signed)==LOCK['release']['sha256']
    pool=t/'ctfe22-root-sdks';fresh.s.lock['raw']['R']=LOCK['roles']['R']['runtime'];fresh.install_archive(signed,pool/'R','R')
    scan=t/'uv22536-registry';scan.mkdir();uv=w/'uv-source';env={'PATH':str(pool/'R/bin')+':/usr/bin:/bin','HOME':str(t),'CARGO_HOME':str(scan),'RUSTC':str(pool/'R/bin/rustc'),'GIT_TERMINAL_PROMPT':'0','LC_ALL':'C.UTF-8'}
    assert git(uv,'rev-parse','HEAD')==CASE['states']['D']['source'];subprocess.run([pool/'R/bin/cargo','fetch','--locked'],cwd=uv,env=env,check=True)
    root=t/'uv22536-canonical';res=w/'session-results';root.mkdir();res.mkdir();en=checked_binding()[2]
    write(res/'replication-host.json',{'registration':replication.REGISTRATION_SHA,'boot':boot,'job':host,'previous':replication.FIRST})
    cfg={'root':str(root),'results':str(res),'source_donor':str(uv),'sdks':{r:str(pool/r)for r in ('R','S','F')},'cargo_home':str(scan),'control_candidate_source_inputs':CASE['role_authority'],'fresh_private_sdk_pool':str(pool),'require_source_tag':True,'excluded_boots':en['excluded_boots']}
    setup(Env(cfg));write(w/'session-config.json',cfg);write(res/'transport.json',{'source_lock':filehash(HERE/'production-inputs.json.gz'),'original_release':filehash(proof/'intake/latest.json'),'reopened_producer_pair':filehash(proof/'intake.json'),'host_inputs':filehash(res/'actual-inputs.json'),'new_head':os.environ['GITHUB_SHA'],'run_id':os.environ['GITHUB_RUN_ID']})
def latest(after=False):
    w,_,_=scope();root=w/'session-results';fresh=oracle()
    assert read(root/'qualification/accepted.json')['control']=='R'
    data=fresh.transport().gh_json('api','--method','GET','-H','Cache-Control: no-cache','repos/astral-experiments/ohm/releases/latest')
    path=root/('fresh-publication-after.json' if after else 'fresh-publication.json')
    write(path,data)
    replication.release(data,LOCK['release'])
if __name__=='__main__':{'acquire':acquire,'latest':latest,'latest-after':lambda:latest(after=True)}[sys.argv[1]]()
