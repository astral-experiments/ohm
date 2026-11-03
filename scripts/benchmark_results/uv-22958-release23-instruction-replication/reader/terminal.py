"""Four unchanged offline functions from the independently checked terminal receiver."""
from pathlib import Path
import re
import native as prior
import paired

FIRST = "marginal"

def records(run, artifacts, contrast, head, branch):
    assert artifacts["total_count"]==len(artifacts["artifacts"])
    result={}
    for row in artifacts["artifacts"]:
        assert row["name"] not in result and not row["expired"] and row["size_in_bytes"]>0
        assert re.fullmatch("sha256:[0-9a-f]{64}",row["digest"]) and row["id"]>0
        origin=row["workflow_run"]
        assert origin["id"]==run and origin["head_sha"]==head and origin["head_branch"]==branch
        assert origin["repository_id"]==origin["head_repository_id"]==1319437234
        result[row["name"]]=row
    prefix="uv-22958-release23-"+contrast+"-"
    assert set(result)<={prefix+"runner-boot",prefix+"wall-eight-pairs"}
    return {key:result[prefix+suff] for key,suff in (("boot","runner-boot"),("original","wall-eight-pairs")) if prefix+suff in result}

def opened(ctx, values, rid, contrast):
    run,jobs,artifacts,commit=values
    head=ctx["head"];scope=ctx["scope"];host=ctx["host"]
    assignment=host.service_assignment(run,jobs,rid,head,host.BRANCH)
    assert commit["sha"]==head and commit["tree"]["sha"]==ctx["tree"] and [p["sha"] for p in commit["parents"]]==[scope.PARENT]
    return assignment,records(rid,artifacts,contrast,head,host.BRANCH)

def unlock_boot(ctx, values, rid, contrast, out, previous=None):
    host=ctx["host"]; lock=ctx["lock"]; head=ctx["head"]; ls=ctx["lock_sha"]; registration=ctx["scope"].REGISTRATION
    assignment,items=opened(ctx,values,rid,contrast)
    item=items["boot"]
    req=dict(run=rid,job=assignment["job"],artifact=item["id"],sha256=item["digest"][7:])
    boot,member_sha=host.original_member(out/"boot.zip",item,req,head,host.BRANCH,item["name"])
    assert all(boot[k]==v for k,v in assignment.items()) and boot["release_lock"]==ls
    host.verify_placement(boot,contrast,lock,ls,registration)
    assert sorted(set(boot["affinity"]))==boot["affinity"] and len(boot["affinity"])==8
    assert Path(boot["workspace"]).is_absolute() and ".." not in Path(boot["workspace"]).parts
    for name in ("inherited","threads","blocking","placement_sha256"):assert re.fullmatch("[0-9a-f]{64}",boot[name])
    if contrast==FIRST:
        assert previous is None and boot["prior_marginal"] is None
    else:
        assert previous is not None and previous["form"]["contrast"]==FIRST
        want=host.from_prior(previous["boot"],previous["assignment"],previous["item"],previous["request"],
                             previous["member_sha"],lock,ls,registration,dict(assignment,boot=boot["boot"]))
        assert want==boot["prior_marginal"]
    compact=dict(run=rid,head=head,job=assignment["job"],runner_id=assignment["runner_id"],runner_name=assignment["runner_name"],
                 contrast=contrast,control=boot["control"],treatment="F",registered=registration,release_lock=ls,
                 boot=boot["boot"],artifact=item["id"],artifact_bytes=item["size_in_bytes"],artifact_sha256=req["sha256"],
                 member_sha256=member_sha,prior_marginal=boot["prior_marginal"],
                 excluded=boot["excluded"],calibrations={k:boot[k] for k in ("inherited","threads","blocking")},
                 placement_sha256=boot["placement_sha256"],selector=f"{rid}:{assignment['job']}:{item['id']}:{req['sha256']}")
    return dict(form=compact,boot=boot,member_sha=member_sha,item=item,request=req,assignment=assignment,source=out)

def check_complete(ctx,z,live,contrast,previous,assignment):
    host=ctx["host"]; lock=ctx["lock"]; lock_sha=ctx["lock_sha"]; scope=ctx["scope"]
    boot=live["boot"]; control=host.CONTRASTS[contrast]["control"]
    data=paired.member(z,"placement.json")
    assert paired.digest(z.read("placement.json"))==boot["placement_sha256"]
    assert all(boot[k]==v for k,v in data.items())
    assert set(boot)==set(data)|{"workspace","placement_sha256","inherited","threads","blocking","affinity"}
    host.verify_placement(data,contrast,lock,lock_sha,scope.REGISTRATION)
    current=host.service_assignment(paired.member(z,"placement/current-run.json"),paired.member(z,"placement/current-jobs.json"),
                                    boot["run"],ctx["head"],host.BRANCH,assignment["runner_name"])
    assert current==assignment
    rawprior={"placement/prior-run.json","placement/prior-jobs.json","placement/prior-artifact.json","placement/prior-boot.zip"}
    if contrast==FIRST:assert not rawprior.intersection(z.namelist())
    else:
        assert rawprior.issubset(z.namelist()) and previous
        recorded=host.service_assignment(paired.member(z,"placement/prior-run.json"),paired.member(z,"placement/prior-jobs.json"),
                                         previous["form"]["run"],ctx["head"],host.BRANCH)
        assert recorded==previous["assignment"]
        archived=paired.member(z,"placement/prior-artifact.json")
        for k in ("id","name","size_in_bytes","digest","workflow_run"):assert archived[k]==previous["item"][k]
        assert z.read("placement/prior-boot.zip")== (previous["source"]/"boot.zip").read_bytes()
    # Existing native receiver verifies both closures, migration files, four zero-launch
    # no-edit observations, actual release twice, all runtime members and all three clocks.
    scoped_lock=dict(lock,sources={k:lock["sources"][k] for k in (control,"F")})
    label=ctx["rule"]["role_names"][control]
    prior.check_native(z,boot,scoped_lock,control,{"physical_role_choice":label},lock_sha)
    raw=paired.member(z,"native-22958/score.json")
    assert raw["contrast"]==contrast and raw["control"]==control and raw["treatment"]=="F"
    assert raw["sources"]==scoped_lock["sources"] and raw["control_kind"]==label
    assert raw["scope"]==("F and S both include #318. This comparison isolates #327, #328 and #336." if contrast==FIRST
                           else "F adds #318, #327, #328 and #336 to published stock R on the independently admitted uv edit.")
    return paired.digest(z.read("native-22958/score.json"))
