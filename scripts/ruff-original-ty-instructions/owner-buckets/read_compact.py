"""Verify the permanent raw control archive without downloading full Rust native bodies."""
import argparse,hashlib,json,math,statistics,subprocess,tarfile
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify import digest,must
def close(path,sha):
    must(path.stat().st_size<40*2**20 and digest(path)==sha,"compact identity");table={};idx=None
    with subprocess.Popen(["zstd","-qdc",path],stdout=subprocess.PIPE)as p:
        with p.stdout,tarfile.open(fileobj=p.stdout,mode="r|")as tf:
            for f in tf:
                must(f.isreg()and 0<=f.size<20*2**20 and len(table)<30000,"unexpected archive shape")
                data=tf.extractfile(f).read()
                if f.name=="index.json":must(idx is None,"duplicate index");idx=json.loads(data);continue
                prefix,sep,h=f.name.partition("/");must(prefix=="records"and sep=="/"and h==hashlib.sha256(data).hexdigest()and h not in table,"bad raw record");table[h]=data
        must(p.wait()==0,"corrupt compression")
    boots=set();pairs=[];referenced=set()
    for slot,order in enumerate(("PC","CP","CP","PC","PC","CP")):
        files=idx[str(slot)]["files"];referenced.update(files.values());rd=lambda n:json.loads(table[files[n]])
        reg=rd("registration.json");bid=reg["boot_id"];must(bid not in boots and "".join(reg["order"])==order and reg["slot"]==slot,"boot/ordering");boots.add(bid);r={}
        for i,label in enumerate(order):
            arm=str(i)+label;h=rd(arm+"/edit/hardware.json");must(h["status"]==0 and h["enabled"]==h["running"]>0 and h["instructions"]>0,"primary physical counter")
            before=rd(arm+"/old/ty-ide-objects.json")["objects"];after=rd(arm+"/edit/ty-ide-objects.json")["objects"];fresh=rd(arm+"/independent-clean/ty-ide-objects.json")["objects"]
            must(before.keys()==after.keys()==fresh.keys(),"wrong inventory");kept=0
            for k,b in before.items():
                y=after[k];must(b["sha256"]==y["sha256"]==fresh[k]["sha256"],"changed object")
                if (b["dev"],b["ino"])==(y["dev"],y["ino"]):must(b["mtime_ns"]==y["mtime_ns"],"inode was reused");kept+=1
            r[label]=(h["instructions"],kept)
        pairs.append({"slot":slot,"boot":bid,"P":r["P"][0],"C":r["C"][0],"speedup":r["P"][0]/r["C"][0],"donors_P":r["P"][1],"donors_C":r["C"][1]})
    must(referenced==table.keys(),"missing or unbound raw record")
    gains=[x["speedup"]for x in pairs];n=len(gains);k=min(sum(x>1 for x in gains),sum(x<1 for x in gains))
    return {"pairs":pairs,"median":statistics.median(gains),"range":[min(gains),max(gains)],"two_sided_sign_p":min(1,2*sum(math.comb(n,i)for i in range(k+1))/2**n)}
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("archive",type=Path);p.add_argument("--sha256",required=True);args=p.parse_args();print(json.dumps(close(args.archive,args.sha256),indent=2))
