"""Scope a single off-clock observation on the existing canonical root/material."""
import json, os, re, shutil, subprocess, sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
P=json.loads((HERE/'protocol.json').read_bytes())
REPO=HERE.parents[1]
PANEL=REPO/'scripts/handwritten-panel'
sys.path.insert(0,str(PANEL))
import material as m

def only_scope():
    name=P['repo'];branch='refs/heads/'+P['branch'];env=os.environ
    m.guard(__debug__ and sys.version_info[:2]==(3,12) and env['GITHUB_REPOSITORY']==name and env['GITHUB_EVENT_NAME']=='workflow_dispatch' and
            env['GITHUB_RUN_ATTEMPT']=='1' and env['GITHUB_REF']==branch and re.fullmatch('[0-9a-f]{40}',env['REVIEWED_HEAD']) and
            env['GITHUB_SHA']==env['REVIEWED_HEAD'] and env['GITHUB_WORKFLOW_REF']==name+'/.github/workflows/ci.yml@'+branch,'unexpected workflow scope')
    ws=Path(env['GITHUB_WORKSPACE']).resolve(strict=True);tmp=Path(env['RUNNER_TEMP']).resolve(strict=True)
    m.guard(REPO==ws/'coordinator' and m.sha_git(REPO,'rev-parse','HEAD').decode().strip()==env['GITHUB_SHA'],'coordinator identity')
    parent=[x[7:].decode()for x in m.sha_git(REPO,'cat-file','commit','HEAD').split(b'\n\n',1)[0].splitlines() if x.startswith(b'parent ')]
    m.guard(parent==[P['parent']],'wrong direct coordinator parent')
    for n,k in P['frozen_trees'].items():
        m.guard(m.sha_git(REPO,'rev-parse','HEAD:'+n).decode().strip()==k,'changed registered reader '+n)
    diff=set(m.sha_git(REPO,'diff','--name-only',P['parent'],'HEAD').decode().splitlines())
    m.guard('.github/workflows/ci.yml'in diff and all(x=='.github/workflows/ci.yml'or x.startswith('scripts/uv-root-20988-rdr/')for x in diff),'outside diagnostic scope')
    m.guard(not m.sha_git(REPO,'status','--porcelain','--untracked-files=no'),'modified coordinator')
    return ws,tmp,ws/'trait-results'

def capacity(part,phase,floor):
    d={str(p):{'device':p.stat().st_dev,'free':shutil.disk_usage(p).free}for p in (Path('/tmp'),Path(os.environ['GITHUB_WORKSPACE']),Path(os.environ['RUNNER_TEMP']))}
    m.save(part/('capacity-'+phase+'.json'),d)
    m.guard(all(x['free']>floor*(1<<30)for x in d.values()),'bounded hosted disk floor '+phase)

def references():
    ls=m.reference()['argv'];ts={}
    for argv in ls:
        name=argv[argv.index('--crate-name')+1]
        if name in P['targets'] and argv[argv.index('--crate-type')+1]=='lib':
            m.guard(name not in ts and f'crates/{name.replace("_","-")}/src/lib.rs' in argv,'registered library source '+name)
            ts[name]=argv
    m.guard(len(ls)==18 and sorted(ts)==sorted(P['targets']),'wrong enrolled root scope')
    return ls,ts

def runtime_receipt(sdk,ident):
    env={'PATH':'/usr/bin:/bin','HOME':str(sdk.parent),'LC_ALL':'C.UTF-8'}
    get=lambda *a:subprocess.check_output(a,env=env,text=True)
    rustc=sdk/'bin/rustc';version=get(rustc,'-vV');cargo=get(sdk/'bin/cargo','-Vv');ld=get('ldd',rustc)
    m.guard(version==ident['rustc_vV'] and P['source']['commit'] in version and Path(get(rustc,'--print','sysroot').strip()).resolve()==sdk and
        'commit-hash: '+m.P['signed_cargo_commit']+'\n' in cargo and 'not found'not in ld and m.filesha(sdk/'bin/cargo')==P['signed_cargo_sha256'],'native toolchain identity')
    mapped=dict(re.findall(r'(?m)^\s*(\S+) => (\S+)',ld))
    m.guard(all(Path(mapped[k]).samefile(sdk/'lib'/k)for k in[ident['driver'],*ident['resolved_llvm']]),'foreign shared objects')
    return {'rustc':version,'cargo':cargo,'ldd':ld}

def inventory(sdk):
    expected=P['effective_inventory'];present={str(f.relative_to(sdk))for f in sdk.rglob('*')if f.is_file()}
    m.guard(set(expected)==present and all((f:=sdk/n).resolve()==f and f.stat().st_size==v['bytes'] and
            f.stat().st_mode&0o777==v['mode'] and m.filesha(f)==v['sha256']for n,v in expected.items()),'effective complete SDK inventory')
    return m.digest(m.canon(expected))
