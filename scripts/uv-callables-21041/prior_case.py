"""Recheck the qualifying private incremental study's original service identity and the current published Ohm release."""
def gate(c,old,proof):
    m=c.m;x=m.read(c.HERE/'first-qualification.json')
    expected=c.PAIR['prior_case']
    c.guard(x==expected and x['all_eight_valid']is True and x['explicit_full_stack_go']is True
            and x['candidate_source']==c.PAIR['arms'][c.ROLES[1]]['source']['commit']
            and x['candidate_sdk']==c.PAIR['arms'][c.ROLES[1]]['artifact'],"different or unqualified predecessor")
    root='repos/astral-experiments/ohm'
    last=old.gh_json('api',root+'/releases/latest')
    c.guard(last['id']==x['release_id'] and last['tag_name']=='ohm-1.99.0-22' and last['draft'] is False and last['prerelease'] is False,
            "latest published stable release changed; stop and reassess")
    m.save(proof/'latest-release.json',{k:last[k]for k in ('id','tag_name','published_at','draft','prerelease')})
    rr=old.gh_json('api',root+'/actions/runs/'+str(x['run']))
    jobs=old.gh_json('api',root+'/actions/runs/'+str(x['run'])+'/attempts/1/jobs?per_page=100')['jobs']
    art=old.gh_json('api',root+'/actions/artifacts/'+str(x['original']['id']))
    c.guard(len(jobs)==1 and rr['id']==jobs[0]['run_id']==art['workflow_run']['id']==x['run']
            and rr['repository']['private'] and rr['repository']['id']==art['workflow_run']['repository_id']==1319437234
            and rr['head_sha']==jobs[0]['head_sha']==art['workflow_run']['head_sha']==x['head']
            and rr['event']=='workflow_dispatch' and rr['head_branch']==x['branch'] and rr['run_attempt']==jobs[0]['run_attempt']==1
            and rr['conclusion']==jobs[0]['conclusion']=='success' and jobs[0]['id']==x['job']
            and art['size_in_bytes']==x['original']['bytes'] and art['digest']=='sha256:'+x['original']['sha256']
            and art['name']=='uv-21041-callables-production-eight-pair-1' and not art['expired'], "different predecessor service/archive")
    m.save(proof/'qualified-predecessor.json',x)
