"""Run paired disk cohorts from the common Rust 1.99 formatting baseline."""
import json,os,shutil,subprocess,sys,time
from pathlib import Path
root=Path(__file__).resolve().parent.parent;disk=root/'disk';bench=root/'bench'
cells=[f'{project}-{label}-{mode}' for mode in ['single','forks'] for project in ['ruff','uv'] for label in ['stock','ohm']]
selected={cell:cell for cell in cells}
for storage in selected.values():assert not (disk/'evidence'/storage).exists(),storage
with (disk/'selected-cohorts.json').open('x') as f:f.write(json.dumps(selected,indent=2)+'\n')
status={'state':'starting','pid':os.getpid(),'started_at':time.time(),'completed':[]}
def save():
 status['updated_at']=time.time();(disk/'compatible-controller.json').write_text(json.dumps(status,indent=2)+'\n')
def run(args,name):
 with (disk/name).open('x') as log:subprocess.run([sys.executable,'-B',*map(str,args)],stdout=log,stderr=subprocess.STDOUT,check=True)
try:
 save()
 for cell,storage in selected.items():
  project,label,mode=cell.split('-');evidence=disk/'evidence'/storage
  required_gib=60+{'ruff-stock-single':8,'ruff-ohm-single':8,'uv-stock-single':16,'uv-ohm-single':14,'ruff-stock-forks':60,'ruff-ohm-forks':40,'uv-stock-forks':88,'uv-ohm-forks':48}[cell]
  while shutil.disk_usage(root).free<required_gib*1024**3:
   status.update(state='waiting for capacity',cohort=storage,required_free_gib=required_gib,free_gib=shutil.disk_usage(root).free/1024**3);save();time.sleep(10)
  status.update(state='running',cohort=storage);save();print(storage,flush=True)
  run([bench/'run-disk.py',project,label,mode],storage+'-run.log')
  if project=='uv':run([bench/'check-disk-runtime.py',evidence],storage+'-runtime-audit.log')
  run([bench/'export-disk.py',evidence],storage+'-audit.log')
  run([bench/'retire-cohort.py',evidence],storage+'-retirement.log')
  status['completed'].append(storage);save()
 run([bench/'export-disk.py'],'compatible-final-audit.log')
 status.update(state='complete',completed_at=time.time());save()
except BaseException as error:
 status.update(state='failed',error=repr(error));save();raise
