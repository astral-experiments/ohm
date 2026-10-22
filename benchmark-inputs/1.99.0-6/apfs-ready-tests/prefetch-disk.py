import hashlib,json,os,subprocess,time,tomllib
from pathlib import Path
root=Path('/private/tmp/ohm-benchmarks-1.99.0-6/apfs-ready-tests/disk')
proof=json.loads((root/'source-preparation.json').read_text())
rows=[];coverage=[]
env={k:v for k,v in os.environ.items() if not k.startswith(('CARGO_','RUST','__CARGO_')) and k!='PYTHONSAFEPATH'}
env.update(CARGO_HOME='/private/tmp/codex-cargo-home',CARGO_TARGET_DIR='/private/tmp/codex-cargo-targets/ohm/isolated/release-1.99.0-6/prefetch',GIT_CONFIG_COUNT='2',GIT_CONFIG_KEY_0='maintenance.auto',GIT_CONFIG_VALUE_0='false',GIT_CONFIG_KEY_1='gc.auto',GIT_CONFIG_VALUE_1='0')
(root/'prefetch').mkdir(exist_ok=True)
for project,item in proof.items():
 source=Path(item['source']);fixture=json.loads((Path('/private/tmp/ohm-benchmarks-1.99.0-6/ohm/scripts/session_replays')/item['fixture']).read_text());base=fixture['base_revision']
 wt=root/'prefetch'/project
 if wt.exists():
  assert subprocess.check_output(['git','-C',str(wt),'rev-parse','HEAD'],text=True).strip()==base
 else:subprocess.run(['git','-C',str(source),'worktree','add','--detach',str(wt),base],check=True)
 with (root/'prefetch'/(project+'.log')).open('x') as log:
  subprocess.run(['cargo','+ohm','fetch','--locked'],cwd=wt,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
 lock=(wt/'Cargo.lock').read_bytes();packages={(x['name'],x['version'],x['source'],x.get('checksum')) for x in tomllib.loads(lock.decode())['package'] if 'source' in x}
 rows.append({'project':project,'base':base,'lock_sha256':hashlib.sha256(lock).hexdigest()})
 for revision in item['required_commits']:
  raw=subprocess.check_output(['git','-C',str(source),'show',revision+':Cargo.lock'])
  selected={(x['name'],x['version'],x['source'],x.get('checksum')) for x in tomllib.loads(raw.decode())['package'] if 'source' in x}
  assert selected<=packages,(project,revision,selected-packages)
  coverage.append({'project':project,'revision':revision,'lock_sha256':hashlib.sha256(raw).hexdigest(),'all_packages_in_prefetched_base':True})
(root/'prefetch.json').write_text(json.dumps({'completed_at':time.time(),'sources':rows,'passed':True},indent=2)+'\n')
(root/'dependency-coverage.json').write_text(json.dumps({'passed':True,'sources':coverage},indent=2)+'\n')
print('APFS dependencies verified',flush=True)
