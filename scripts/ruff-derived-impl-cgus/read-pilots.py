"""Reopen both original enrolled source pilots on a separate machine."""
import hashlib,json,os,shutil,subprocess,sys
from pathlib import Path
h=Path(__file__).resolve().parent
root=Path(os.environ['RUNNER_TEMP']);out=root/'verified-pilots';out.mkdir()
assert int(next(x.split()[1]for x in Path('/proc/meminfo').read_text().splitlines()if x.startswith('MemAvailable:')))>8*2**20 and shutil.disk_usage(root).free>16*2**30
for name,run,job,asset,size,head,sha in [
 ('28392',41731293461,126249036171,13278037542,180990251,'453a3893b5844334a5b7f1c770c14e94ad1a34f8','d8f109648a86cf0c3b8b1daea0b51ef2197a4cb8ffc96b7943252e021c914e13'),
 ('26372',41735947765,126265083879,13279078044,189841597,'96c451cc7c6eee5682ec8d98537e0f09d69fd2cc','f605f80c9dda9ad1410ed0fef578c27df320916accff841763f35b138c5fb055')]:
 api=lambda path:json.loads(subprocess.check_output(['gh','api','repos/astral-experiments/ohm/actions/'+path]));j,t,m=api('runs/'+str(run)),api('jobs/'+str(job)),api('artifacts/'+str(asset))
 assert j['head_sha']==head and j['run_attempt']==1 and t['run_id']==run and t['conclusion']=='success'and m['workflow_run']['id']==run and m['size_in_bytes']==size and m['digest']=='sha256:'+sha
 package=root/(name+'.zip')
 with package.open('xb')as f:subprocess.run(['gh','api','repos/astral-experiments/ohm/actions/artifacts/'+str(asset)+'/zip'],stdout=f,check=True)
 assert package.stat().st_size==size;subprocess.run([sys.executable,'-IB',h/'reopen.py',package,sha,out/(name+'.json')],check=True)
 (out/(name+'-binding.json')).write_text(json.dumps(dict(artifact=asset,run=run,job=job,sha256=sha,bytes=size,head=head),sort_keys=True)+'\n');package.unlink()
