from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib, json, re, subprocess as sp
HERE=Path(__file__).resolve().parent
GH='/home/dev-user/.local/bin/gh-auto'; API='repos/astral-experiments/ohm/actions/'
def api(endpoint):
    return json.loads(sp.check_output([GH, 'api', API+endpoint]))
def download(a):
    path=HERE/(str(a['id'])+'.zip')
    if not path.exists():
        tmp=path.with_suffix('.part')
        with tmp.open('wb')as f:sp.run([GH,'api',API+'artifacts/'+str(a['id'])+'/zip'],stdout=f,check=True)
        with tmp.open('rb')as f: assert 'sha256:'+hashlib.file_digest(f,'sha256').hexdigest()==a['digest']
        assert tmp.stat().st_size==a['size_in_bytes']; tmp.rename(path)
    (HERE/(str(a['id'])+'.github.json')).write_text(json.dumps(a,sort_keys=True,indent=2)+'\n')
    return [a['name'],a['id'],a['size_in_bytes']]
out=[]
for run,hed,allowed in [(41611390234,'bfd230f',set('01 02 03 04 05 06 07 8'.split())),(41611905762,'e1518fd',{'08'})]:
    r=api(f'runs/{run}'); assert r['event']=='workflow_dispatch' and r['run_attempt']==1 and r['head_sha'].startswith(hed) and r['repository']['full_name']=='astral-experiments/ohm'
    for a in api(f'runs/{run}/artifacts')['artifacts']:
        pair=a['name'].removeprefix(f'matched-sete-native-{run}-')
        assert pair in allowed and not a['expired'] and a['workflow_run']['id']==run and a['workflow_run']['head_sha']==r['head_sha']
        a['pair_seen']=pair
        out.append(a)
with ThreadPoolExecutor(max_workers=2) as e:
    for r in e.map(download,out):print(*r,flush=True)
