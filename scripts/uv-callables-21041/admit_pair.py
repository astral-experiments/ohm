"""Restore the two separately produced SDKs using the original release verifier in isolated interpreters."""
import sys,subprocess
import core as c
import production_archive as archive
from production_service import PRODUCERS,REPO,service
m=c.m
def admit():
    w,tmp=c.host();_,prev=m.check_sources(w);old=m.load('signed_release_intake',prev/'intake.py')
    out=w/'trait-results';proof=out/'intake';proof.mkdir();meta=proof/'role-material';meta.mkdir()
    temp=tmp/'production-domain-incoming';temp.mkdir();pool=tmp/'ctfe22-root-sdks';pool.mkdir()
    latest=old.gh_json('api','repos/'+REPO+'/releases/latest')
    c.guard(latest['tag_name']=='ohm-1.99.0-22'and latest['draft']is False and latest['prerelease']is False,'latest release changed')
    m.save(proof/'latest-release.json',{k:latest[k]for k in ('id','tag_name','draft','prerelease','published_at')})
    old.released(temp,proof);signed,=(temp/'signed').glob('*.tar.gz');fixed=archive.official_cargo(signed,temp)
    result={}
    for role,builder in zip(c.ROLES,['control-builder','treatment-builder'],strict=True):
        p=PRODUCERS[role];arm=c.PAIR['arms'][role];here=proof/role;here.mkdir();work=temp/role;work.mkdir();docs=[]
        for n,tail in [('run',''),('jobs','/attempts/1/jobs?per_page=100'),('artifacts','/artifacts?per_page=100')]:
            data=old.gh_json('api',f"repos/{REPO}/actions/runs/{p['run']}"+tail);m.save(here/(n+'.json'),data);docs.append(data)
        current=service(role,*docs);c.guard(current==arm['service']and current['members'][p['sdk']]==arm['artifact'],'production material no longer enrolled')
        for kind in ('sdk','qa'):
            a=current['members'][p[kind]];z=work/(kind+'.zip');old.gh_bytes(f"repos/{REPO}/actions/artifacts/{a['id']}/zip",z,a['bytes'],a['sha256']);archive.unpack(z,work/kind,kind)
        scratch=work/'restored';scratch.mkdir()
        subprocess.run([sys.executable,'-ISBu',c.HERE/'verify_role.py',role,w/builder,work/'sdk',work/'qa',scratch,fixed,meta/role,pool],check=True)
        result[role]=m.read(meta/role/'registered.json')
    left,right=[m.read(meta/r/'source.json')for r in c.ROLES]
    older=m.read(meta/c.ROLES[1]/'previous-derive-source.json')
    for key in ('role','source','source_pack_sha256','component_git','recipe','training_objects','released_coordinator','signed_manifest_sha256','overlay_description_sha256'):
        c.guard(left[key]==older[key],('different actual preceding compiler',key))
    for key in ('component_git','recipe','training_objects','released_coordinator','signed_manifest_sha256'):c.guard(left[key]==right[key],('unmatched production recipe',key))
    a,b=[m.read(meta/r/'role.json')for r in c.ROLES];c.guard(a['execution_pgo']==b['execution_pgo']and a['bolt_note']is b['bolt_note']is True and a['effective_benchmark_cargo_sha256']==b['effective_benchmark_cargo_sha256']==m.filesha(fixed)and a['driver']['sha256']!=b['driver']['sha256']and a['archive_sha256']!=b['archive_sha256'],'production binaries or flags')
    m.save(out/'intake.json',dict(installed=result,sdk_lock_sha256=m.filesha(c.HERE/'pair.json'),signed_cargo_sha256=m.filesha(fixed)))
