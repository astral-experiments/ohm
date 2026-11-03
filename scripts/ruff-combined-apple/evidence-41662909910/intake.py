"""Verify the run identity, download archived originals, and extract into a private directory."""
import hashlib,json,os,shutil,stat,subprocess,sys,tarfile,zipfile
from pathlib import Path,PurePosixPath
base=Path(sys.argv[4]).resolve();base.mkdir(exist_ok=True)
which=sys.argv[3]
repo='repos/astral-experiments/ohm'
run=int(sys.argv[1])
head=sys.argv[2]
gh=['/home/dev-user/.local/bin/gh-auto','api']
def api(endpoint):return json.loads(subprocess.check_output(gh+[repo+endpoint]))
def sha(path):
 with path.open('rb')as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
state=api('/actions/runs/'+str(run));assert state['id']==run and state['head_sha']==head and state['run_attempt']==1 and state['event']=='workflow_dispatch'
(base/'run.json').write_text(json.dumps(state,indent=2)+'\n')
assets=api('/actions/runs/'+str(run)+'/artifacts')['artifacts']
(base/'assets.json').write_text(json.dumps({'artifacts':assets},indent=2)+'\n')
artifacts=[a for a in assets if a['name'].startswith('integrated-qa-sdk-')==(which=='sdk')]
assert len(artifacts)==(1 if which=='sdk'else 4),[(a['name'],a['size_in_bytes'])for a in artifacts]
for a in artifacts:
 assert not a['expired'] and a['workflow_run']['id']==run and a['workflow_run']['head_sha']==head
 file=base/(a['name']+'.zip')
 if not file.is_file():
  tmp=file.with_suffix('.partial')
  with tmp.open('wb')as stream:subprocess.run(gh+[repo+'/actions/artifacts/'+str(a['id'])+'/zip'],stdout=stream,check=True)
  assert tmp.stat().st_size==a['size_in_bytes']and 'sha256:'+sha(tmp)==a['digest']
  tmp.rename(file)
 assert file.stat().st_size==a['size_in_bytes']and 'sha256:'+sha(file)==a['digest']
 out=base/a['name'];out.mkdir(exist_ok=True)
 with zipfile.ZipFile(file)as z:
  names=z.namelist();assert len(names)==len(set(names))and not z.testzip()
  for i in z.infolist():
   n=PurePosixPath(i.filename);assert not n.is_absolute()and '..'not in n.parts and not stat.S_ISLNK(i.external_attr>>16)
   dest=out/n
   if i.is_dir():dest.mkdir(parents=True,exist_ok=True);continue
   if not dest.exists():
    dest.parent.mkdir(parents=True,exist_ok=True)
    with z.open(i)as source,dest.open('wb')as target:shutil.copyfileobj(source,target)
 if which=='sdk':
  sdk=base/'replayed-sdk';sdk.mkdir(exist_ok=True)
  tar=out/'fixed-linux-sdk.tar.zst'
  with subprocess.Popen(['zstd','-qdc','--',tar],stdout=subprocess.PIPE)as proc:
   with tarfile.open(fileobj=proc.stdout,mode='r|')as members:
    for m in members:
     n=PurePosixPath(m.name);assert n.parts[0]in ('bin','lib')and '..'not in n.parts and (m.isdir()or m.isfile())
     members.extract(m,sdk,filter='data')
   assert proc.wait()==0
  ru=base/'rustup/toolchains';ru.mkdir(parents=True,exist_ok=True)
  if not (ru/'ohm').exists():(ru/'ohm').symlink_to(sdk,target_is_directory=True)
  probes={}
  for cmd in ('cargo','rustc','rustdoc'):
   s=subprocess.check_output([cmd,'+ohm','-vV'],env={'HOME':os.environ['HOME'],'PATH':os.environ['PATH'],'RUSTUP_HOME':str(ru.parent)},text=True)
   probes[cmd]={'version':s,'sha256':sha(sdk/'bin'/cmd)}
  (base/'replayed-executables.json').write_text(json.dumps(probes,indent=2)+'\n')
 print(a['id'],a['name'],file.stat().st_size,a['digest'],flush=True)
