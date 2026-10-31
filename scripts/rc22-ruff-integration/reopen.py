"""Reopen the raw typed and Darwin kernel streams, programs and the original .rlink operands."""
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("qualifier",HERE/"study.py")
q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)
need=q.need
def js(p):return json.loads(p.read_bytes())
def digest(b):return hashlib.sha256(b).hexdigest()
def blob(root,kind,key):
    need(len(key)==64 and all(c in "0123456789abcdef" for c in key),"bad object hash")
    p=(root/"cgu-inputs"/kind if kind else root/"markers")/(key+".gz")
    b=gzip.decompress(p.read_bytes());need(digest(b)==key,"corrupt object");return b
def verify_proof(root,out,row,ev,imgs,target,prior):
    import cgu_inputs as cg
    key=row["proofs"][target]["raw"]
    if (out/target/"original-link.json").exists():
        proof=js(out/target/"original-link.json")
        need(proof==prior[(target,key)],"no actual historic link for the exact returned image")
        return
    p=js(out/target/"cgu-proof.json")
    need(p["source"]=="kernel-xcode-ld+rustc-recipe" and p["raw"]==key,"wrong source of native body")
    links=[r["argv"] for r in ev if imgs.get(r["path"],{}).get("role")=="ld" and
           [b for a,b in zip(r["argv"],r["argv"][1:]) if a=="-o"]==[p["output"]]]
    need(len(links)==1 and p["linker_argv"]==digest(json.dumps(links[0],separators=(",",":")).encode()),"no unique native linker")
    version,parts=cg.modules(blob(root,"recipes",p["recipe"]))
    need(version==p["version"] and {v["object"] for v in parts}==set(p["physical"]),"incomplete physical recipe")
    owned=Path(p["output"]).with_suffix(".rlink-objects")
    need({w for w in links[0] if Path(w).parent==owned and w.endswith(".o")}==set(p["physical"]),"actual ld and recipe differ")
    modules={}
    for part in parts:
        path=part["object"];v=p["physical"][path];body=blob(root,"objects",v["sha256"])
        need(Path(path).parent==owned and part["name"]==v["module"] and v["bytes"]==len(body) and
             v["kind"]==part["kind"] and body[:8]==bytes.fromhex("cffaedfe0c000001") and int.from_bytes(body[12:16],"little")==1,"foreign root object")
        modules[part["name"]]=v["sha256"]
    need(modules==p["modules"]==row["proofs"][target]["modules"],"different root modules")
    body=subprocess.check_output(["zstd","-q","-dc",root/"images"/(key+".zst")])
    need(digest(body)==key,"changed whole native image")
    normal,checked=cg.canonical(body,p["output"],links[0],incremental=True,namespace=False)
    need(digest(normal)==p["same_path_image"]==row["proofs"][target]["same_path_image"] and
         checked["nonce_objects"]==p["nonce_objects"] and checked["code_pages"]==p["code_pages"] and
         all(v["path"] in p["physical"] for v in checked["nonce_objects"]),"unexpected Mach-O/debug/signature differences")
    prior[target,key]={k:p[k] for k in ("raw","recipe","linker_argv")}
def reopen(root,apple,marker):
    sys.path[:0]=[str(apple),str(marker)]
    import evidence
    aggregate={}; enrollment=js(root/"enrollment.json"); done=js(root/"complete.json")
    need(done["scored"] is False and enrollment["command"]==q.CLI and enrollment["trees"]==q.TREES and
         js(root/"calibration/complete.json")["program_exit"]==13,"unexpected study")
    for role in ("pinned","fourfix"):
        role_root=root/role;seen={};refs={};rows={}
        selector=js(role_root/"selector.json")
        need(selector["sha256"]==enrollment["cargos"][role]["sha256"],"incorrect active reader")
        for name,rev in (*q.STEPS,("empty-A",q.OLD),("empty-B",q.NEW)):
            if name.startswith("empty-"):seen={}
            out=role_root/name;row=js(out/"verified.json");units,outputs=q.read_units((out/"cargo.stdout").read_bytes())
            need(row["revision"]==rev,"incorrect historical phase")
            ev=json.loads(gzip.decompress((out/"es-execs.json.gz").read_bytes()));imgs=js(out/"images.json");native=js(out/"native.json")
            for path,img in imgs.items():
                if img["role"]=="cargo":need(img["sha256"]==selector["sha256"],"different native Cargo")
                if img["role"]=="rustc":need(any(v["sha256"]==img["sha256"] and Path(k).name=="rustc" for k,v in enrollment["fixed"].items()),"different rustc")
            need(all(ev[i]["seq"]<ev[i+1]["seq"] for i in range(len(ev)-1)),"kernel stream reordered")
            comp=[];rel=[];link=[];front=[];drivers=[]
            for e in ev:
                what=imgs.get(e["path"],{}).get("role");a=e["argv"]
                if what=="cargo":(drivers if Path(a[0]).name=="ohm-link-cc" else front).append(e)
                elif what=="rustc" and "--crate-name" in a:
                    crate=a[a.index("--crate-name")+1]
                    if crate=="___" and ("--print" in a or any(x.startswith("--print=") for x in a)):continue
                    (rel if any("link-only" in x for x in a) else comp).append(crate)
                elif what=="ld":link.append(e)
                else:need(Path(e["path"]).name not in {"ld","ld64","ld-classic","ld-prime","wild","rust-lld","ld64.lld","ld.lld","wild-ld"},"unclassified native linker")
            dirty=[(u["package_id"],u["target"]["name"],u["target"]["kind"]) for u in units if not u["fresh"]]
            need(len(front)==1 and sorted(comp)==native["full"] and sorted(rel)==native["link_only"] and sum(q.ld_output(x["argv"]) is not None for x in link)==native["stock_ld"] and
                 sum(q.ld_output(x["argv"]) is None for x in link)==native["stock_ld_queries"] and
                 len(drivers)==native["real_link_driver"] and native["typed"]==len(units) and native["fresh"]==len(units)-len(dirty) and
                 list(map(list,dirty))==native["dirty"],"typed counts or kernel process counts differ")
            flags=js(out/"markers.json");need(any("#zmij@1.0.10" in f["package"] for f in flags),"missing v1 producer")
            for f in flags:
                raw=evidence.raw_rule(Path(f["raw_path"]),blob(root,None,f["raw"]));x=evidence.encoded(blob(root,None,f["translated"]))
                want=evidence.V1 if "#zmij@" in f["package"] else evidence.V2
                expected=None if role=="pinned" and want==evidence.V1 else want
                need(raw==f["rules"]==[want] and x["LNK1"]==f["LNK1"]==expected and x["markers"]==f["markers"],"different native marker")
            for k in outputs:verify_proof(root,out,row,ev,imgs,k,seen)
            need(sorted(k for k in outputs if (out/k/"cgu-proof.json").exists())==native["terminals"],"wrong terminal linker attribution")
            fixtures=out/"behavior"
            actual=[row["cli"][0],*( (fixtures/(n+".raw")).read_bytes().hex() for n in ("stdout","stderr","sentinel"))]
            need(actual==row["cli"] and row["cli"][0]==int(rev==q.NEW) and
                 sorted(n[:-6] for n in (out/"list.txt").read_text().splitlines() if n.endswith(": test"))==row["tests"] and
                 b"1 passed; 0 failed" in (out/"test.txt").read_bytes(),"changed CLI or libtest outcomes")
            if name.startswith("empty-"):refs[rev]=row
            else:rows[name]=row
        need(q.hashes_by_revision(rows,refs)==js(role_root/"clean-comparisons.json"),"different mandatory clean verdict")
        aggregate[role]={n:r["native"] for n,r in rows.items()}
    need(aggregate==done["native"],"summary differs from independent raw counts")
    return {"scope":"unscored real Ruff release-reader control","visits":16,"native":aggregate}
if __name__=="__main__":
    result=reopen(*(Path(p) for p in sys.argv[1:4]))
    q.save(Path(sys.argv[4]),result)
