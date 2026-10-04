"""Require 30 seconds of >=95% aggregate idle before validation work."""
import json,sys,time,shutil
from pathlib import Path
sys.path.insert(0,'/tmp/ohm-release-campaign/llvm/harness')
from measure_v3 import external_compilers
root=Path('/tmp/ohm-release-campaign/llvm')
def cpu():return list(map(int,Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
a=cpu();started=time.time();time.sleep(30);b=cpu();d=[y-x for x,y in zip(a,b)]
r={'phase':sys.argv[1],'start_unix':started,'end_unix':time.time(),'cpu_ticks_before':a,'cpu_ticks_after':b,'idle_percent':100*d[3]/sum(d),'iowait_percent':100*d[4]/sum(d),'steal_percent':100*d[7]/sum(d),'free_bytes':shutil.disk_usage(root).free,'external_compilers':external_compilers()}
(root/'evidence'/('idle-gate-'+sys.argv[1]+'.json')).write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r),flush=True)
assert r['idle_percent']>=95 and not r['external_compilers'],r
assert r['free_bytes']>=20*1024**3,r
