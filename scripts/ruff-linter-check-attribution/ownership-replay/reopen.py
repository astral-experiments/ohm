"""Independently inspect the Actions ZIP without unpacking or executing its programs."""
import argparse
from collections import Counter, deque
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tarfile
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
import rmeta
import controls

HERE = Path(__file__).resolve().parent
PHASES = ("old","old-unchanged","edited","new-unchanged","invalid","repair","clean")
ROLES = ("rustc","cc","collect2","wild")
PROD = "annotate_snippets"
DIRECT = {"ruff_db","ty_site_packages"}
COMMAND = ["cargo","+ohm","check","-p","ty_server","--lib","--locked","--offline","--message-format=json"]


def verify(ok, explanation):
    if not ok:
        raise ValueError(explanation)


def native(z, reference, where, ids):
    def rows(name):
        return [l.split("\t") for l in z.read(where+"/"+name).decode().splitlines()]
    def arg(n):
        body=z.read(where+f"/args-{n:04d}")
        verify(body.endswith(b"\0") and len(body)>1,"incomplete kernel command")
        return body[:-1].decode().split("\0")
    size, typ, event, read_format, inherit, disabled, kernel, hv, cloexec = map(int, rows("abi.tsv")[0])
    verify((typ,event,read_format,inherit,disabled,kernel,hv,cloexec)==(0,1,3,1,1,1,1,8),"event diagnostic")
    for name,on_exec in (("whole",4096),("subtree",0)):
        body=z.read(where+"/"+name+"-attr.bin")
        verify(len(body)==size and struct.unpack_from("<IIQQQQQ",body)==(0,size,1,0,0,3,99+on_exec) and not any(body[48:]),"actual kernel perf ABI")
    tasks=rows("tasks.tsv")
    root,=[int(r[1]) for r in tasks if r[0]=="root"]
    closes={int(r[1]):tuple(map(int,r[2:])) for r in tasks if r[0]=="exit"}
    births={int(r[2]):int(r[1]) for r in tasks if r[0]=="spawn"}
    declared={int(r[1]):int(r[2]) for r in tasks if r[0]=="task"}
    verify(len(closes)==sum(r[0]=="exit" for r in tasks) and len(births)==sum(r[0]=="spawn" for r in tasks)
           and set(closes)==set(declared)=={root,*births}, "open kernel descendant set")
    def lineage(pid):
        line=[]
        while pid!=root:
            verify(pid in births and pid not in line,"missing ancestor")
            line.append(pid);pid=births[pid]
        return [*line,root]
    chains={p:lineage(p) for p in declared}
    verify(all(declared[p] in c for p,c in chains.items()) and closes[root]==(0,0),"thread/proc closure")
    events={};selected={}
    for rec in rows("exec.tsv"):
        serial,pid,role,actual,dev,ino=map(int,rec[:6]); identity=[dev,ino,rec[6]]
        verify(serial==len(events)+1 and pid in declared and ["exec",str(pid),str(serial)] in tasks,"actual exec")
        flags=[i for i,k in enumerate(ROLES,1) if ids["selectors"][k][:2]==[dev,ino]]
        verify(len(flags)<=1 and role==(flags[0] if flags else 0),"physical selector")
        a=arg(serial); events[serial]=(pid,identity,a,role)
        expect=(role==1 and "--crate-name" in a and "--out-dir" in a) or (role in (2,4) and "-o" in a)
        verify(bool(actual)==expect,"unmetered exec")
        if actual:selected[serial]=(pid,a,role)
    verify(len(events)==sum(r[0]=="exec" for r in tasks),"open exec ledger")
    verify(events[1][:3]==(root,ids["process"]["proxy"],COMMAND),"normal Cargo proxy")
    actual_cargo,=[p for p,e,a,r in events.values() if e==ids["process"]["cargo"] and a[1:]==COMMAND[2:]]
    samples={}
    for r in rows("samples.tsv"):
        n,p,kind,err,readsize,count,enabled,running=map(int,r)
        verify(n not in samples and (p,kind)==((root,0) if n==0 else (selected[n][0],selected[n][2]))
               and err==0 and readsize==24 and 0<count and running==enabled>0,"invalid or multiplexed sample")
        samples[n]=count
    verify(set(samples)=={0,*selected},"sample domain")
    hosts={p for p,a,kind in selected.values()}
    verify(len(hosts)==len(selected),"compiler re-exec")
    workers={};physical={}
    for n,(pid,a,kind) in selected.items():
        verify(kind==1 and not (hosts&set(chains[pid][1:])) and actual_cargo in chains[pid][1:]
               and closes[pid]==(0,0),"non-disjoint or failed compiler")
        verify(not any(other!=pid and pid in chains[other] for other,_,_,_ in events.values()),"subprocess exec below compiler")
        pos=tasks.index(["exec",str(pid),str(n)])
        verify(not any(v[:2]==["spawn",str(pid)] for v in tasks[:pos]) and not any(v[:2]==["exec",str(pid)] for v in tasks[pos+1:]),"open owner interval")
        verify(a.count("--crate-name")==1 and a.count("--out-dir")==1 and a.count("--emit=dep-info,metadata")==1,"check-only mode")
        name=a[a.index("--crate-name")+1]
        verify(name not in workers and name in reference["argv"],"duplicate or foreign target")
        # Compare every argv byte except the single per-boot SDK directory at the registered path options.
        shard=set(re.findall(r"/v2-[0-9a-f]{16}/","\0".join(a)))
        verify(len(shard)==1,"unexpected namespaces")
        (source,)=shard
        rewritten=[]
        for index,value in enumerate(a):
            if source in value:
                verify(index>0 and (a[index-1] in ("-L","--extern","--out-dir") or
                       a[index-1]=="-C" and value.startswith("incremental=")), "changed compiler setting")
            rewritten.append(value.replace(source,"/v2-<sdk>/"))
        verify(hashlib.sha256(json.dumps(rewritten,separators=(",",":")).encode()).hexdigest()==reference["argv"][name],"unregistered rustc argv: "+name)
        externs={a[i+1].partition("=")[0] for i in range(len(a)-1) if a[i]=="--extern"}
        verify((PROD in externs)==(name in DIRECT),"wrong direct dependency")
        workers[name]=samples[n];physical[name]={"pid":pid,"serial":n,"arguments":len(a),"tasks":sum(pid in c for c in chains.values())}
    phase=where.removeprefix("events-")
    cargo_rows=[json.loads(l) for l in z.read("P/"+phase+"/stdout").splitlines()]
    verify(Counter(x["target"]["name"] for x in cargo_rows if x["reason"]=="compiler-artifact" and not x["fresh"])
           ==Counter(workers.keys()) and cargo_rows[-1]=={"reason":"build-finished","success":True},"typed Cargo/exec disagreement")
    verify(set(workers)==(set(reference["argv"]) if phase=="edited" else set()),"historical roster")
    check=json.loads(z.read("P/"+phase+"/ownership.json"))
    verify(check["whole"]==samples[0] and {v["crate"]:v["instructions"] for v in check["owners"]}==workers,"worker counters vs actual raw")
    root_remainder=samples[0]-sum(workers.values())
    buckets={"producer": workers.get(PROD,0), "direct":sum(workers.get(k,0) for k in DIRECT),
             "indirect":sum(v for k,v in workers.items() if k not in DIRECT|{PROD})}
    verify(root_remainder>0 and check["residual"]==root_remainder and check["group"]==buckets,"overlap or bad arithmetic")
    return {"whole":samples[0],"outside_named_rustcs":root_remainder,"groups":buckets,"crates":workers,"physical":physical,
            "events":len(events),"tasks":len(declared),"root_pid":root,"cargo_pid":actual_cargo}


def dependencies(z):
    graph=json.loads(z.read("unit-graph.json"));units=graph["units"]
    (root,)=graph["roots"];verify(units[root]["target"]["name"]=="ty_server" and units[root]["mode"]=="check","wrong check root")
    raw=json.loads(z.read("P/edited/rustcs.json"));result={}
    for row in raw:
        name=row["crate"];argv=row["argv"]
        (unit,)=[i for i,v in enumerate(units) if v["pkg_id"].startswith("path+file:") and v["target"]["name"]==name and v["mode"]=="check"]
        externs={argv[i+1].split("=",1)[0] for i,v in enumerate(argv[:-1]) if v=="--extern"}
        edges={e["extern_crate_name"] for e in units[unit]["dependencies"]}
        tracked={PROD,*DIRECT,"ty_python_semantic"};verify((externs&tracked)==(edges&tracked),"unit graph versus executed externs")
        if name!=PROD:
            verify((PROD in externs) == (name in DIRECT), "direct consumer classification")
        queue=deque([[unit]]);seen={unit}
        while queue:
            path=queue.popleft()
            if units[path[-1]]["target"]["name"]==PROD:break
            for edge in units[path[-1]]["dependencies"]:
                child=edge["index"]
                if child not in seen:
                    queue.append(path+[child]);seen.add(child)
        else:raise ValueError("unrelated compiled target "+name)
        result[name]={"shortest_to_producer":[units[i]["target"]["name"] for i in path], "executed_related_externs":sorted(externs&tracked)}
    return result


def compare(left,right):
    lh,ld,lr,le,lx=left;rh,rd,rr,re,rx=right
    verify(lh["stable"]==rh["stable"] and set(ld)==set(rd) and all(ld[k][0]==rd[k][0] for k in ld),"stable metadata definitions")
    common=lr.keys()&rr.keys()
    return {"public_changed":lh["public"]!=rh["public"], "private_changed":lh["private"]!=rh["private"],
            "reachable_old":len(lr),"reachable_new":len(rr),"changed":sum(lr[k]!=rr[k] for k in common),
            "lost":len(lr.keys()-rr.keys()),"added":len(rr.keys()-lr.keys())}


def witnesses(z,schema):
    version=json.loads(z.read("P/compiler.json"))["rustc_vV"].splitlines()[0]+" (Ohm metadata 3)"
    results={}
    for phase in ("old","edited","clean"):
        where="P/"+phase+"/"
        info=json.loads(z.read(where+"phase.json"))
        data=z.read(where+"witness-rmeta.tar.zst")
        verify(hashlib.sha256(data).hexdigest()==info["witness_archive_sha"],"archive digest")
        out=subprocess.run(["zstd","-q","-dc"],input=data,stdout=subprocess.PIPE,check=True).stdout
        found={}
        with tarfile.open(fileobj=io.BytesIO(out)) as archive:
            for member in archive:
                key=member.name.removesuffix(".rmeta")
                verify(member.isfile() and member.size < 64*2**20 and key in DIRECT|{PROD,"ty_server"} and key not in found,"foreign witness")
                raw=archive.extractfile(member).read()
                verify(hashlib.sha256(raw).hexdigest() in [v for n,v in info["workspace_rmeta"].items() if n.split("/")[0]==key],"native metadata digest")
                found[key]=rmeta.decode(raw,*schema,key,version)
        verify(set(found)==DIRECT|{PROD,"ty_server"},"missing metadata witnesses")
        results[phase]=found
    return {k:{"edit":compare(results["old"][k],results["edited"][k]), "empty":compare(results["edited"][k],results["clean"][k])} for k in sorted(results["old"])}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("zip",type=Path);parser.add_argument("sha256")
    parser.add_argument("rust_source",type=Path);parser.add_argument("out",type=Path)
    args=parser.parse_args()
    with args.zip.open("rb") as f: verify(hashlib.file_digest(f,"sha256").hexdigest()==args.sha256,"transport SHA mismatch")
    ref=json.loads((HERE.parent/"owner-reference.json").read_bytes())
    with zipfile.ZipFile(args.zip) as z:
        verify(len(z.namelist())==len(set(z.namelist())) and z.testzip() is None,"duplicate or corrupt archive")
        ids=json.loads(z.read("owner-inputs.json"));final=json.loads(z.read("ownership-complete.json"))
        verify(final["source"]==ref["p"] and ids["factory"]==41562405539 and final["head"]==ids["head"] and ids["boot"]==final["boot"],"wrong experiment")
        stages={s:json.loads(z.read("P/"+s+"/phase.json")) for s in PHASES}
        workspaces=[stages[p]["workspace_rmeta"] for p in ("edited","new-unchanged","repair","clean")]
        plain_ok=sorted(k for k,v in workspaces[0].items() if workspaces[-1][k]==v)
        verify(plain_ok==ref["empty_equal"] and len(workspaces[0])==31 and all(r==workspaces[0] for r in workspaces[:3])
               and stages["old"]["workspace_rmeta"]==stages["old-unchanged"]["workspace_rmeta"],"warm, repaired or empty rmeta")
        verify(all(stages[s]["diagnostics"]==[] for s in PHASES if s!="invalid") and stages["invalid"]["counts"]=={PROD:1}
               and any(r[:2]==["error","E0308"] for r in stages["invalid"]["diagnostics"]),"wrong compiler verdict")
        verify(stages["edited"]["counts"]==stages["repair"]["counts"]==dict.fromkeys(ref["argv"],1)
               and not stages["old-unchanged"]["counts"] and not stages["new-unchanged"]["counts"],"native control counts")
        ordinary=controls.ordinary(z,stages)
        verify(ordinary==json.loads((HERE/"ordinary-reference.json").read_bytes()),"ordinary 279-unit graph or 283-compiler empty roster changed")
        calibration=controls.calibrations(z)
        native_result={s:native(z,ref,"events-"+s,ids) for s in ("edited","new-unchanged")}
        if args.rust_source.is_dir():
            schema=rmeta.schema(args.rust_source)
        else:
            encoded=args.rust_source.read_bytes()
            verify(hashlib.sha256(encoded).hexdigest()=="7fa0044e649b14fc56746d44b6d824a747fe4d2be447d4550a32f86b0e1c65f9","wrong compiler schema")
            source=json.loads(encoded);verify(source["rust"]==ref["p"],"wrong schema source")
            schema=source["symbols"],source["tables"]
        rr=witnesses(z,schema)
        prior=json.loads((HERE/"definition-reference.json").read_bytes())
        verify(rr==prior,"different decoded definition changes from both ordinary parent runs")
        closure={"archive_sha256":args.sha256,"head":ids["head"],"boot":ids["boot"],"source":ref["p"],"hardware":native_result,
                 "empty_equals":plain_ok,"workspace_metadata":31,"definitions":rr,"ordinary_prior":ref["arms"],
                 "invalid":stages["invalid"]["diagnostics"],"repair_matches_edited":True,"calibration":calibration,"ordinary":ordinary,"unit_graph":dependencies(z)}
        args.out.write_text(json.dumps(closure,sort_keys=True,indent=2)+"\n")


if __name__=="__main__":
    main()
