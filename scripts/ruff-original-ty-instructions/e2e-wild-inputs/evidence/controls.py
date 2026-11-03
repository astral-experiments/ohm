"""Corrupt three real syscalls one at a time and require the independent raw reader to refuse."""
import gzip,json,sys,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from reopen import argv,parse
class Replace:
    def __init__(self,z,key,updated):self.z,self.key,self.updated=z,key,updated
    def namelist(self):return self.z.namelist()
    def read(self,k):return self.updated if k==self.key else self.z.read(k)
def main(p):
    answers=[]
    with zipfile.ZipFile(p)as z:
        a=argv(z.read('native-capture/argv.nul'));q=parse(z,'syscall-observer',a)
        miss=q['winners']['util']['examined'][0];sy=q['actual_symbols']['maps'][0]
        for label,tid,seq,old,new in [('erase earlier negative',miss['tid'],miss['seq'],None,None),('change kernel result',miss['tid'],miss['seq'],b'ENOENT',b'EACCES'),('erase symbols mmap',sy['tid'],sy['seq'],None,None)]:
            path=f'syscall-observer/syscalls/task.{tid}.gz';lines=gzip.decompress(z.read(path)).splitlines(keepends=True)
            if new is None:del lines[seq]
            else:assert lines[seq].count(old)==1;lines[seq]=lines[seq].replace(old,new)
            try:parse(Replace(z,path,gzip.compress(b''.join(lines),mtime=0)),'syscall-observer',a)
            except AssertionError:answers.append({'case':label,'raw_task':tid,'seq':seq,'result':'refused'})
            else:raise RuntimeError(label)
    print(json.dumps(answers,sort_keys=True))
if __name__=='__main__':main(Path(sys.argv[1]))
