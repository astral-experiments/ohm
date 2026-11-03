"""Independently read the registered user-mode counters and every retained native body."""
import argparse
import collections
import hashlib
import json
import os
import re
import resource
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"source-pcs/verified-29697"))
from reopen import ar

OLD="157caa55a51ebae4fa541d31697e3af9a6c32ccf"
NEW="bfa2407e98ee1343caeefd02b4b69043509baa8c"
NAMES="34acb828168117d5f9e50edf4baa07e4153bd2f86d3e48514c1ae8cb21cc1f2f"
DIRTY={"ty_project","ty_ide","ty_server","e2e"}
ARM=("0P","1C","2C","3P")
PHASE=("old","edit","unchanged","repair","observed-old","observed-edit","observed-unchanged","independent-clean")

def must(value,message):
    if not value:raise ValueError(message)

def digest(path):
    with path.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()

def reader(archive,temp):
    with zipfile.ZipFile(archive) as z:
        names=set(z.namelist());must(len(names)==len(z.namelist()),"duplicate source member")
        def j(n):return json.loads(z.read(n))
        def docs(n):return [json.loads(line) for line in z.open(n+"/stdout.jsonl")]
        def pmu(n):
            p=j(n+"/hardware.json")
            must(p["status"]==0 and p["instructions"]>0 and p["enabled"]==p["running"]>0,n)
            return p["instructions"]
        reg=j("registration.json");factory=j("factory-consumed.json")
        must(reg["old"]==OLD and reg["new"]==NEW and reg["order"]==list("PCCP") and reg["factory"]==factory["binding"],"source and role registration")
        sealed=j("terminal.json");histories=[];body_specs={};rlibs=collections.defaultdict(list);roster=None
        for idx,arm in enumerate(ARM):
            role=j(arm+"/role.json");must(role["role"]==arm[1] and role["driver"]==reg["factory"]["driver"][arm[1]],"selected physical compiler")
            proof={};elf={}
            def body(item):
                sha=item["sha256"];must(re.fullmatch("[a-f0-9]{64}",sha) and 0<item["bytes"]<650*2**20,("native extent",item))
                must(body_specs.setdefault(sha,item["bytes"])==item["bytes"],"same hash, different extent")
            def verdict(n,passed):
                raw=z.read(n+"/list").decode().splitlines()
                tests=sorted(s.removesuffix(": test")for s in raw if s.endswith(": test"))
                must(len(set(tests))==len(tests)==200 and hashlib.sha256(("\n".join(tests)+"\n").encode()).hexdigest()==NAMES,n+" names")
                payload=z.read(n+"/stdout")+z.read(n+"/stderr")
                must((b"1 passed;" if passed else b"1 failed;")in payload and b"debug_command"in payload,n+" verdict")
                if not passed:must(b"snapshot"in payload.lower(),n+" stale")
            def kernel(n):
                was={};calls=[];cost=collections.Counter();lost=collections.Counter();allrows=z.read(n+"/tasks/epochs.tsv").decode().splitlines()
                phys=role["physical"]
                for line in allrows:
                    row=line.split()
                    if row[0]=="I":
                        image=int(row[1]);entry=z.read(n+f"/tasks/{image:05}.nul").split(b"\0")
                        must(entry.pop()==b"" and row[2].encode()==entry[0],n+" native image")
                        key=tuple(map(int,entry[1:3]));who=Path(os.fsdecode(entry[3])).name;argv=entry[4:]
                        if key==(phys["rustc"]["dev"],phys["rustc"]["ino"]) and b"--crate-name" in argv:
                            who="rustc:"+argv[argv.index(b"--crate-name")+1].decode()
                        if key==(phys["wild"]["dev"],phys["wild"]["ino"]):who="wild"
                        was[image]=who
                        if row[5]=="exec" and (who.startswith("rustc:") or who=="wild"):calls.append(who)
                    elif row[0]=="C":
                        image,_,_,count,enabled,running=map(int,row[1:7]);must(count>=0 and enabled==running,n+" kernel counter")
                        cost[was[image]]+=count
                        if count and not enabled:lost[was[image]]+=count
                return {"real_execs":calls,"process_instructions":dict(cost),"positive_instructions_without_clock":dict(lost)}
            verdict(arm+"/stale-old",False)
            for phase in PHASE:
                n=arm+"/"+phase;rows=docs(n);d=j(n+"/result.json")
                must(rows[-1]=={"reason":"build-finished","success":True},n+" cargo")
                a=[r for r in rows if r["reason"]=="compiler-artifact"]
                units=sorted([r["package_id"],r["target"]["name"],r["target"]["kind"],sorted(r["features"])]for r in a)
                if roster is None:roster=units
                must(len(units)==len(roster)==289 and units==roster and sorted(r["target"]["name"]for r in a if not r["fresh"])==d["dirty"],n+" units")
                if phase in ("old","independent-clean"):must(len(d["dirty"])==289,n+" empty control")
                if phase=="edit":must(set(d["dirty"])==DIRTY and len(d["dirty"])==4,n+" changed")
                if "unchanged"in phase:must(not d["dirty"],n+" unchanged")
                must(d["source"]==(OLD if phase in ("old","observed-old")else NEW),n+" source")
                if not phase.startswith("observed"):must(pmu(n)==d["instructions"],n+" hardware")
                if phase.startswith("observed"):
                    k=kernel(n);must(k==d["observed"],n+" independently decoded kernel census")
                    if phase=="observed-edit":must(sorted(k["real_execs"])==sorted(["rustc:"+x for x in DIRTY]+["wild"]),n+" literal exec roster")
                    if phase=="observed-unchanged":must(not k["real_execs"],n+" unchanged kernel roster")
                verdict(n+"/test",True);body(d["elf"]);elf[phase]=d["elf"]["sha256"]
                if phase in ("old","edit","independent-clean"):
                    diags=[json.loads(line)for line in z.open(n+"/interface.stderr")]
                    if phase=="old":must(any((x.get("code")or {}).get("code")=="E0599" and "scripts_to_synchronize"in x.get("message","")for x in diags),n+" old public method")
                    else:must(not any(x.get("level")=="error"for x in diags),n+" new public method")
                    body(d["producer_metadata"])
                if phase in ("old","edit","observed-old","observed-edit","independent-clean"):
                    o=j(n+"/ty-ide-objects.json");objs=o["objects"];must(len(objs)>=100 and all(re.fullmatch("[0-9a-z]+[.]o",k)for k in objs),n+" CGU inventory")
                    for item in o["outputs"].values():body(item)
                    for item in o["index_files"].values():
                        if "body"in item:body(item)
                    witness=collections.Counter((x["sha256"],x["bytes"])for x in objs.values())
                    rlibs[o["outputs"][".rlib"]["sha256"]].append(witness);proof[phase]=objs
            must(len(set(elf.values()))==2 and elf["old"]==elf["observed-old"] and all(elf[p]==elf["edit"]for p in PHASE if p not in ("old","observed-old")),arm+" complete executables")
            failure=docs(arm+"/invalid");must(failure[-1]=={"reason":"build-finished","success":False} and any((r.get("message",{}).get("code")or{}).get("code")=="E0308"for r in failure if r["reason"]=="compiler-message"),arm+" invalid")
            def classify(a,b):
                must(a.keys()==b.keys(),arm+" CGU names");kept=[];fresh=[]
                for name,x in a.items():
                    y=b[name];must((x["sha256"],x["bytes"])==(y["sha256"],y["bytes"]),arm+" CGU payload")
                    if (x["dev"],x["ino"])==(y["dev"],y["ino"]):
                        must(x["mtime_ns"]==y["mtime_ns"],arm+" recycled inode");kept.append(name)
                    else:fresh.append(name)
                return {"retained":sorted(kept),"regenerated":sorted(fresh)}
            before=classify(proof["old"],proof["edit"])
            must(before==j(arm+"/old-to-new-objects.json"),arm+" primary donors")
            must(classify(proof["observed-old"],proof["observed-edit"])==j(arm+"/observed-old-to-new-objects.json"),arm+" replay donors")
            classify(proof["edit"],proof["independent-clean"])
            rep=j(arm+"/qualified.json");must(rep==sealed["roles"][idx] and rep["retained"]==len(before["retained"]) and rep["primary"]==pmu(arm+"/edit") and rep["cold"]==pmu(arm+"/old") and rep["noop"]==pmu(arm+"/unchanged"),arm+" primary summary")
            histories.append({"role":arm,"primary":rep["primary"],"cold":rep["cold"],"noop":rep["noop"],"objects":len(proof["edit"]),"retained":rep["retained"],"old":elf["old"],"new":elf["edit"],"storage":rep["storage"]})
        must(len({r["old"]for r in histories})==len({r["new"]for r in histories})==1,"cross-role ELF")
        must({p for p in names if p.startswith("native/")}=={"native/"+sha+".zst"for sha in body_specs},"native archive coverage")
        for sha,size in sorted(body_specs.items()):
            path=temp/sha
            with path.open("xb")as dest:
                proc=subprocess.Popen(["zstd","-qdc"],stdin=subprocess.PIPE,stdout=dest,
                                      preexec_fn=lambda:resource.setrlimit(resource.RLIMIT_FSIZE,(size,size)))
                with proc.stdin,z.open("native/"+sha+".zst")as source:shutil.copyfileobj(source,proc.stdin,2**20)
                must(proc.wait()==0,"native zstd")
            must(path.stat().st_size==size and digest(path)==sha,"unsealed native file")
            if sha in rlibs:
                actual=ar(path);must(all(actual==registered for registered in rlibs[sha]),"rlib members differ from CGU session")
            path.unlink()
        pairs=[{"reduction":1-histories[c]["primary"]/histories[p]["primary"],"additional_objects":histories[c]["retained"]-histories[p]["retained"]}for p,c in ((0,1),(3,2))]
        gate=all(p["reduction"]>=.02 and p["additional_objects"]>0 for p in pairs)
        must(pairs==sealed["pairs"] and gate==sealed["gate"],"registered decision")
        return {"histories":histories,"pairs":pairs,"gate":gate,"native_bodies":len(body_specs),"rlibs":len(rlibs),"unique_raw_bytes":sum(body_specs.values()),"signed_sampled_discovery_reopened":"signed-discovery-reopened.json" in names}
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("archive",type=Path);p.add_argument("--sha256",required=True);p.add_argument("--output",type=Path,required=True);args=p.parse_args()
    must(digest(args.archive)==args.sha256 and shutil.disk_usage(args.archive.parent).free>16*2**30,"input identity or headroom")
    with tempfile.TemporaryDirectory(dir=args.archive.parent)as d:report=reader(args.archive,Path(d))
    args.output.write_text(json.dumps(report|{"original_sha256":args.sha256},indent=2,sort_keys=True)+"\n")
