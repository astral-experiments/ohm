"""Verify stock and full-stack outputs with each producer's originally qualified reader."""
from pathlib import Path
import shutil,subprocess,sys
import core as c
import production_archive as archive
m=c.m;REPO='astral-experiments/ohm'
def admit():
    w,tmp=c.host();_,previous=m.check_sources(w);old=m.load('released_intake_transport',previous/'intake.py')
    out=w/'trait-results';proof=out/'intake';proof.mkdir();meta=proof/'role-material';meta.mkdir();temp=tmp/'production-cumulative-incoming';temp.mkdir();pool=tmp/'ctfe22-root-sdks';pool.mkdir()
    latest=old.gh_json('api','repos/'+REPO+'/releases/latest');c.guard(latest['tag_name']=='ohm-1.99.0-22'and latest['draft']is False and latest['prerelease']is False,'signed baseline changed')
    m.save(proof/'latest-release.json',{k:latest[k]for k in ('id','tag_name','draft','prerelease','published_at')});old.released(temp,proof);signed,=(temp/'signed').glob('*.tar.gz');fixed=archive.official_cargo(signed,temp)
    roles=c.ROLES;materials=m.read(c.HERE/'derive/cumulative-material.json');result={}
    for idx,(role,owner,producer)in enumerate(zip(roles,['stock-authority','derive-authority'],['control-builder','treatment-builder'],strict=True)):
        arm=c.PAIR['arms'][role];h=proof/role;h.mkdir();work=temp/role;work.mkdir();coordinator=w/owner;reader=coordinator/'scripts/uv-callables-21041';rs=arm['service']['run']
        for key,suffix in [('run',''),('jobs','/attempts/1/jobs?per_page=100'),('artifacts','/artifacts?per_page=100')]:
            m.save(h/(key+'.json'),old.gh_json('api',f'repos/{REPO}/actions/runs/{rs}'+suffix))
        subprocess.run([sys.executable,'-ISBu',c.HERE/'derive/production_authority.py',role,coordinator,h,h/'service.json'],check=True)
        enrolled=m.read(h/'service.json');current=enrolled['service'];names=enrolled['artifact_names'];c.guard(current==arm['service']and current==materials['services'][role]and current['members'][names['sdk']]==arm['artifact'],'unregistered producer')
        for kind,name in names.items():
            a=current['members'][name];z=work/(kind+'.zip');old.gh_bytes(f"repos/{REPO}/actions/artifacts/{a['id']}/zip",z,a['bytes'],a['sha256']);archive.unpack(z,work/kind,kind)
        scratch=work/'restored';scratch.mkdir();dest=meta/role
        subprocess.run([sys.executable,'-ISBu',reader/'verify_role.py',role,w/producer,work/'sdk',work/'qa',scratch,fixed,dest,pool],check=True)
        actual=m.read(dest/'registered.json');c.guard(actual['server']==arm['artifact']and actual['source']==arm['source']and actual['runtime']['bin/cargo']==m.filesha(fixed),'installed source/SDK mismatch');result[role]=actual
        if idx==0:
            for source,dst in [('passed.json','pair-passed.json'),('cache-transition/passed.json','cache-transition.json')]:shutil.copyfile(work/'prior_pair'/source,proof/dst)
            seals=m.read(reader/'original-control.json')
            c.guard(all(m.filesha(proof/path)==digest for path,digest in seals['files'].items()),'different authentic original stock distribution')
            pair=m.read(proof/'pair-passed.json');transition=m.read(proof/'cache-transition.json')
            c.guard(pair['roles'][role]=={k:m.read(dest/(k+'.json'))for k in ('source','role')}and pair['cross_sdk_cache_rejection_sha256']==m.filesha(proof/'cache-transition.json')and transition['native_processes']==16 and pair['required_benchmark_cargo_sha256']==m.filesha(fixed)and all(pair['artifacts'][role][k]=={key:current['members'][names[k]][key]for key in ('id','sha256')}for k in ('sdk','qa')),'stock producer pair qualification')
    left,right=[m.read(meta/r/'source.json')for r in roles];a,b=[m.read(meta/r/'role.json')for r in roles]
    c.guard(all(left[k]==right[k]for k in ('component_git','recipe','training_objects','released_coordinator','signed_manifest_sha256'))and a['execution_pgo']==b['execution_pgo']and a['bolt_note']is b['bolt_note']is True and a['effective_benchmark_cargo_sha256']==b['effective_benchmark_cargo_sha256']==m.filesha(fixed)and a['driver']['sha256']!=b['driver']['sha256']and a['archive_sha256']!=b['archive_sha256'],'unmatched production recipe or native artifacts')
    m.save(out/'intake.json',dict(installed=result,sdk_lock_sha256=m.filesha(c.HERE/'pair.json'),signed_cargo_sha256=m.filesha(fixed)))
