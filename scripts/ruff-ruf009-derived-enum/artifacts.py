"""Download only enrolled workflow artifacts and verify each original byte."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile

REPO='astral-experiments/ohm'
def need(ok,why):
    if not ok:raise ValueError(why)
def gh(resource):
    return ['gh','api','repos/'+REPO+'/'+resource]
def api(resource):
    return json.loads(subprocess.check_output(gh(resource)))
def download(run,name,parent):
    assets=api(f'actions/runs/{run}/artifacts?per_page=100')
    need(assets['total_count']<100,'unexpected original artifact count')
    a,=[v for v in assets['artifacts']if v['name']==name]
    need(a['workflow_run']['id']==run and not a['expired'] and 0<a['size_in_bytes']<2000*(1<<20) and re.fullmatch('sha256:[a-f0-9]{64}',a['digest']),'unregistered artifact')
    archive=parent/'original.zip'
    need(shutil.disk_usage(parent).free>15*(1<<30)+2*a['size_in_bytes'],'readback disk reserve')
    with archive.open('xb')as f:subprocess.run(gh(f"actions/artifacts/{a['id']}/zip"),stdout=f,check=True)
    with archive.open('rb')as f:need('sha256:'+hashlib.file_digest(f,'sha256').hexdigest()==a['digest'] and archive.stat().st_size==a['size_in_bytes'],'changed original zip')
    result=parent/'data';result.mkdir()
    with zipfile.ZipFile(archive)as z:
        seen=set();size=0
        for e in z.infolist():
            member=Path(e.filename)
            need(not member.is_absolute() and '..'not in member.parts and not stat.S_ISLNK(e.external_attr>>16) and e.filename not in seen,'unsafe archive')
            seen.add(e.filename);size+=e.file_size;need(size<3000*(1<<20),'oversize raw packet')
            out=result/member
            if e.is_dir():out.mkdir(parents=True,exist_ok=True);continue
            out.parent.mkdir(parents=True,exist_ok=True)
            with z.open(e)as src,out.open('xb')as dest:shutil.copyfileobj(src,dest,1<<20)
    return result,{'run':run,'id':a['id'],'name':name,'bytes':a['size_in_bytes'],'sha256':a['digest'].split(':')[1]}

def recipe():
    suite=Path(__file__).resolve().parent
    repo=suite.parents[1]
    files=[repo/'.github/workflows/ci.yml']
    for path in [suite,repo/'scripts/ruff-module-16149',repo/'scripts/ruff-linter-check-attribution',repo/'scripts/ruff-heldout-mono-fold/residual']:
        files.extend(f for f in path.rglob('*') if f.is_file() and '__pycache__' not in f.parts and f.name not in ('factory.json','admitted-pilot.json'))
    ordered={str(f.relative_to(repo)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(files)}
    return hashlib.sha256(json.dumps(ordered,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def pilot_gate(root):
    path=Path(__file__).resolve().parent
    expected=json.loads((path/'admitted-pilot.json').read_bytes())
    run=expected['run'];head=expected['head']
    live=api(f'actions/runs/{run}')
    need(live['head_sha']==head and live['head_branch']==json.loads((path/'registration.json').read_bytes())['qa_branch'] and live['event']=='workflow_dispatch' and live['run_attempt']==1 and live['conclusion']=='success','pilot provenance')
    with tempfile.TemporaryDirectory(dir=root)as temp:
        files,identity=download(run,f'ruf009-reviewed-{run}',Path(temp))
        need(identity==expected['reader'],'different independently reviewed pilot')
        pilot=json.loads((files/'pilot-0.json').read_bytes())
        need(pilot['worker']['sha']==head and pilot['worker']['run']==run and pilot['worker']['phase']=='pilot' and pilot['worker']['block']==0 and pilot['pilot_admits'] and pilot['eligible_shape'] and pilot['reduction']>=0.10,'pilot did not qualify')
        need(pilot['worker']['recipe']==recipe(),'pilot and confirmation used different receiver code')
        need(pilot['worker']['factory']==json.loads((path/'factory.json').read_bytes()) and pilot['worker']['source']==json.loads((path/'registration.json').read_bytes()),'different product or ordinary registration')
    return expected
