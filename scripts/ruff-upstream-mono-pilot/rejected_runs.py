"""Reopen two refused runs descriptively after proving their complete native references equivalent."""
import collections,gzip,hashlib,json,os,subprocess,sys,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import native_reference as n

def document(z,key):
    data=z.read(key)
    return json.loads(gzip.decompress(data) if key.endswith(".gz") else data)

def history(z,refs):
    counts={};reuse={};storage={};rosters=set()
    factory=document(z,"factory.json");installed=document(z,"compiler-installations.json")["arms"]
    n.need(factory["run"]==41419184460 and factory["head"]=="eb9a39839aea21c67380644a1b2ba00a9afac79b","different original matched factory")
    for role,sha in (("normal","4a641b775a19853c0b73efa066bebf89bb7bb927a676811ee675137a304c39f4"),
                     ("defer","9f5b60652faf0d480a531e298d0de041283f154d0727199438633125bf7d9ee0")):
        ds=[v for k,v in installed[role]["files"].items() if k.startswith("lib/librustc_driver-")]
        n.need(ds==[sha],"unexpected original compiler")
    cpu=document(z,"cpu.json");n.need(len(set(cpu["cpus"]))==4 and len(cpu["boot"])==36,"unregistered physical CPU receipt")
    for name in ("0-P","0-C","1-C","1-P"):
        role=name[-1];counts[name]={};storage[name]={}
        for phase in ("B","A","unchanged","invalid","repair"):
            folder=name+"/"+phase+"/"
            rows=[json.loads(l) for l in gzip.decompress(z.read(folder+"cargo.stdout.gz")).splitlines()]
            ok=phase!="invalid"
            n.need(rows[-1]=={"reason":"build-finished","success":ok},"altered Cargo verdict")
            errors=[(v["target"]["name"],v["message"]["code"]["code"]) for v in rows if v["reason"]=="compiler-message"
                    and v["message"]["level"]=="error" and v["message"].get("code")]
            n.need(errors==([] if ok else [("ruff_python_parser","E0308")]),"unexpected diagnostic")
            if not ok:
                continue
            rev="B" if phase=="B" else "A"
            desc=document(z,folder+"native.json.gz");clean=document(z,("clean-A-"+role if rev=="A" else "0-"+role+"/B")+"/native.json.gz")
            visit=document(z,folder+"visit.json")
            n.need(sum(v["reason"]=="compiler-artifact" for v in rows)==375 and desc==clean and desc["cli"]["whole"]==refs[rev][role]
                   and visit["whole"]=={k:desc[k]["whole"] for k in ("cli","reader")},"different original contribution or native output")
            roster=sorted((r["package_id"],r["target"]["name"],tuple(r["target"]["kind"]),tuple(r["features"]),r["profile"]["test"])
                          for r in rows if r["reason"]=="compiler-artifact")
            digest=hashlib.sha256(json.dumps(roster,separators=(",",":")).encode()).hexdigest()
            n.need(visit["roster"]==digest and desc["typed"]=="Expr="+("56" if rev=="B" else "64")+" valid=1 rejected","different roster or typed revision")
            rosters.add(digest)
            if phase!="repair":
                counter=document(z,folder+"clock.json")
                n.need(counter["event_errno"]==0 and counter["enabled"]==counter["running"]>0 and counter["instructions"]==visit["count"]>0,
                       "invalid original hardware reading")
                counts[name][phase]=visit["count"];storage[name][phase]=visit["storage"]
        reuse[name]={}
        for owner,src in document(z,name+"/objects.json").items():
            value=0
            for obj in src["objects"].values():
                pre,post=obj["previous"],obj["current"];same=bool(pre and post and pre[:2]==post[:2])
                n.need(same==obj["same_inode"] and (not same or obj["before_sha256"]==obj["after_sha256"]),"inconsistent actual donor")
                value+=same
            reuse[name][owner]=value
    n.need(len(rosters)==1,"changed workspace inventory")
    return dict(boot=cpu["boot"],counts=counts,storage=storage,reuse=reuse,roster=rosters.pop())

def main():
    original=Path(os.environ["RUNNER_TEMP"]);out=original/"upstream-mono-study/logs";out.mkdir(parents=True)
    registrations=json.loads((HERE/"rejected-runs.json").read_bytes());evidence={}
    for r in registrations:
        run=str(r["run"]);place=original/("proof-"+run);place.mkdir()
        os.environ["RUNNER_TEMP"]=str(place)
        n.RUN,n.HEAD,n.ZIP,n.EXPECTED=r["run"],r["head"],tuple(r["archive"]),r["refs"]
        n.main(r["artifact_name"])
        root=place/"upstream-mono-study";v=json.loads((root/"logs/accepted-native.json").read_bytes())
        evidence[run]=dict(root=root,proof=v)
    os.environ["RUNNER_TEMP"]=str(original)
    a,b=evidence.values();across={}
    for rev in "AB":
        files=[v["root"]/(rev+"-P-ruff") for v in (a,b)]
        dirs=[os.fsencode(v["proof"]["results"][rev]["old"]) for v in (a,b)]
        across[rev]=n.compare(*files,*dirs)
    results={}
    for run,v in evidence.items():
        with zipfile.ZipFile(v["root"]/"failed-pilot.zip") as z:
            results[run]={"native":v["proof"],"history":history(z,v["proof"]["refs"])}
    n.need(len({v["history"]["boot"] for v in results.values()})==2,"repeated kernel boot")
    (out/"rejected-runs-analysis.json").write_text(json.dumps(dict(head=os.environ["REVIEWED_HEAD"],
        original_admission="refused", across_boots=across, results=results),indent=2,sort_keys=True)+"\n")
if __name__=="__main__":main()
