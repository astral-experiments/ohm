#!/usr/bin/env python3
"""Load this trusted experiment's monitor helper under PYTHONSAFEPATH."""
import hashlib,json,runpy,sys,time
from pathlib import Path
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))
record_path=root/'runtime-transition.json'
record=json.loads(record_path.read_text()) if record_path.exists() else {}
source=Path(__file__).read_text()
record.setdefault('bootstrap_launches',[]).append({'time':time.time(),'reason':'PYTHONSAFEPATH excludes the script directory; add only this trusted experiment directory before importing the frozen monitor helper.','source':source,'sha256':hashlib.sha256(source.encode()).hexdigest(),'runtime_sha256':hashlib.sha256((root/'runtime.py').read_bytes()).hexdigest(),'helper_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [root/'ablate.py',root/'ablate_original.py'] if p.exists()},'arguments':sys.argv[1:]})
record_path.write_text(json.dumps(record,indent=2)+'\n')
runpy.run_path(str(root/'runtime.py'),run_name='__main__')
