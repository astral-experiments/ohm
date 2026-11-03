"""Keep exact raw counters, exec rosters and verdicts from the six original archives."""
import argparse,collections,hashlib,io,json,re,subprocess,tarfile,zipfile
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify import digest,must
def write(roots,receipts,output):
    index={};unique={}
    allowed=re.compile(r"(?:registration|terminal|factory-consumed|sdk-proof|signed-discovery-reopened)\.json|calibration-[0-9]+/hardware\.json|[01][PC]/(?:role|qualified|old-to-new-objects|observed-old-to-new-objects)\.json|[01][PC]/(?:stale-old|(?:old|edit|unchanged|repair|observed-old|observed-edit|observed-unchanged|independent-clean)/test)/(?:list|stdout|stderr)|[01][PC]/(?:old|edit|invalid|unchanged|repair|observed-old|observed-edit|observed-unchanged|independent-clean)/(?:stdout\.jsonl|hardware\.json|result\.json|ty-ide-objects\.json|interface\.stderr|tasks/(?:epochs\.tsv|[0-9]+\.nul))")
    for a in receipts:
        slot=a["slot"];source=roots/(str(slot)+".zip");must(digest(source)==a["sha256"],"wrong original")
        files={}
        with zipfile.ZipFile(source)as z:
            for item in z.infolist():
                name=item.filename
                if not allowed.fullmatch(name):continue
                must(item.file_size<=8*2**20,"unexpected raw record extent");b=z.read(item);key=hashlib.sha256(b).hexdigest()
                must(key not in unique or unique[key]==b,"different raw records with same digest");unique[key]=b;files[name]=key
        must("terminal.json"in files and "registration.json"in files,"missing original");index[str(slot)]={"source":a,"files":files}
    def add(t,key,data):
        e=tarfile.TarInfo(key);e.mode=0o644;e.size=len(data);t.addfile(e,io.BytesIO(data))
    with output.open("xb")as out,subprocess.Popen(["zstd","-q","-10","-T1","-c"],stdin=subprocess.PIPE,stdout=out)as proc:
        with proc.stdin,tarfile.open(fileobj=proc.stdin,mode="w|")as t:
            add(t,"index.json",(json.dumps(index,sort_keys=True,separators=(",",":"))+"\n").encode())
            for k,b in sorted(unique.items()):add(t,"records/"+k,b)
        must(proc.wait()==0,"compact archive compression")
    return {"archive_bytes":output.stat().st_size,"sha256":digest(output),"records":sum(len(x["files"])for x in index.values()),"unique_records":len(unique),"unique_bytes":sum(map(len,unique.values()))}
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("originals",type=Path);p.add_argument("verified",type=Path);p.add_argument("archive",type=Path);a=p.parse_args();print(json.dumps(write(a.originals,json.loads(a.verified.read_bytes())["assets"],a.archive),sort_keys=True))
