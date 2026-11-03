"""Open the two source-bound SDK originals, then install a single role at the same local path."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess as sp
import tarfile
import zipfile

HERE=Path(__file__).resolve().parent
REGISTER=json.loads((HERE/'registration.json').read_bytes())
KIT=json.loads((HERE/'transports.json').read_bytes()) if (HERE/'transports.json').exists() else {}
def require(ok,message):
    if not ok:raise ValueError(message)
def sha(p):
    with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def jsonfile(p,obj):p.write_text(json.dumps(obj,sort_keys=True,indent=2)+'\n')
def api(path):return json.loads(sp.check_output(['gh','api','repos/astral-experiments/ohm/'+path]))
def fetch(role,cache,dest):
    spec=KIT[role];cache.mkdir(parents=True,exist_ok=True);dest.mkdir(parents=True)
    job=api('actions/runs/'+str(spec['run']));require(job['head_sha']==spec['qa'] and job['run_attempt']==1 and job['status']=='completed','unadmitted source factory')
    task=api('actions/jobs/'+str(spec['job']))
    require(task['run_id']==spec['run'] and task['conclusion']=='success','wrong or incomplete role-specific factory job')
    proof={}
    for label in ('qualification','sdk'):
        sid,expected=spec[label];m=api('actions/artifacts/'+str(sid))
        require(m['workflow_run']['id']==spec['run'] and not m['expired'] and m['digest']=='sha256:'+expected and m['size_in_bytes']<650*2**20,'unbound Actions original')
        p=cache/(expected+'.zip')
        if not p.exists():
            with p.open('xb') as f:sp.run(['gh','api','repos/astral-experiments/ohm/actions/artifacts/'+str(sid)+'/zip'],stdout=f,check=True)
        require(p.stat().st_size==m['size_in_bytes'] and sha(p)==expected,'downloaded Actions parcel')
        with zipfile.ZipFile(p) as z:
            require(len(set(z.namelist()))==len(z.namelist()) and all(not n.startswith('/') and '..'not in Path(n).parts for n in z.namelist()),'zip members')
            if label=='qualification':
                for n in ('source.json','bootstrap.json','reported-versions.json','sdk.json','sdk-sha256','probes/verdict.json'):
                    require(z.getinfo(n).file_size<1024*1024,'oversized proof');(dest/n).parent.mkdir(parents=True,exist_ok=True);(dest/n).write_bytes(z.read(n))
                proof=json.loads((dest/'sdk.json').read_bytes());source=json.loads((dest/'source.json').read_bytes());versions=json.loads((dest/'reported-versions.json').read_bytes())
                name={'P':'parent','C':'candidate'}[role]
                require(source['source']==REGISTER[name] and source['tree']==REGISTER[name+'_tree'] and source['factory']==spec['qa'] and str(source['run'])==str(spec['run']),'wrong physical source role')
                require(proof['role']==name and proof['driver']==spec['driver'] and proof['versions']==versions and REGISTER[name] in versions['rustc'] and REGISTER['cargo'] in versions['cargo'],'wrong source binary')
                require((dest/'sdk-sha256').read_text().strip()==spec['tar'],'wrong declared SDK digest')
                require(sha(dest/'bootstrap.json')=='3129eb48157c6b610c65b818ac9f86269ab1257020cf12d29701a36111460993','actual bootstrap argv differ from source-matched parent')
            else:
                require(z.namelist()==['sdk.tar.zst'],'wrong SDK archive shape')
                tar=cache/(spec['tar']+'.tar.zst')
                if not tar.exists():
                    require(z.getinfo('sdk.tar.zst').file_size<650*2**20,'large SDK payload')
                    with z.open('sdk.tar.zst')as a,tar.open('xb')as b:shutil.copyfileobj(a,b)
                require(sha(tar)==spec['tar'],'wrong actual SDK build')
    return tar,proof
def install(tar,proof,sdk,alias):
    sdk.mkdir(parents=True);total=0;seen=set()
    p=sp.Popen(['zstd','-qdc',tar],stdout=sp.PIPE)
    with p.stdout,tarfile.open(fileobj=p.stdout,mode='r|')as stream:
        for m in stream:
            name=Path(m.name);require(not name.is_absolute() and '..'not in name.parts and name.parts[0]in('bin','lib') and m.name not in seen,'SDK escaping or duplicate member');seen.add(m.name)
            to=sdk/name
            if m.isdir():to.mkdir(parents=True,exist_ok=True);continue
            require(m.isfile() and 0<=m.size<650*2**20,'SDK special or oversized member')
            total+=m.size;require(total<3*2**30,'oversized uncompressed SDK');to.parent.mkdir(parents=True,exist_ok=True)
            with stream.extractfile(m)as a,to.open('xb')as b:shutil.copyfileobj(a,b)
            to.chmod(m.mode&0o777)
    require(p.wait()==0,'truncated zstd');driver,=(sdk/'lib').glob('librustc_driver-*.so')
    require(sha(driver)==proof['driver'] and sha(sdk/'bin/rustc')==proof['rustc'] and sha(sdk/'bin/cargo')==proof['release_cargo'],'materialized source-built SDK')
    for n,m in REGISTER['release_members'].items():require(sha(sdk/n)==m['sha256'],'changed common release Cargo/linker')
    alias.parent.mkdir(parents=True,exist_ok=True);alias.symlink_to(sdk,target_is_directory=True)
