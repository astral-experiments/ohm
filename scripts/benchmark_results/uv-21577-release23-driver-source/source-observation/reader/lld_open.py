"""Optional independent check of the actual final LLD open, using the already enrolled PID and raw trace."""
import gzip,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from read import OPEN,digest,load,reduce,require,save,stream

def probe(visit,actual_pid=None,expected_exe=None):
    v=Path(visit);obs=reduce(v);req=load(v/"request.json")
    path=obs["policy"]+"/"+str(obs["pid"])+".exports";found=[]
    for entry in load(v/"trace.json")['files']:
        pid=int(entry['file'].split('.')[1])
        events=stream(gzip.decompress((v/entry['file']).read_bytes()),req['cwd'])
        binary=None
        for line,call,args,rc,err,arg in events:
            if call in ('execve','execveat') and rc==0:
                binary=arg
            if call in OPEN and arg==path and rc>=0 and 'O_RDONLY' in args:
                require(binary and Path(binary).name in ('ld.lld','rust-lld'),("unexpected policy reader",pid,binary))
                found.append({'pid':pid,'exe':binary,'line':line,'path':path,'trace':entry['sha256']})
    require(len(found)==1,("missing/excess kernel LLD policy-file open",found))
    if actual_pid is not None:require(found[0]['pid']==actual_pid,("late PID mismatch",found,actual_pid))
    if expected_exe is not None:require(found[0]['exe']==expected_exe,("late executable mismatch",found,expected_exe))
    return found[0]

if __name__=='__main__':
    p=Path(sys.argv[1]);out=Path(sys.argv[2]);cases=load(p/'accepted.json')['cases']
    save(out,{k:probe(next((p/k/'phase').glob('visit-*')))for k in cases})
