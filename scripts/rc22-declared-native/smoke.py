"""Run the published zero-link gate against a private toolchain. Never alter rustup's installed aliases."""
import argparse, hashlib, json, os, platform, shutil, subprocess
from pathlib import Path
args=argparse.ArgumentParser()
for name in ('lane','sdk','cargo','smoke'):args.add_argument(name,type=Path)
a=args.parse_args()
for k,v in vars(a).items():setattr(a,k,v.resolve())
def digest(p):
 with p.open('rb') as file:return hashlib.file_digest(file,'sha256').hexdigest()
assert digest(a.smoke)=='e57b87041abe1f91c78c29bb26e276e7ccd41e8f33a360aec616fb260d7ec175'
a.lane.mkdir()
env={k:v for k,v in os.environ.items() if not k.startswith(('CARGO_', 'RUST', 'OHM_', 'LLVM_'))}
for k,d in [('TMPDIR','tmp'),('RUSTUP_HOME','rustup'),('CARGO_HOME','cargo-home')]:
 p=a.lane/d;p.mkdir();env[k]=str(p)
kit=a.lane/'kit';(kit/'bin').mkdir(parents=True)
for p in a.sdk.iterdir():
 if p.name!='bin':(kit/p.name).symlink_to(p,target_is_directory=p.is_dir())
for p in (a.sdk/'bin').iterdir():(kit/'bin'/p.name).symlink_to(a.cargo if p.name=='cargo' else p)
subprocess.run(['rustup','toolchain','link','ohm-declared-proof',kit],cwd=a.lane,env=env,check=True)
versions={p:subprocess.check_output([p,'+ohm-declared-proof','-vV'],env=env,cwd=a.lane,text=True) for p in ('rustc','cargo')}
with (a.lane/'smoke.log').open('xb') as f:
 proc=subprocess.run(['bash','-x',a.smoke,'ohm-declared-proof',a.lane/'project'],cwd=a.lane,env=env,stdout=f,stderr=subprocess.STDOUT)
data={'host':platform.machine(),'cargo_sha256':digest(a.cargo),'smoke_sha256':digest(a.smoke),'versions':versions,'status':proc.returncode,'log_sha256':digest(a.lane/'smoke.log')}
(a.lane/'result.json').write_text(json.dumps(data,indent=2)+'\n')
print(json.dumps(data,indent=2));raise SystemExit(proc.returncode)
