"""Require the correct, separate private producer's physical job and both original artifacts."""
import re
REPO = "astral-experiments/ohm"
ROLES = ("callables_ctfe318", "callables_ctfe318_incoherent_domain")
PRODUCERS = {ROLES[0]:dict(run=41398925829,head="4e34ea9c7232977f95498d7bf48d382157e8558b",branch="charlie/codex-21041-callable-production22",job="Production GNU callable SDK",id=125126258067,sdk="callable-production-sdk",qa="callable-production-qa-attempt-1"),ROLES[1]:dict(run=41414598941,head="5f7e5680285caa6b9a848db810b63ef58dfe0143",branch="charlie/codex-21041-domain-production22",job="Production GNU incoherent-impl domain SDK",id=125175283448,sdk="domain-production-sdk",qa="domain-production-qa-attempt-1")}
COMMON = {"Admit this production workspace and allocate its physical emergency reserve","Reconstruct and verify the exact compiler source","Install native GNU bootstrap prerequisites","Install pinned LLVM BOLT tools","Prepare pinned Wild linker","Build the production PGO and BOLT distribution","Verify the production SDK and exercise the original regression","Validate this role's complete capacity evidence before its SDK upload","Upload the native-qualified SDK","Retain role identity, release build and native diagnostics"}
def need(ok,why):
    if not ok:raise ValueError(why)
def service(role,run,jobs,artifacts):
    p=PRODUCERS[role]
    need(run['id']==p['run'] and run['event']=='workflow_dispatch' and run['repository']['id']==run['head_repository']['id']==1319437234 and run['repository']['private'] is True and run['repository']['full_name']==REPO and run['head_sha']==p['head'] and run['head_branch']==p['branch'] and run['run_attempt']==1 and run['status']=='completed' and run['conclusion']=='success','different producer run or repository')
    need(len(jobs['jobs'])==jobs['total_count']==1,'extra or missing native producer');job,=jobs['jobs']
    need(job['id']==p['id'] and job['name']==p['job'] and job['run_id']==p['run'] and job['head_sha']==p['head'] and job['run_attempt']==1 and job['runner_id']>0 and job['labels']==['namespace-profile-ubuntu-24-04-16'] and job['status']=='completed' and job['conclusion']=='success','invalid native producer')
    ok={s['name']for s in job['steps']if s['status']=='completed'and s['conclusion']=='success'}
    extra={'Validate the independently qualified stage1 hardware prerequisite'}if role==ROLES[1]else set()
    need(COMMON|extra<=ok,'missing release/native/capacity or prerequisite step')
    arts=artifacts['artifacts'];need(len(arts)==artifacts['total_count']==2 and {a['name']for a in arts}=={p['sdk'],p['qa']}and len({a['id']for a in arts})==2,'wrong service upload roster')
    compact={}
    for a in arts:
        w=a['workflow_run'];need(w['id']==p['run']and w['head_sha']==p['head']and w['head_branch']==p['branch']and w['repository_id']==w['head_repository_id']==1319437234 and a['expired']is False and re.fullmatch('sha256:[a-f0-9]{64}',a['digest']),'wrong artifact origin')
        compact[a['name']]={'id':a['id'],'bytes':a['size_in_bytes'],'sha256':a['digest'][7:]}
    need((190<<20)<compact[p['sdk']]['bytes']<(700<<20)and 0<compact[p['qa']]['bytes']<(64<<20),'unexpected SDK or QA size')
    return {'run':p['run'],'head':p['head'],'branch':p['branch'],'job':p['id'],'runner':job['runner_id'],'runner_name':job['runner_name'],'jobs':{p['job']:p['id']},'members':compact}
