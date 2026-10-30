"""Capture only our own named APFS fixture events and expose the kernel stat schema."""
import json,os
from pathlib import Path
import subprocess,sys,tempfile,threading,time
sys.path.insert(0,str(Path(__file__).resolve().parent))
from study import need,save

def frames(stream):
    chunks=[];total=0
    for line in stream:
        if not chunks and not line.strip():continue
        chunks.append(line);total+=len(line)
        need(total<8*2**20,"oversized ES event")
        if line.startswith(b"}") or len(chunks)==1 and line.strip().endswith(b"}"):
            item=json.loads(b"".join(chunks));chunks=[];total=0
            yield item
    need(not chunks,"incomplete ES event")

def run(root):
    root.mkdir(parents=True,exist_ok=True)
    stem="ohm-response-schema-"+str(os.getpid())
    base=Path(subprocess.check_output(["/usr/bin/getconf","DARWIN_USER_TEMP_DIR"],text=True).strip()).resolve(strict=True)
    out=root/"monitor.stderr";matches={};failures=[];stats=[];events=[]
    with out.open("wb") as err:
        p=subprocess.Popen(["sudo","-n","/usr/bin/eslogger","create","rename","link","unlink"],stdout=subprocess.PIPE,stderr=err,start_new_session=True)
        def read():
            try:
                for r in frames(p.stdout):
                    if stem in json.dumps(r["event"],separators=(",",":")):
                        for key in r["event"]:
                            matches.setdefault(key,r);events.append([key,r.get("seq_num"),r.get("global_seq_num")])
            except Exception as e:failures.append(str(e))
        t=threading.Thread(target=read,daemon=True);t.start()
        try:
            for trial in range(25):
                tag=stem+"-"+str(trial);src=base/(tag+".in");target=base/(tag+".out");other=base/(tag+".alias")
                with src.open("xb") as tmp:tmp.write(b"39")
                held=os.open(src,os.O_RDONLY|os.O_NOFOLLOW);s=os.fstat(held)
                stats.append({"file":str(src),"inode":s.st_ino,"device":s.st_dev,"uid":s.st_uid,"mode":s.st_mode,"pid":os.getpid()})
                src.rename(target);os.link(target,other);other.unlink();target.unlink();os.close(held)
                time.sleep(.15)
                if len(matches)==4:break
            time.sleep(.25)
            save(root/"known.json",{"observed":matches,"changes":events,"own":stats,"errors":failures})
            print("event shapes",sorted(matches),"monitor stderr",out.read_text()[-400:],flush=True)
            need(set(matches)=={"create","rename","link","unlink"} and not failures,"did not witness all known APFS operations")
        finally:
            subprocess.run(["sudo","-n","/bin/kill","-TERM",str(p.pid)],capture_output=True)
            try:p.wait(timeout=3)
            except subprocess.TimeoutExpired:p.kill()
if __name__=="__main__":run(Path(sys.argv[1]))
