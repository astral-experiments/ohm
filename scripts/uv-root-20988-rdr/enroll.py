"""Authenticate the actual one-role source build and the official signed -22 Cargo and helpers."""
from pathlib import Path
from zipfile import ZipFile
import os, shutil, subprocess, sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import common as c
m=c.m;p=c.P

def admit():
    w,tmp,out=c.only_scope();proof=out/'intake';proof.mkdir();c.capacity(proof,'intake',p['capacity_before_gib'])
    old=m.load('old_signed',c.REPO/'scripts/uv-resolver-whole-pmu/intake.py')
    e=m.load('panel_sdk',c.PANEL/'enroll.py')
    lk=p['producer'];rid=lk['rid'];role,=lk['roles'];art=lk['roles'][role];job_name,=lk['jobs'];head=lk['head'];branch=lk['branch'];repo=p['repo']
    for label,tail in (('run',''),('jobs','/jobs?per_page=100'),('artifacts','/artifacts?per_page=100')):
        m.save(proof/(label+'.json'),old.gh_json('api','--method','GET',f'repos/{repo}/actions/runs/{rid}'+tail))
    r,j,a=[m.read(proof/(q+'.json'))for q in ('run','jobs','artifacts')]
    m.guard((r['repository']['full_name'],r['head_repository']['full_name'],r['repository']['private'],r['id'],r['head_sha'],r['head_branch'],r['event'],r['run_attempt'],r['status'],r['conclusion'],r['path'])==(repo,repo,True,rid,head,branch,'workflow_dispatch',1,'completed','success','.github/workflows/ci.yml'),'producer run')
    m.guard(j['total_count']==len(j['jobs'])==a['total_count']==len(a['artifacts'])==1,'one-role producer')
    j=j['jobs'][0];a=a['artifacts'][0]
    m.guard((j['id'],j['name'],j['run_id'],j['head_sha'],j['run_attempt'],j['status'],j['conclusion'])==(lk['jobs'][job_name],job_name,rid,head,1,'completed','success'),'native QA job')
    m.guard((a['name'],a['id'],a['size_in_bytes'],a['digest'],a['expired'],a['workflow_run']['id'],a['workflow_run']['head_sha'],a['workflow_run']['head_branch'])==('rdr-observer-stage1-'+role,art['id'],art['bytes'],'sha256:'+art['sha256'],False,rid,head,branch),'service SDK role')
    b=w/'producer';sd=b/'scripts/rdr-observer-stage1';m.guard(m.sha_git(b,'rev-parse','HEAD').decode().strip()==head and not m.sha_git(b,'status','--porcelain','--untracked-files=no'),'producer checkout')
    sys.path.insert(0,str(sd));stage=m.load('observer_builder',sd/'stage.py');carrier=stage.file_map()
    scratch=tmp/'root-rdr-intake';scratch.mkdir();archive=scratch/'stage1.zip'
    old.gh_bytes(f"repos/{repo}/actions/artifacts/{art['id']}/zip",archive,art['bytes'],art['sha256'])
    origin=scratch/'capsule';origin.mkdir()
    with ZipFile(archive)as z:
        rows=z.infolist();m.guard(len(rows)==len(p['capsule']) and {i.filename for i in rows}==p['capsule'].keys(),'complete capsule roster')
        for i in rows:
            f=origin/i.filename;size,h=p['capsule'][i.filename]
            m.guard(e.safe_name(i.filename) and not i.is_dir() and (i.external_attr>>16)&0o170000 in (0,0o100000) and not i.flag_bits&1 and i.file_size==size,'unsafe capsule member')
            with z.open(i)as inp,f.open('xb')as output:shutil.copyfileobj(inp,output,1<<20)
            m.guard(m.filesha(f)==h,'qualified native QA or SDK changed: '+i.filename)
            if i.filename!='sdk.tar.zst':shutil.copy2(f,proof/i.filename)
    ref='refs/heads/'+branch
    ctx={'GITHUB_REPOSITORY':repo,'GITHUB_SHA':head,'GITHUB_REF':ref,'GITHUB_WORKFLOW_REF':repo+'/.github/workflows/ci.yml@'+ref,'GITHUB_RUN_ID':str(rid),'GITHUB_RUN_ATTEMPT':'1'}
    ident=e.check_archive(role,origin,stage,ctx,carrier);stage.passed((origin/'allocator.log').read_bytes(),'allocator',role)
    arm=m.read(origin/'role.json')['source'];sm=m.read(origin/'observer-smoke.json')
    m.guard({k:arm[k]for k in p['source']}==p['source'] and sm['visits']==['native','observer','native'] and sm['trace_sha256']==m.filesha(origin/'observer-fixture.rdr'),'observer source or native parity')
    sdk=tmp/'enrolled-rdr-sdk';built=e.extract(origin,sdk)
    old.released(scratch,proof);tar,=(scratch/'signed').glob('*.tar.gz');fixed=e.signed(scratch/'signed-helpers',tar)
    for n,source in fixed.items():
        dest=sdk/n;dest.parent.mkdir(parents=True,exist_ok=True);m.guard(not dest.is_symlink(),'tool link');shutil.copy2(source,dest)
    inv=c.inventory(sdk);runtime=c.runtime_receipt(sdk,ident)
    src=scratch/'smoke.rs';src.write_text('fn main() { assert_eq!(2 + 2, 4); }\n');env={'PATH':'/usr/bin:/bin','HOME':str(scratch),'LC_ALL':'C.UTF-8'}
    subprocess.run([sdk/'bin/rustc',src,'-o',scratch/'smoke'],check=True,env=env);subprocess.run([scratch/'smoke'],check=True,env=env)
    m.save(out/'intake.json',{'source':p['source'],'producer':lk,'effective_inventory_sha256':inv,'sdk':str(sdk),'runtime':runtime,'native_compile_link_run':True,'score':False})
    shutil.rmtree(scratch)
if __name__=='__main__':admit()
