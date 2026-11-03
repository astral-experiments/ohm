from pathlib import Path
import hashlib,os,sys,time,signal,subprocess,json,shutil,re
sources=Path(__file__).resolve().parent;sys.path.insert(0,str(sources.parent/'ruff-foreign-span-observer'))
import worker as base
# Both controls run without export credentials after authenticating exactly the shipped SDK.
e=base.install();assert all(not any(x in k for x in ('TOKEN','SECRET','PASSWORD','CREDENTIAL'))for k in e)
assert 'RUSTFLAGS'not in e and 'CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST'not in e
root=Path(os.environ['RUNNER_TEMP'])/'join-custody';root.mkdir();log=base.proof;all={}
for name in ('scheduler','macro','source-class'):
 dest=root/name;shutil.copytree(sources/('macro'if name=='source-class'else name),dest);pub=log/name;pub.mkdir();spec=json.loads((sources/name/'prereg.json').read_bytes());(pub/'registration.json').write_text(json.dumps({'commit':os.environ['GITHUB_SHA'],'source_sha256':base.hf(dest/'probe.py'),'plan':spec},indent=2)+'\n');minimum=base.avail();assert minimum>=10*2**30;start=time.monotonic()
 with (pub/'script.stdout').open('wb')as so,(pub/'script.stderr').open('wb')as se:
  p=subprocess.Popen(['python3','-IB',str(dest/'probe.py')],cwd=dest,env=e,stdout=so,stderr=se,start_new_session=True)
  while p.poll()is None:
   minimum=min(minimum,base.avail())
   if minimum<8*2**30 or shutil.disk_usage(root).free<15*2**30 or time.monotonic()-start>240:
    os.killpg(p.pid,signal.SIGKILL);p.wait();raise ValueError('resource or duration admission')
   time.sleep(.1)
 all[name]=p.returncode
 for n in ('fixture','runs','results','bodies'):
  if (dest/n).is_dir():shutil.copytree(dest/n,pub/n)
 if (dest/'completed.json').is_file():shutil.copyfile(dest/'completed.json',pub/'completed.json')
 base.put(pub/'stage.json',{'exit':p.returncode,'minimum_available':minimum})
 print(name,p.returncode,flush=True)
base.put(log/'terminal.json',all);assert all=={'macro':0,'scheduler':0,'source-class':0},all
