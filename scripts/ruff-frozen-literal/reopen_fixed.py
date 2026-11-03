"""Replay original fixed-input artifacts and all complete kernel counters."""
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import read as old
import tree_clock as t
sys.path.insert(0,str(HERE.parent/"ruff-module-16149"))
import scope_rdr

reg=old.REG;factory=old.BIND;protocol=old.load(HERE/"inherited-registration.json")
need=old.need


def run(root):
    worker,registry=old.inputs(root);obj=root/"objects"
    need(old.load(root/"inherited-enrollment.json")==protocol and old.load(root/"complete.json")["protocol"]==protocol and not (root/"refused.txt").exists(),"incomplete fixed-input registration")
    schemas=json.loads(gzip.decompress((HERE.parent/"ruff-module-16149/schema.json.gz").read_bytes()))
    archives={"old":set(),"new":set()};decoded={};visits=[];stats={};sigs={};native={};fixed=[]
    def state(d,which,parser=False):
        r=old.load(d/"products.json");m=r["metadata"];raw=(obj/m["sha256"]).read_bytes()
        need(m["bytes"]==len(raw) and all((obj/f["sha256"]).is_file()for f in r["dep_info"]),"root rmeta/dep-info")
        if not parser:
            z=r["archive"];body=(obj/z["sha256"]).read_bytes()
            if z["sha256"]not in archives[which]:old.verify_zip(body,which)
            need(len(body)==z["bytes"] and raw.count(body)==1 and any(any(v.encode()in(obj/f["sha256"]).read_bytes()for v in z["paths"])for f in r["dep_info"]),"actual embedded source and dependency")
            archives[which].add(z["sha256"])
        return m["sha256"]
    def clock(d,mode,identity,crate,cmd,has_owner,cargo=True):
        actual,ims=t.decode(d.with_suffix(".epochs"),mode,identity,crate);saved=old.load(d/"physical.json")
        need(all(saved[k]==v for k,v in actual.items()) and actual["status"]==0 and bool(actual["owner"])==has_owner,"kernel/copy or owner mismatch")
        if cargo:
            q=[x for x in ims.values()if x["trigger"]=="exec" and x["ino"]==identity["cargo_inode"]]
            need(len(q)==1 and q[0]["argv"][1:]==cmd[2:],"different physical Cargo")
            if has_owner:
                av=actual["argv"];ex={av[i+1].split("=",1)[0]:av[i+1].split("=",1)[1]for i,a in enumerate(av)if a=="--extern"}
                need(set(saved["extern"])==set(ex) and all(v["path"]==ex[k] and v["bytes"]==(obj/v["sha256"]).stat().st_size for k,v in saved["extern"].items()),"required upstream original")
        return saved
    def meta(digest,crate):
        if digest not in decoded:
            raw=(obj/digest).read_bytes()
            r=scope_rdr.decode(raw,schemas["symbols"],schemas["tables"],crate,"rustc 1.99.0-dev (Ohm metadata 3)")
            decoded[digest]=r
        return decoded[digest]
    def provider_header(digest,crate):
        # The dependent's required hash needs only this source-defined CrateRoot header.
        # Preserve the complete original provider. No edition or downstream table inference.
        raw=(obj/digest).read_bytes();r=scope_rdr.Reader(raw,schemas["symbols"])
        need(r.take(8)==b"rust\0\0\0\n","provider magic");at=int.from_bytes(r.take(8),"little")
        need(r.string()=="rustc 1.99.0-dev (Ohm metadata 3)" and r.pos<at<len(raw)-13 and raw.endswith(b"rust-end-file"),"provider schema")
        r.pos=at;need(r.symbol()=="x86_64-unknown-linux-gnu","provider target")
        values=[r.take(16).hex(),r.take(16).hex()];need(r.symbol()==crate,"different required provider name")
        return values
    def real_clean(a,b,aa,bb):
        keys={k for k in aa if aa[k]["sha256"]!=bb[k]["sha256"]};need(set(aa)==set(bb),"different literal dependency roster")
        if a==b:return dict(equal=True,different_externs=sorted(keys))
        need(keys,"different root output under the exact same direct dependencies")
        left,right=meta(a,"ty_vendored"),meta(b,"ty_vendored")
        required={k for k in left[4]if left[4][k]!=right[4][k]};need(required and set(left[4])==set(right[4]),"fresh metadata changed without an actual changed required hash")
        matched=[]
        for k in keys:
            source1=provider_header(aa[k]["sha256"],k);source2=provider_header(bb[k]["sha256"],k)
            for dependency in required:
                if dependency.startswith(k+"-") and source1!=source2:matched.append(k)
        need(matched,"no actual changed direct provider semantic header")
        return dict(equal=False,different_externs=sorted(keys),semantic_direct=sorted(set(matched)),changed_required=sorted(required),edited=a,empty=b)
    # Standalone two-thread plus exec'd-child fixture: real output and full event fidelity.
    for label in ("small","large"):
        d=root/"inherited-calibration";d0=d/(label+"-plain");plain=old.hw(d0);tmp={}
        for mode in ("owner","whole","roster"):
            dst=d/(label+"-"+mode);trace=dst.with_suffix(".epochs")
            f=next(v for v in trace.glob("*.nul")if b"\0--crate-name\0family\0"in v.read_bytes() and v.read_bytes().split(b"\0")[3].endswith(b"/family"))
            b=f.read_bytes().split(b"\0");idn={"rustc_inode":[int(b[1]),int(b[2])]};obs,_=t.decode(trace,mode,idn,"family")
            need((dst/"stdout").read_bytes()==(d0/"stdout").read_bytes() and len(obs["owner_tasks"])==3 and obs["tasks"]>=4,"inherited native control")
            if mode!="roster":tmp[mode]=obs["instructions"]
        if label=="large":need(plain>50_000_000 and all(abs(x-plain)/min(x,plain)<.01 for x in tmp.values()),"lost real child/thread instructions")
    for index,role in enumerate(reg["order"],1):
        d=root/f"visit-{index}-{role}";ident=old.load(d/"identity.json");cfg=registry["inline-"+role];physical=old.load(d/"sdk-file-stats.json")
        need(ident["role"]==role and ident["source"]==cfg["source"]==factory["source"][role] and all(ident[k]==cfg[k]for k in ("driver","rustc","cargo")) and stats.setdefault(role,physical)==physical,"SDK stat or verified contents changed across visits")
        need(ident["mapped_driver_inode"][1]==int(ident["mapped_driver_row"].split(None,5)[4]) and ident["mapped_driver_row"].split(None,5)[5]==ident["driver_path"],"incorrect authenticated fd mapping")
        m=clock(d/"mapping-owner","owner",ident,"physical_compiler_guard",None,True,False);h=old.hw(d/"mapping-whole")
        need(abs(h-m["instructions"])/min(h,m["instructions"])<.02,"genuine small compiler clock integrity")
        cold=state(d/"cold","old");prices={};raws={};out_digests={}
        for phase,src,dirty in (("old-idle","old",False),("edit","new",True),("new-idle","new",False)):
            work={};h=old.hw(d/"plain"/phase);pr=state(d/"plain"/phase,src);out_digests[phase]=pr
            for mode in ("whole","owner"):
                target=d/mode/phase;row=clock(target,mode,ident,"ty_vendored",reg["target"],dirty);work[mode]=row
                need(state(target,src)==pr,"restored histories emit different entire metadata")
                if dirty:
                    need(row["compilers"]==[["ty_vendored","--emit=dep-info,metadata"]] and len(row["build_scripts"])==1 and "/ty_vendored/"in row["build_scripts"][0] and len(row["owner_tasks"])>=2,"different genuine edited workload")
                else:need(not row["compilers"] and not row["build_scripts"],"untouched workload dirty")
            if dirty:
                need(work["whole"]["argv"]==work["owner"]["argv"] and work["whole"]["extern"]==work["owner"]["extern"],"different real editable operands")
                raws["edit"]=work["owner"]
            prices[phase]=dict(plain=h,traced_whole=work["whole"]["instructions"],owner=work["owner"]["instructions"])
        need(cold==out_digests["old-idle"]!=out_digests["edit"]==out_digests["new-idle"],"stale OLD/NEW or unstable untouched state")
        cal=clock(d/"same-deps-clean/check","roster",ident,"ty_vendored",reg["target"],True);clean=state(d/"same-deps-clean/check","new")
        need(cal["extern"]==raws["edit"]["extern"] and clean==out_digests["edit"] and all(n in ("build_script_build","ty_vendored")for n,_ in cal["compilers"]),"empty package under same dependencies differs")
        fres=clock(d/"safety/fresh","roster",ident,"ty_vendored",reg["target"],True);repair=clock(d/"safety/repair","roster",ident,"ty_vendored",reg["target"],True)
        fsha=state(d/"safety/fresh","new");need(fsha==state(d/"safety/repair","new") and fres["extern"]==repair["extern"],"failed repair after independently cold B")
        cold_control=real_clean(out_digests["edit"],fsha,raws["edit"]["extern"],fres["extern"])
        failures=[json.loads(l)for l in(d/"safety/E0308/stdout").read_bytes().splitlines()]
        errors=[r["message"]for r in failures if r["reason"]=="compiler-message"and r["message"]["level"]=="error"]
        need([r["code"]["code"]for r in errors]==["E0308"] and any(span["is_primary"]and span["file_name"].endswith("crates/ty_vendored/src/lib.rs")and any("OHM_FROZEN_LITERAL_INVALID"in t0["text"]for t0 in span["text"])for span in errors[0]["spans"]) and [r["success"]for r in failures if r["reason"]=="build-finished"]==[False],"wrong native diagnostic")
        d2=d/"parser";oo=clock(d2/"owner","owner",ident,"ruff_python_parser",reg["common_symbol_guard"],True);ow=clock(d2/"whole","whole",ident,"ruff_python_parser",reg["common_symbol_guard"],True)
        need(oo["argv"]==ow["argv"] and oo["extern"]==ow["extern"] and oo["compilers"]==ow["compilers"]==[["ruff_python_parser","--emit=dep-info,metadata"]],"different parser operands")
        need(len({state(d2/k,"new",True) for k in("cold","plain","owner","whole")})==1,"clean parser output differs")
        raws["parser"]=oo
        prices["parser"]=dict(cold=old.hw(d2/"cold"),plain=old.hw(d2/"plain"),traced_whole=ow["instructions"],owner=oo["instructions"])
        prices["cold"]=dict(plain=old.hw(d/"cold"))
        for k,v in raws.items():
            av=v["argv"];out=av[av.index("--out-dir")+1];scope,=re.findall(r"/(v2-[0-9a-f]{16})/",out)
            need(sigs.setdefault(role,scope)==scope and all(set(re.findall(r"/(v2-[0-9a-f]{16})/",a))<={scope}for a in av),"unbound scoped Cargo namespace")
            v["normalized"]=[a.replace("/"+scope+"/","/<authenticated-sdk>/")for a in av]
        if index==1:
            base=d/"fixed-operand";ref=old.load(base/"source.json")
            need(ref["argv"]==cal["argv"] and ref["extern"]==cal["extern"] and ref["archive"]in archives["new"],"unregistered fixed donor")
            for i,k in enumerate("PCP",1):
                path=base/(str(i)+k);deployed=old.load(path/"identity.json")
                obs=clock(path/"run","owner",deployed,"ty_vendored",None,True,False)
                need(deployed["driver"]==registry["inline-"+k]["driver"]and obs["argv"]==ref["argv"],"different exact independent physical driver or command")
                fixed.append(dict(role=k,instructions=obs["instructions"],metadata=state(path/"run","new")))
            need(fixed[0]["metadata"]==fixed[2]["metadata"] and abs(fixed[0]["instructions"]-fixed[2]["instructions"])/min(fixed[0]["instructions"],fixed[2]["instructions"])<.02,"opposite fixed parent repetitions disagree")
        if index<=2:
            n={}
            for mode,source in (("old","old"),("edit","new"),("fresh","new")):
                k=d/"native"/mode;r=old.load(k/"products.json");z=r["archive"]["sha256"];body=(obj/r["elf"]).read_bytes()
                need(z in archives[source]and body.startswith(b"\x7fELF") and len(body)==r["bytes"]and body.count((obj/z).read_bytes())>=1 and (k/"run/stdout").read_text().split()==r["text"]==list(map(str,reg["source"]["required_source_commit_and_doc_count"][source])),"native OLD/NEW verdict")
                rows=[json.loads(x)for x in(k/"cargo/stdout").read_bytes().splitlines()];need([x["success"]for x in rows if x["reason"]=="build-finished"]==[True] and all(any(x["reason"]=="compiler-artifact"and x["target"]["name"]==key and value["path"]in x["filenames"]for x in rows)for key,value in r["extern"].items()),"native caller has a different compiled dependency")
                n[mode]=r["elf"]
            need(n["old"]!=n["edit"]==n["fresh"],"new native differs from complete independent clean")
            native[role]=n
        visits.append(dict(role=role,index=index,prices=prices,extern={k:v["extern"]for k,v in raws.items()},argv={k:v["normalized"]for k,v in raws.items()},scope=sigs[role],empty_new=cold_control,edited_metadata=out_digests["edit"]))
    need(native["P"]==native["C"] and len(archives["old"])==len(archives["new"])==1 and archives["old"]!=archives["new"],"different genuine data or complete native binary across roles")
    all_pairs=[]
    for pair in (visits[:2],visits[2:]):
        parent,candidate=sorted(pair,key=lambda v:v["role"],reverse=True)
        need(parent["role"]=="P"and candidate["role"]=="C"and parent["argv"]==candidate["argv"],"different cross-role native flags besides the independently authenticated Cargo namespace")
        delta={phase:{meter:1-candidate["prices"][phase][meter]/val for meter,val in fields.items()if val>0}for phase,fields in parent["prices"].items()}
        controls=dict(edited_owner=delta["edit"]["owner"]>=.20,whole=delta["edit"]["plain"]>=-.01,parser=all(delta["parser"][k]>=-.02 for k in("cold","owner","plain")),independent_clock=all(abs(v["prices"]["edit"]["plain"]-v["prices"]["edit"]["traced_whole"])/min(v["prices"]["edit"]["plain"],v["prices"]["edit"]["traced_whole"])<=.03 for v in pair))
        all_pairs.append(dict(order="".join(v["role"]for v in pair),reductions=delta,gates=controls))
    fixed_delta=min(1-fixed[1]["instructions"]/fixed[x]["instructions"]for x in(0,2))
    return dict(worker=worker,factory=factory,protocol=protocol,visits=visits,pairs=all_pairs,zip={k:sorted(v)for k,v in archives.items()},native=native,fixed=fixed,fixed_reduction=fixed_delta,eligible_for_confirmation=fixed_delta>=.20 and all(all(p["gates"].values())for p in all_pairs))


if __name__=="__main__":
    archive,digest,dest=Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3])
    with archive.open("rb")as f:need(hashlib.file_digest(f,"sha256").hexdigest()==digest,"wrong physical artifact")
    with tempfile.TemporaryDirectory(prefix="literal-fixed-",dir=dest.parent)as scratch:
        target=Path(scratch);old.extract(archive,target);res=run(target)
    dest.write_text(json.dumps(res|dict(original_sha256=digest,original_bytes=archive.stat().st_size),indent=2,sort_keys=True)+"\n")
