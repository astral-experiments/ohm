"""Reopen each full Cargo-returned image, native linker, metadata reader and test verdict."""
import argparse
import collections
import functools
import gzip
import json
from pathlib import Path
import sys
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reopen_cgu
from study import digest, need, save
from ty_links import A, B, ERROR, EXISTING, NEW
from verbs import macho_text
from workspace_images import CHUNK, Image, compare

ROOT = "ty-comparison/workspace"
EXPECTED_MATH = b"3ff6a09e667f3bcd 3fb504f3 4000000000000000 40800000 401a000000000000 40d00000\n"
OLD_PROGRAM = reopen_cgu.program
VISITS = (("cold", "old"), ("edit", "new"), ("repeat-1", "new"), ("repeat-2", "new"),
          ("invalid", "bad"), ("repair", "new"))

def logical_path(value):
    for old,new in (("/private/var/", "/var/"), ("/private/tmp/", "/tmp/")):
        if value.startswith(old):return new+value[len(old):]
    return value

class Corpus:
    def __init__(self, source):
        self.directory=source if isinstance(source,Path) and source.is_dir() else None
        self.zip=None if self.directory else ZipFile(source)
        paths=[str(p.relative_to(source)) for p in source.rglob("*") if p.is_file()] if self.directory else [e.filename for e in self.zip.infolist() if not e.is_dir()]
        need(len(paths)==len(set(paths)) and all(not n.startswith("/") and ".." not in Path(n).parts for n in paths),"duplicate or foreign artifact path")
        self.names=set(paths)
        self.proofs=sorted(n.rsplit("/",1)[0] for n in paths if n.endswith("/cgu-proof.json"))
        self.aliases={p+"/exec.json.gz":p.split("/workspace-image-proofs/",1)[0]+"/exec.json.gz"
                      for p in self.proofs if "/workspace-image-proofs/" in p}
        need(not(self.names & self.aliases.keys()) and all(v in self.names for v in self.aliases.values()),"missing original phase execution log")
        self.inventory=self.names|self.aliases.keys()
    def namelist(self):return self.inventory
    def read(self,name):
        name=self.aliases.get(name,name)
        if name not in self.names:raise KeyError(name)
        return (self.directory/name).read_bytes() if self.directory else self.zip.read(name)
    def json(self,name):return json.loads(self.read(name))
    def packed(self,name):return gzip.decompress(self.read(name))
    def close(self):
        if self.zip:self.zip.close()

@functools.lru_cache(maxsize=2)
def raw_image(corpus, key):
    filename="workspace-returned-images/images/"+key+".json"
    if filename not in corpus.names:return OLD_PROGRAM(corpus,key)
    rec=corpus.json(filename);need(rec["raw"]==key and rec["chunks"],"wrong enrolled image manifest")
    body=bytearray()
    for i,(h,length) in enumerate(rec["chunks"]):
        chunk=corpus.packed("workspace-returned-images/chunks/"+h[:2]+"/"+h+".gz")
        need(len(chunk)==length and digest(chunk)==h and 0<length<=CHUNK and
             (i==len(rec["chunks"])-1 or length==CHUNK),"wrong archived physical chunk")
        body.extend(chunk)
    data=bytes(body)
    need(len(data)==rec["bytes"] and macho_text(Image(data))=={"raw":key,"text":rec["text"]},"complete returned image, size or ARM64 text changed")
    return data

def bundle(corpus,kind,key):
    data=corpus.packed("cgu-inputs/"+kind+"/"+key+".gz")
    need(digest(data)==key,"different "+kind)
    return data

def math(c, phase, typed, row):
    artifacts=[t for t in typed if t["target"]["name"]=="libm" and t["target"]["kind"]==["lib"]]
    need(len(artifacts)==len(row["libm"])>0,"missing typed math registry units")
    for idx,(art,receipt) in enumerate(zip(artifacts,row["libm"])):
        where=phase+"/math-"+str(idx)
        q=c.json(where+"/verified.json")
        paths=[x for x in art["filenames"] if x.endswith((".rlib",".rmeta"))]
        need(len(paths)==2 and paths==list(dict.fromkeys(paths)) and "libm@0.2.16" in art["package_id"],"foreign math package")
        typed_by_ext={Path(p).suffix:p for p in paths}
        ext=[v.removeprefix("libm=") for k,v in zip(q["argv"],q["argv"][1:]) if k=="--extern"]
        need(set(ext)==set(paths) and len(ext)==2 and receipt["path"]==typed_by_ext[".rlib"] and receipt["sha256"]==q["archive"],"reader did not receive both actual Cargo outputs")
        library=bundle(c,"libm-rlibs",q["archive"]);meta=bundle(c,"libm-metadata",q["metadata"])
        need(library.startswith(b"!<arch>\n") and meta.startswith(b"rust") and len(meta)>1024,"empty or foreign full libm")
        for variant,code in (("real",0),("corrupt",1)):
            vr=q["metadata_tests"][variant];argv=vr["argv"];actual=[v for k,v in zip(argv,argv[1:]) if k=="--extern"]
            target=typed_by_ext[".rmeta"]
            need(len(actual)==1 and (actual[0]=="libm="+target if code==0 else "/bad-metadata/"+Path(target).name in actual[0]),"metadata-only reader used the wrong input")
            need("--emit=metadata" in argv and vr["exit"]==code and vr["file"]==(q["metadata"] if not code else digest(b"not rustc metadata\n")),"metadata control changed")
            diagnostics=c.packed(where+"/"+variant+"-metadata.stderr.gz")
            found=[(v.get("code") or {}).get("code") for v in map(json.loads,diagnostics.splitlines())]
            need(found==vr["diagnostics"] and (not code or any(d in ("E0463","E0786") for d in found) and b"libm" in diagnostics),"corrupt metadata did not have its original diagnostic")
        program=bundle(c,"libm-math-programs",q["stored_program"])
        need(macho_text(Image(program))==q["program"] and q["exit"]==0 and q["stdout"].encode()==EXPECTED_MATH==c.packed(where+"/run.stdout.gz") and not c.packed(where+"/run.stderr.gz"),"wrong native math result")
    return len(artifacts)

def compare_phase(c, phase, state, role, history, bodies, proofs):
    q=c.json(phase+"/verified.json")
    need(q["state"]==state and q["scores"]==0 and q["argv"]==["cargo","+ohm","test","--workspace","--no-run","--locked","--offline","-j4","--message-format=json"],"different developer command")
    raw={k:c.packed(phase+"/"+n+".gz") for k,n in (("stdout","stdout"),("stderr","stderr"),("native_events","exec.json"))}
    need(q["streams"]=={k:digest(v) for k,v in raw.items()},"physical streams differ")
    rows=[json.loads(l) for l in raw["stdout"].splitlines()]
    valid=state!="bad"
    need(rows[-1]=={"reason":"build-finished","success":valid} and q["exit"]==(0 if valid else 101),"wrong Cargo result")
    events=json.loads(raw["native_events"])
    typed=[r for r in rows if r["reason"]=="compiler-artifact"]
    if not valid:
        need(q["e2e"] is None and any((r.get("message",{}).get("code") or {}).get("code")=="E0425" for r in rows) and ERROR.encode() in raw["stdout"],"invalid source did not fail correctly")
        return {},None,0
    by_path={logical_path(k):(k,v) for k,v in q["binary_roster"].items()}
    returned=[r for r in typed if r["executable"] and r["profile"]["test"]]
    need(len(returned)==len(q["binary_roster"])==len(by_path)==83,"wrong workspace size")
    links=collections.defaultdict(list)
    for e in events:
        if Path(e["path"]).name in ("ld","ld64","ld-prime","ld-classic"):
            links[logical_path(reopen_cgu.link_output(e["argv"]))].append(e)
    roster={}
    for r in returned:
        path=logical_path(r["executable"]);recorded,b=by_path[path];unit=(r["package_id"],r["target"]["name"],tuple(r["target"]["kind"]))
        need(unit not in roster and (b["unit"][0],b["unit"][1],tuple(b["unit"][2]))==unit and b["features"]==r["features"] and b["profile"]==r["profile"],"typed workspace output identity differs")
        p=b["proof"];key=p["raw"]
        need(key==b["sha"] and b["bytes"]==p["length"] and (key,p["length"],tuple(p["text"])) in bodies and len(links[path])==b["links"],"physical binary or Xcode link count differs")
        here=phase+"/workspace-image-proofs/"+digest(json.dumps(unit,separators=(",",":")).encode())
        if links[path]:
            need(len(links[path])==1 and p["current_link"] and p["link_origin"]==here,"unwitnessed or ambiguous fresh test program")
            event,=links[path];link=c.json(here+"/link.json");argv=event["argv"]
            need(event["pid"]==link["pid"] and event["seq"]==link["seq"] and event["cdhash"]==link["cdhash"] and
                 event["path"]==link["path"] and link["output"]==reopen_cgu.link_output(argv) and link["argv_sha256"]==digest(json.dumps(argv,separators=(",",":")).encode()) and link==p["physical"],"kernel Xcode linker did not emit this program")
            if p.get("error"):
                need(c.json(here+"/unsupported.json")["raw"]==key,"dropped unqualified root")
            else:
                native=proofs[here];detail=c.json(here+"/cgu-proof.json")
                need(native["raw"]==key and detail["source"]=="kernel-xcode-ld+rustc-recipe"
                     and detail["same_path_image"]==p["own_image"] and detail["cross_path_image"]==p["cross_image"] and detail["output"]==p["output"]
                     and digest(json.dumps(detail["modules"],sort_keys=True,separators=(",",":")).encode())==p["modules"]
                     and digest(json.dumps(detail["debug_paths"],separators=(",",":")).encode())==p["debug_paths"],"root linker native equivalence certificate differs")
            history[(unit,path,key)]=p
        else:
            old=history.get((unit,path,key));v=c.json(here+"/prior.json") if old else None
            if old:
                need(not p["current_link"] and p=={**old,"current_link":False} and v=={"raw":key,"output":recorded,"own_link_origin":old["link_origin"]},"cross-install or stale returned binary")
            else:
                need(p["link_origin"] is None and p.get("error"),"unwitnessed kernel linker attributed to a returned binary")
        roster[unit]=b
    inv=c.packed(phase+"/list-stdout.gz").decode().splitlines()
    need(all(x.endswith(": test") for x in inv) and sorted(x[:-6] for x in inv)==q["e2e"]["inventory"] and EXISTING in q["e2e"]["inventory"] and (NEW in q["e2e"]["inventory"])==(state=="new"),"changed e2e catalog")
    for name in [EXISTING]+([NEW] if state=="new" else []):
        prefix=phase+"/"+name.rsplit("::",1)[1]
        evidence=c.packed(prefix+"-stdout.gz")
        need(c.json(prefix+"-exit.json")==0 and ("test "+name+" ... ok").encode() in evidence and b"1 passed; 0 failed" in evidence,"changed native e2e verdict")
    reads=math(c,phase,typed,q) if q["label"] in ("cold","edit","clean","repair") else 0
    if q["label"] in ("cold","edit","clean"):
        emit=c.json(phase+"/development-emitters.json")
        need(set(e["crate"] for e in emit)=={"e2e","ty_server"},"missing ordinary incremental local compiler")
        for e in emit:
            actual=[v for v in events if v["pid"]==e["pid"] and v["path"]==e["path"] and v["argv"]==e["argv"]]
            need(len(actual)==1 and any(v=="incremental="+e["directory"] or v=="-Cincremental="+e["directory"] for v in e["argv"]) and e["sessions"] and all(s["graph_bytes"] and s["objects"] and len(s["work_products"])==64 for s in e["sessions"]),"physical local incremental command or generation changed")
    return roster,q["e2e"],reads

def providers(c, proofs):
    from cgu_inputs import agrees
    from fixed_crc import INPLACE
    from provider_edges import mach, NATIVE, NO_RUST, STEPS
    count=0;outside=[];certs=0
    for name in sorted(x for x in c.names if x.startswith("provider-matrix/") and x.endswith("/inputs.json")):
        base=name.rsplit("/",1)[0];schema=c.json(name);last={"warm":{},"empty":{}}
        label=base.rsplit("/",1)[1];stamp=label.split("-")[0].endswith("stamp")
        design=INPLACE if stamp else STEPS
        need(schema["steps"]==[list(i) for i in design],"provider registration changed")
        for point,state,rust in design:
            value=(17 if state=="overwrite" else 29) if stamp else NATIVE[state]
            expected=[0,[value,rust]] if value is not None else [101,None]
            observed={};physical={}
            for kind in ("warm","empty"):
                phase=base+"/"+point+"/"+kind;row=c.json(phase+"/verified.json");count+=1
                streams={k:c.packed(phase+"/"+n+".gz") for k,n in (("stdout","stdout"),("stderr","stderr"),("native_events","exec.json"))}
                need({k:digest(v) for k,v in streams.items()}==row["streams"],"provider stream changed")
                cargo=[json.loads(a) for a in streams["stdout"].splitlines()]
                valid=row["status"]==0;need(cargo[-1]=={"reason":"build-finished","success":valid},"wrong provider Cargo verdict")
                if valid:
                    image=row["image"];key=image["raw"];body=OLD_PROGRAM(c,key)
                    need(mach(body)==image and c.json(phase+"/program.json")=={"exit":0,"path":row["returned"],"sha256":key} and
                         not c.packed(phase+"/program.stderr.gz") and list(map(int,c.packed(phase+"/program.stdout.gz").split()))==row["answer"],"wrong external native result")
                    if schema["defaults"]:
                        if row["final_links"]:
                            saved=c.json(phase+"/cgu-proof.json");need(proofs[phase]["raw"]==key,"provider CGU for different image")
                            physical[kind]=saved
                            last[kind][key]=saved
                        else:
                            saved=last[kind].get(key);need(kind=="warm" and saved is not None and
                                c.json(phase+"/prior-cgu-proof.json")=={"raw":key,"recipe":saved["recipe"],"observed_link":saved["linker_argv"]},"unwitnessed no-link provider")
                            physical[kind]=saved
                        certs+=1
                    for final in row["final_links"]:
                        ev=reopen_cgu.observed_ld(c,phase,argv_sha=final["argv_sha"],output=final["output"],pid=final["pid"])
                        need(ev["cdhash"]==final["cdhash"] and "-lqa_owned_external" in ev["argv"],"different actual native provider linker")
                else:
                    key=None
                    need(row["status"]==101 and row["answer"] is None and any(t in streams["stdout"]+streams["stderr"] for t in (b"qa_owned_external",b"qa_value")),"wrong provider diagnostic")
                observed[kind]=[row["status"],row["answer"],key]
            prior=c.json(base+"/"+point+"/compared.json")
            need(observed=={k:prior[k] for k in ("warm","empty")} and observed["empty"][:2]==expected,"wrong original provider control")
            equivalent=(observed["warm"][2]==observed["empty"][2]) if all(v[2] for v in observed.values()) else None
            if len(physical)==2:equivalent=agrees(physical["warm"],physical["empty"])
            need(equivalent==prior["same_checked_image"],"wrong adjudicated provider bytes")
            if stamp or schema["defaults"] or schema["watch"]=="declared" or point not in NO_RUST:
                need(observed["warm"][:2]==expected and equivalent is not False,"required provider regression")
            elif observed["warm"][:2]!=expected:outside.append([label,point,observed["warm"][:2],expected])
    original=c.json("provider-matrix/terminal.json");need(count==392 and sorted(outside)==sorted(original["off_unwatched_comparisons"]),"different 392-case scope")
    return {"commands":count,"optional_off_unwatched":len(outside),"physically_bound_default_returns":certs}

def verify_all(c):
    reg=c.json("libm-registration.json");need(reg["ruff"]==[A,B] and not reg["timed"],"different registered edit")
    provider=c.json("provider-matrix/terminal.json");need(provider["passed"] and provider["commands"]==392 and not any(provider["wrong_or_image_mismatch"].values()),"provider certification failed")
    reopen_cgu.program=raw_image
    bodies=set()
    for name in sorted(c.names):
        if name.startswith("workspace-returned-images/images/") and name.endswith(".json"):
            row=c.json(name);raw_image(c,row["raw"]);bodies.add((row["raw"],row["bytes"],tuple(row["text"])))
    need(bodies,"no whole workspace images")
    proofs={name:reopen_cgu.verify(c,name) for name in c.proofs}
    provider_rows=providers(c,proofs)
    seen={};math_count=0;statuses={};failures=0
    for role in "PC":
        phases={}
        for sequence,visits in (("empty-old",[("clean","old")]),("visit",VISITS),("empty-new",[("clean","new")])):
            history={}
            for label,state in visits:
                key="clean-old" if sequence=="empty-old" else label
                prefix=f"{ROOT}/{role}/{sequence}/{label}"
                programs,e2e,count=compare_phase(c,prefix,state,role,history,bodies,proofs);math_count+=count
                if state!="bad":phases[key]=(state,programs,e2e)
        seen[role]=phases
        for key,(state,arm,e2e) in phases.items():
            _,ref,ref_e2e=phases["clean-old" if state=="old" else "clean"]
            need(arm.keys()==ref.keys() and e2e["inventory"]==ref_e2e["inventory"] and e2e["text"]==ref_e2e["text"],"wrong full clean inventory")
            rows=c.json(f"{ROOT}/{role}/all-images-{key}.json");need(len(rows)==83,"incomplete every-program comparison")
            scores=[]
            for row in rows:
                u=(row["unit"][0],row["unit"][1],tuple(row["unit"][2]));a,b=arm[u],ref[u];s=compare(a["proof"],b["proof"])
                need(a["sha"]==row["actual"] and b["sha"]==row["empty"] and row["status"]==s,"program clean comparison disagrees")
                scores.append(s)
            failures+=sum(v not in ("exact","authenticated-local-names") for v in scores)
            statuses[role+"/"+key]=dict(collections.Counter(scores))
    for key in ("clean-old","clean"):
        state="old" if key=="clean-old" else "new"
        rows=c.json(f"{ROOT}/all-clean-across-{state}.json");need(len(rows)==83,"incomplete clean cross-compiler census")
        for row in rows:
            u=(row["unit"][0],row["unit"][1],tuple(row["unit"][2]));a,b=[seen[r][key][1][u] for r in "PC"]
            s=compare(a["proof"],b["proof"],cross=True)
            need(row["status"]==s and row["parent"]==a["sha"] and row["child"]==b["sha"],"wrong cross-compiler physical comparison")
            failures+=s not in ("exact","authenticated-cross-compiler")
    terminal=c.json("libm-workspace-qualification.json")
    need(math_count>0 and terminal["safe"]==(failures==0) and not terminal["timed"],"application and independent qualification verdict disagree")
    return {"pins":reg,"providers":provider_rows,"workspace_comparisons":83*(7*2+2),
            "successful_workspaces":14,"invalid_workspaces":2,"distinct_whole_workspace_programs":len(bodies),
            "distinct_workspace_bytes":sum(x[1] for x in bodies),"physical_witnesses":len(proofs),
            "physical_root_objects_reopened":sum(v["objects"] for v in proofs.values()),"real_math_readers":math_count,
            "unqualified_comparisons":failures,"by_role_phase":statuses,"safe":not failures,"timed":False}

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("source",type=Path);p.add_argument("--output",type=Path)
    ns=p.parse_args();corpus=Corpus(ns.source)
    try:result=verify_all(corpus)
    finally:corpus.close()
    destination=ns.output or (ns.source/"libm-reopened.json" if ns.source.is_dir() else None)
    if destination:save(destination,result)
    print(json.dumps(result,sort_keys=True),flush=True)
    need(result["safe"],"the physical readback retains unqualified native programs")
