"""Independently verify one downloaded original and reopen its native sources, outputs and counters."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from readout import counted, mapping, need, owner

REG=json.loads((HERE/"registration.json").read_bytes())
BIND=json.loads((HERE/"factory.json").read_bytes())
A,B=REG["source"]["A"],REG["source"]["B"]
SHA=lambda buf:hashlib.sha256(buf).hexdigest()


def load(path):return json.loads(path.read_bytes())


def extract(original,dest):
    with zipfile.ZipFile(original)as z:
        infos=z.infolist();need(len({i.filename for i in infos})==len(infos) and sum(i.file_size for i in infos)<2*(1<<30),"zip roster or size")
        for i in infos:
            name=i.filename;path=Path(name);need(not path.is_absolute() and ".." not in path.parts and len(name)<=500 and i.file_size<=250<<20,"unsafe member")
            if i.is_dir():continue
            target=dest/path;target.parent.mkdir(parents=True,exist_ok=True)
            with target.open("xb")as out:out.write(z.read(i))


def inputs(root):
    worker=load(root/"worker.json");meta=load(root/"scope-sdks.json");src=load(root/"source-inputs.json")
    need(worker["registration"]==REG and worker["factory"]==BIND and worker["boot"] and len(set(worker["cpus"]))==4 and worker["runner_id"]>0 and worker["job"]>0,"worker/source registration")
    need(set(src)=={A,B} and all(src[rev]["tree"]==REG["trees"][rev] for rev in (A,B)),"source tree")
    objects=root/"objects"
    for f in objects.iterdir():need(f.is_file() and SHA(f.read_bytes())==f.name,"changed or injected source/output object")
    for rev in (A,B):
        for name,row in src[rev]["files"].items():
            data=(objects/row["sha256"]).read_bytes()
            need(hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()==row["git"],"source blob identity")
        need(src[rev]["files"]["Cargo.lock"]["sha256"]==REG["source"]["lock_sha256"] and src[rev]["files"]["crates/ty_vendored/build.rs"]["sha256"]==REG["source"]["generator_source"],"source/lock bytes")
    lock=tomllib.loads((objects/REG["source"]["lock_sha256"]).read_text())
    locked={r["name"]+"-"+r["version"]+".crate":r["checksum"]for r in lock["package"]if r.get("source")=="registry+https://github.com/rust-lang/crates.io-index"}
    need(len(locked)==505 and locked==load(root/"registry.json"),"physical registry inventory")
    need([meta["inline-"+r]["source"] for r in "PC"]==[BIND["source"][r]for r in "PC"] and meta["inline-P"]["driver"]!=meta["inline-C"]["driver"] and meta["inline-P"]["cargo"]==meta["inline-C"]["cargo"],"matched physical compiler")
    return worker,meta


def verify_zip(raw,truth):
    packed=gzip.decompress((HERE/"members.json.gz").read_bytes());need(SHA(packed)==REG["member_map_sha"],"reference members")
    exp=json.loads(packed);expected=dict(exp["rows"])
    if truth=="new":expected.update(exp["edit"])
    with zipfile.ZipFile(io.BytesIO(raw))as z:
        need(len(z.infolist())==len(expected)==819 and set(z.namelist())==set(expected),"archive member set")
        for i in z.infolist():
            data=z.read(i);need(dict(bytes=len(data),crc=i.CRC,method=i.compress_type,sha256=SHA(data))==expected[i.filename],"actual stubs differ")


def hw(stage):
    h=load(stage/"hardware.json");need(h["status"]==0 and h["pid"]>0 and h["instructions"]>0 and h["enabled"]==h["running"]>0,"incomplete hardware input")
    need(load(stage/"command.json")["exit"]==0,"failed measured command")
    return h["instructions"]


def activity(stage):
    return sorted((m[1],m[2])for line in (stage/"stderr").read_text().splitlines()if (m:=re.match(r"^\s*(Checking|Compiling)\s+([^ ]+)",line)))


def metrics(stage,identity,name,argv,required,repo):
    logs=stage.with_suffix(".epochs"); obs=owner(logs,identity,name,repo)
    need(obs==load(stage/"physical.json"),"physical rows differ on independent replay")
    ims,_,_=counted(logs);procs=[im["argv"] for im in ims.values() if im["trigger"]=="exec" and [im["dev"],im["ino"]]==identity["cargo_inode"]]
    need(len(procs)==1 and procs[0][1:]==argv[2:] and len(obs["owner"])==required and (required or not obs["compilers"]),"Cargo image or untouched owner")
    raw=obs["owner"];row=raw[0] if raw else {}
    return dict(summed=obs["total"],owner=row.get("instructions",0),unit_args=row.get("argv",[]),compiler_names=obs["compilers"],build_scripts=obs["build_scripts"])


def complete(root):
    worker,meta=inputs(root);objects=root/"objects";cache={};zips={"old":set(),"new":set()};all_results=[]
    def physical(stage,state,parser=False):
        row=load(stage/"products.json"); m=row["metadata"];body=(objects/m["sha256"]).read_bytes()
        need(len(body)==m["bytes"] and all((objects/d["sha256"]).is_file()for d in row["dep_info"]),"missing original metadata or dep-info")
        if not parser:
            z=row["archive"];raw=(objects/z["sha256"]).read_bytes();need(len(raw)==z["bytes"] and body.count(raw)==1,"recorded rustc output does not contain registered entire data")
            need(any(any(name.encode()in(objects[d["sha256"]]).read_bytes()for name in z["paths"])for d in row["dep_info"]),"input dep-info archive")
            if(z["sha256"],state)not in cache:verify_zip(raw,state);cache[z["sha256"],state]=True
            zips[state].add(z["sha256"])
        return m["sha256"]
    cal=load(root/"calibration/closed.json")
    for variant in ("thread","child"):
        for level in (0,1):
            stage=root/"calibration"/(variant+str(level)); h=hw(stage.with_name(stage.name+"-whole"))
            ims,cnts,_=counted(stage.with_suffix(".epochs")); per=sum(x[0]for i,x in cnts.items()if i!=1)
            need([h,per]==cal[stage.name],"calibration source")
        need(all(x>y+10_000_000 for x,y in zip(cal[variant+"1"],cal[variant+"0"])),"calibrated thread or child missing")
    need(load(root/"complete.json")["order"]==REG["order"] and not (root/"refused.txt").exists(),"incomplete hosted study")
    for i,role in enumerate(REG["order"],1):
        base=root/f"visit-{i}-{role}";ident=load(base/"identity.json");binding=meta["inline-"+role]
        need(ident["source"]==binding["source"] and all(ident[k]==binding[k]for k in ("rustc","driver","cargo")),"selected wrong real compiler")
        observed=load(base/"mapping/verified.json");row=ident["mapped_driver_row"].split(None,5)
        need(row[5]==ident["driver_path"] and int(row[4])==ident["mapped_driver_inode"][1],"different enrolled map")
        need(mapping(base/"mapping.epochs"/f"{observed['image']:05}.maps",ident)==observed["rows"],"separate actual compiler calibration")
        cargo=load(base/"whole/edit/command.json")["argv"];need(cargo[3:]==REG["target"],"changed metered whole command")
        # The compiler argv and original command/stat records disclose the hosted Ruff pathname.
        root_hint=next((p for p in load(root/"source-inputs.json")[A]["files"] if p=="crates/ty_vendored/src/lib.rs"),None);need(root_hint,"source registration")
        # Since each commands' CWD is the independently enrolled workspace checkout, recover it
        # from the actual historical checked package on Cargo's ordinary stdout/stderr.
        ms=re.findall(r"(?m)^\s*(?:Checking|Compiling) ty_vendored [^\n]*?\(([^)]+/crates/ty_vendored)\)",(base/"exec/cold/stderr").read_text())
        need(len(ms)==1,"genuine package not found in Cargo human output");repo=Path(ms[0]).parent.parent
        prices={};delivered={"old":[],"new":[]}
        for name,state,dirty in (("cold","old",1),("old-idle","old",0),("edit","new",1),("new-idle","new",0)):
            first,second=base/"whole"/name,base/"exec"/name;need(activity(first)==activity(second),"whole vs traced dirty Cargo package roster")
            val=metrics(second,ident,"ty_vendored",REG["target"],dirty,repo); val["whole"]=hw(first);prices[name]=val
            if name=="edit":need(any("ty_vendored" in r["exe"].replace("-","_") and r["instructions"]>0 for r in val["build_scripts"]),"physical trusted generator did not execute on the genuine changed source")
            if not dirty:need(not val["build_scripts"],"unchanged source reran a native build script")
            for d in (first,second):delivered[state].append(physical(d,state))
        for name in ("fresh","repair"):delivered["new"].append(physical(base/"safety"/name,"new"))
        failures=[json.loads(l) for l in (base/"safety/E0308/stdout").read_bytes().splitlines()]
        err=[r["message"]for r in failures if r["reason"]=="compiler-message" and r["message"]["level"]=="error"]
        need([r["code"]["code"]for r in err]==["E0308"] and any(s["is_primary"]and s["file_name"].endswith("crates/ty_vendored/src/lib.rs") and any("OHM_FROZEN_LITERAL_INVALID"in v["text"]for v in s["text"])for s in err[0]["spans"]) and [r["success"]for r in failures if r["reason"]=="build-finished"]==[False],"stale or changed failure")
        need(all(len(set(v))==1 for v in delivered.values()) and delivered["new"][0]!=delivered["old"][0],"edited/fresh/repaired full package metadata")
        one,two=base/"parser-whole",base/"parser-exec";need(activity(one)==activity(two) and physical(one,"new",True)==physical(two,"new",True),"parser source/output or dirtiness")
        prices["parser"]=metrics(two,ident,"ruff_python_parser",REG["common_symbol_guard"],1,repo)|dict(whole=hw(one))
        native_data={}
        if i in (1,2):
            for name,state in (("old","old"),("edit","new"),("fresh","new")):
                d=base/"native"/name;r=load(d/"products.json");body=(objects/r["elf"]).read_bytes();raw=(objects/r["archive"]["sha256"]).read_bytes()
                need(body.startswith(b"\x7fELF") and len(body)==r["bytes"] and body.count(raw)>=1 and r["archive"]["sha256"]in zips[state] and (d/"run/stdout").read_text().split()==r["text"]==list(map(str,REG["source"]["required_source_commit_and_doc_count"][state])),"incorrect real linked ZIP/verdict")
                rows=[json.loads(line)for line in (d/"cargo/stdout").read_bytes().splitlines()]
                need([r["success"]for r in rows if r["reason"]=="build-finished"]==[True] and all(any(r["reason"]=="compiler-artifact" and r["target"]["name"]==k and v["path"]in r["filenames"]for r in rows)for k,v in r["extern"].items()),"wrong native Cargo dependency")
                native_data[name]=r["elf"]
            need(native_data["edit"]==native_data["fresh"]!=native_data["old"],"native edited and independent fresh executable differ")
        all_results.append(dict(visit=i,role=role,prices=prices,native=native_data,metadata={s:v[0]for s,v in delivered.items()}))
    need(len(zips["old"])==len(zips["new"])==1 and zips["old"]!=zips["new"],"different physical ZIPs between matched arms")
    comparisons=[];rules=REG["pilot_gates"]
    for pair in (all_results[:2],all_results[2:]):
        par,can=sorted(pair,key=lambda a:a["role"],reverse=True);need([par["role"],can["role"]]==["P","C"],"unordered visit pair")
        deltas={};gates={}
        for k in par["prices"]:
            l,r=par["prices"][k],can["prices"][k]
            need(l["compiler_names"]==r["compiler_names"] and l["unit_args"]==r["unit_args"],"different actual named compiler argv or roster: "+k)
            deltas[k]={m:1-r[m]/l[m]for m in ("owner","whole","summed") if l[m]>0}
        gates["owner"]=deltas["edit"]["owner"]>=rules["both_owner_edit_reduction_min"]
        gates["whole"]=deltas["edit"]["whole"]>=-rules["both_whole_edit_max_regression"]
        gates["parser"]=all(deltas["parser"][k]>=-rules["parser_owner_and_whole_max_regression"]for k in ("owner","whole"))
        gates["independent_clock"]=all(abs(v["prices"]["edit"]["whole"]-v["prices"]["edit"]["summed"])/min(v["prices"]["edit"]["whole"],v["prices"]["edit"]["summed"])<=rules["edit_independent_whole_counts_relative_to_smaller_max"] for v in pair)
        comparisons.append(dict(order="".join(x["role"]for x in pair),reductions=deltas,gates=gates))
    return dict(worker=worker,inputs=BIND,zip={k:sorted(v)for k,v in zips.items()},visits=all_results,comparisons=comparisons,eligible_for_fresh_confirmation=all(all(x["gates"].values())for x in comparisons),scope="Single-boot independent ordinary histories, exploratory hardware prices.")


def main():
    archive=Path(sys.argv[1]);digest=sys.argv[2];out=Path(sys.argv[3])
    need(SHA(archive.read_bytes())==digest,"original ZIP digest")
    with tempfile.TemporaryDirectory(prefix="frozen-literal-reader-",dir=out.parent)as t:
        root=Path(t);extract(archive,root);r=complete(root)
    out.write_text(json.dumps(r|dict(original_sha256=digest,original_bytes=archive.stat().st_size),indent=2,sort_keys=True)+"\n")


if __name__=="__main__":main()
