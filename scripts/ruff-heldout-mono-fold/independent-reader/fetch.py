"""Authenticate the single six-boot GitHub enrollment and retain every original raw ZIP."""
import hashlib,json,os,re,shutil,subprocess,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
RUN=41442143564;HEAD='34a6dc52b4543454e7512018ce0586a562d8a03c';REPO='astral-experiments/ohm';GH='/home/dev-user/.local/bin/gh-auto';BRANCH='charlie/qa-heldout-mono-fold-27470-20261102';JOBS=[125266369213,125266369680,125266369669,125266369622,125266369767,125266369730];W=Path('/home/dev-user/code/oss/ohm-package-qa-heldout-mono-fold-27470-20261102')
def need(x,msg):
 if not x:raise RuntimeError(msg)
def api(path):return json.loads(subprocess.check_output([GH,'api','repos/'+REPO+'/actions/'+path],cwd=W))
def save(name,obj):(HERE/name).write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n')
old=None
while True:
 jobs=api(f'runs/{RUN}/attempts/1/jobs?per_page=30');need(jobs['total_count']==6 and set(j['id']for j in jobs['jobs'])==set(JOBS),'different six-boot job set');rows=sorted((j['id'],j['status'],j['conclusion'],tuple(s['number']for s in j['steps']if s['status']=='in_progress'))for j in jobs['jobs']);
 if rows!=old:print(rows,flush=True);old=rows
 if all(j['status']=='completed' for j in jobs['jobs']):break
 time.sleep(25)
run=api(f'runs/{RUN}');arts=api(f'runs/{RUN}/artifacts?per_page=30');need(run['run_attempt']==1 and run['head_sha']==HEAD and run['head_branch']==BRANCH and run['event']=='workflow_dispatch' and run['status']=='completed' and arts['total_count']==6,'different, partial or repeated confirmation');worker={int(j['name'].split()[-1]):j for j in jobs['jobs']};need(sorted(worker)==list(range(1,7))and len({v['runner_id']for v in worker.values()})==6 and len({v['runner_name']for v in worker.values()})==6,'workers or labels repeated');records={}
for a in arts['artifacts']:
 m=re.fullmatch(r'ruff-27470-matched-confirmation-([1-6])',a['name']);need(m is not None and not a['expired'] and 0<a['size_in_bytes']<330<<20 and a['workflow_run']['id']==RUN and a['workflow_run']['head_sha']==HEAD,'wrong worker artifact');slot=int(m[1]);j=worker[slot];need(slot not in records and j['id']==JOBS[slot-1] and j['name']==f'Ruff library-test confirmation boot {slot}' and j['runner_id']>0,'wrong slot');records[slot]=dict(slot=slot,job=j,artifact=a,file=f'slot-{slot}-{a["id"]}.zip')
need(set(records)==set(range(1,7)),'missing raw');save('github-provenance.json',dict(run=run,slots=records));
for n,v in sorted(records.items()):
 a=v['artifact'];p=HERE/v['file'];
 if not p.exists():
  while shutil.disk_usage(HERE).free<=(15<<30)+a['size_in_bytes']:print('holding original ZIP',n,'until 15 GiB reserve available',flush=True);time.sleep(30)
  tmp=p.with_suffix('.part');need(not tmp.exists(),'previous partial original');
  with tmp.open('xb')as f:subprocess.run([GH,'api',f'repos/{REPO}/actions/artifacts/{a["id"]}/zip'],cwd=W,stdout=f,check=True,timeout=400)
  with tmp.open('rb')as f:need('sha256:'+hashlib.file_digest(f,'sha256').hexdigest()==a['digest'] and tmp.stat().st_size==a['size_in_bytes'],'physical artifact checksum mismatch');tmp.rename(p)
 else:
  with p.open('rb')as f:need('sha256:'+hashlib.file_digest(f,'sha256').hexdigest()==a['digest'] and p.stat().st_size==a['size_in_bytes'],'retained package corrupted')
 print('authenticated',n,a['id'],a['size_in_bytes'],a['digest'],flush=True)
