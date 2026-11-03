"""Read the full process counter and add the independent native-proof coordinator charge."""
from pathlib import Path
from zipfile import ZipFile
import hashlib,json,sys
p=Path(sys.argv[1])
with p.open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()=='6dcff8bf78023a304b67be31f2156b8c853e3a332f0d66434bcd9daf8ee8d3a0'
with ZipFile(p)as z:
    r=json.loads(z.read('complete.json'));result={}
    for tag in ('warm2','warm-repeat','capability','warm-control','signed-untouched-warm1','signed-untouched-warm2'):
        c=json.loads(z.read(tag+'/hardware.json'));q=r[tag]['ordinary_clock']
        assert c['instructions']==q['retired_user']and c['enabled']==c['running']>0 and c['status']==0
        coordinated=q.get('coordinator_thread')
        if coordinated:
            assert 0<coordinated['running']<=coordinated['enabled'] and coordinated['instructions']>0
            total=coordinated['instructions']+c['instructions'];assert total==q['cargo_and_coordinator_user_instructions']
        else:
            assert tag.startswith('signed-') and r[tag]['source_native_role_count']==0;total=c['instructions']
        result[tag]={'cargo_retired_user':c['instructions'],'cargo_enabled_ns':c['enabled'],'cargo_running_ns':c['running'],'independent_coordinator':coordinated,'charged_sum':total,'physical_cargo_elapsed_ns':int(z.read(tag+'/hardware.json.elapsed-ns'))}
    print(json.dumps(result,indent=2,sort_keys=True))
