"""Unscored corruption, immutable hardlink, and bidirectional placement checks on private Ruff targets."""
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tomllib

from common import HERE, WORKFLOW, need, save, sha
import storage
import tracking
sys.path.insert(0,str(WORKFLOW))
import acquire
from acquire import guards, pilot, replay, runtime, study, support


def member_map(data):
    need(data.startswith(b"!<arch>\n"),"not an rlib")
    cursor=8;long=b"";objs={};meta={}
    while cursor<len(data):
        hdr=data[cursor:cursor+60]
        need(len(hdr)==60 and hdr[58:]==b"`\n","invalid GNU archive header")
        size=int(hdr[48:58]);pos=cursor+60;last=pos+size
        need(last<=len(data),"member beyond archive")
        name=hdr[:16].rstrip().decode("ascii")
        member=memoryview(data)[pos:last];cursor=last+(size%2)
        if name=="//":
            need(not long,"duplicate archive long names")
            long=bytes(member);continue
        if name in ("/","/SYM64/"):continue
        if name.startswith("/") and name[1:].isdigit():
            idx=int(name[1:]);end=long.find(b"/\n",idx)
            need(0<=idx<end,"bad GNU extended member name")
            name=long[idx:end].decode()
        else:name=name.removesuffix("/")
        if name in ("lib.rmeta","lib.rmeta-link"):
            need(name not in meta,"duplicate Rust metadata member")
            meta[name]=hashlib.sha256(member).hexdigest();continue
        m=tracking.NAME.fullmatch(name)
        need(m and m["owner"]=="ruff_workspace" and m["cgu"] not in objs and member[:6]==b"\x7fELF\x02\x01",
             ("unknown native archive member",name))
        objs[m["cgu"]]=hashlib.sha256(member).hexdigest()
    need(cursor==len(data) and objs and "lib.rmeta" in meta,"incomplete whole native archive")
    return {"objects":objs,"metadata":meta,"raw_sha256":hashlib.sha256(data).hexdigest()}


def executable_byte(data):
    need(data[:6]==b"\x7fELF\x02\x01","invalid old native object")
    shoff=struct.unpack_from("<Q",data,40)[0];shsize,n=struct.unpack_from("<HH",data,58)
    need(shsize==64 and 0<n<65535 and shoff+n*64<=len(data),"unsupported old object section table")
    for i in range(n):
        e=struct.unpack_from("<IIQQQQIIQQ",data,shoff+i*64)
        if e[1]==1 and (e[2]&6)==6 and e[5] and e[4]+e[5]<=len(data):
            return e[4]
    raise ValueError("known hit had no executable code")


def detached_replace(path,data,receipt):
    old=path.stat()
    before=sha(path)
    temp=path.with_name(path.name+".private-placement-control")
    with temp.open("xb") as f:
        f.write(data);f.flush();os.fsync(f.fileno())
    temp.chmod(old.st_mode&0o777)
    os.utime(temp,ns=(old.st_atime_ns,old.st_mtime_ns))
    os.replace(temp,path)
    after=path.stat()
    need(before!=sha(path) and old.st_size==after.st_size and old.st_mtime_ns==after.st_mtime_ns and
         (old.st_dev,old.st_ino)!=(after.st_dev,after.st_ino) and after.st_nlink==1,"unisolated byte mutation")
    save(receipt,{"path":str(path),"before":[before,old.st_dev,old.st_ino,old.st_nlink,old.st_size,old.st_mtime_ns],
                  "after":[sha(path),after.st_dev,after.st_ino,after.st_nlink,after.st_size,after.st_mtime_ns]})


def object_dict(root):
    result={}
    for p in sorted(root.rglob("*.o")):
        if not p.is_file() or not re.fullmatch("[a-z0-9]{25}\\.o",p.name):continue
        k=p.stem
        need(k not in result,"ambiguous finalized prior CGU")
        result[k]=p
    return result


def bind_prior(path,object_bytes):
    raw=path.read_bytes();footer=storage.parse_footer(raw)
    need(footer is not None,"no placement entries on the actual matched object session")
    at=footer["offset"]+len(storage.MAGIC)
    winners=[]
    for slot,size,key,expected in footer["entries"]:
        at+=8
        body=raw[at:at+size-32];at+=size
        observed=subprocess.check_output(["/usr/bin/b3sum","--no-names"],input=bytes(object_bytes)+body+struct.pack("<Q",len(body))).decode().strip()
        if observed==expected:winners.append({"slot":slot,"key":key,"record_bytes":size,"bound_blake3":expected,"index":sha(path)})
    need(len(winners)==1,"previous object and wire did not match one unique authenticated BLAKE3 record")
    return winners[0]


def prior_witnesses(where,objects,known):
    where.mkdir()
    result={}
    for cgu in sorted(known):
        p=objects[cgu];dst=where/(cgu+".o")
        old=p.stat();before=sha(p)
        os.link(p,dst)
        link=dst.stat()
        need(dst.samefile(p) and old.st_nlink+1==link.st_nlink,"not an actual old hardlink")
        result[cgu]={"path":str(p),"witness":str(dst),"dev":link.st_dev,"ino":link.st_ino,"size":link.st_size,
                     "nlink":[old.st_nlink,link.st_nlink],"sha256":before}
    return result


def exercise(kit,root,source):
    kit.select("C")
    suite=root/"workflow-option"
    state=acquire.source_entry(source,"option")
    cmd=state["command"];role_summary=json.loads((kit.evidence/"option/acquired.json").read_bytes())["C"]
    reference=json.loads((kit.evidence/"option/C-edit/new/source-selection.json").read_bytes())
    accepted={v["cgu"] for v in reference["renames"] if v["owner"]=="ruff_workspace"}
    need(accepted,"no genuine previously accepted CGU to challenge")
    chosen=sorted(accepted)[0]
    dest=kit.evidence/"durability";dest.mkdir()
    donor=suite/"registry-donor";work=suite/"work";repo=suite/"ruff";extras=suite/"consumer"
    env=kit.base|{"CARGO_HOME":str(work/"cargo-home"),"CARGO_TARGET_DIR":str(work/"target"),"CARGO_BUILD_BUILD_DIR":str(work/"build")}
    registry={r["name"]+"-"+r["version"]+".crate":r["checksum"] for r in tomllib.loads((source/"Cargo.lock").read_text())["package"] if "checksum" in r}
    gold=study.source_pair(source)
    # These raw files were independently emitted and saved during the ordinary, untampered admission.
    expected={}
    for rev,key in ((study.OLD,"old"),(study.NEW,"clean-new")):
        source_hash=role_summary[key]["owner_archive"]["sha256"]
        with gzip.open(kit.evidence/"owner-archives"/(source_hash+".gz"),"rb") as f:
            expected[rev]=member_map(f.read())
        need(expected[rev]["raw_sha256"]==source_hash,"wrong independent native reference")
    terminals={}
    for case_name in ("round-trip","object-corrupt","optional-corrupt","independent-empty-old"):
        case=dest/case_name;case.mkdir()
        guards.admit(guards.resources(work,case),entry=True)
        study.write_source(repo,study.OLD,False)
        with replay.empty_roots(work,case):
            home=work/"cargo-home";(home/"registry").mkdir()
            for f in ("index","cache"):
                subprocess.run(["cp","-a","--reflink=auto",donor/"registry"/f,home/"registry"/f],check=True)
            subprocess.run(["cargo","+ohm","fetch","--locked","--offline"],env=env,cwd=repo,check=True)
            need(pilot.registry(home)==registry,"different original registry")
            graph=pilot.unit_graph(cmd,env,repo,case,"option")
            reports={};oldlinks={}
            for phase,rev in ([("old",study.OLD)] if case_name=="independent-empty-old" else
                              [("old",study.OLD),("new",study.NEW)]+([("return-old",study.OLD)] if case_name=="round-trip" else [])):
                loc=case/phase
                before=study.write_source(repo,rev,False)
                with tracking.add_file_calls(guards,loc):
                    rusts,actual,_,_,_,_=runtime.visit(kit,loc,work,repo,env,cmd,0,score=False,cold=phase=="old",observe=phase!="old")
                need(before==study.source_state(repo,rev,False),"source changed during the selected visit")
                rows=replay.cargo_rows((loc/"outer.stdout").read_bytes())
                products=study.results(rows,True)
                keys=[acquire.e2e.artifact_key(v["package_id"],v["target"],v["features"],v["profile"]["test"]) for v in products]
                need(Counter(keys)==graph[0],"different real Cargo graph")
                dirty=[k for v,k in zip(products,keys) if not v["fresh"]]
                need(Counter(dirty)==graph[0] if phase=="old" else actual=={"rustc":[["full","ruff_workspace",1]],"linkers":[]},
                     ("wrong physical cold/edited compiler count",case_name,phase,actual))
                reader=pilot.native.client(loc,rows,products,extras,work,env,gold[rev],kit.evidence/"native-bodies")
                expected_reader=role_summary["old" if rev==study.OLD else "clean-new"]["elf"]
                need(reader["sha256"]==expected_reader,"complete separately linked reader differed from independent cold")
                archive=study.artifact(products,study.OWNER)
                stored=support.physical.keep(archive,kit.evidence/"owner-archives",b"!<arch>\n")
                parsed=member_map(archive.read_bytes())
                need(parsed["raw_sha256"]==stored["sha256"] and parsed["objects"]==expected[rev]["objects"],
                     ("different executable or DWARF bytes in an owner CGU",case_name,phase))
                selection=tracking.read(loc,kit.sdk);save(loc/"source-selection.json",selection)
                hits={v["cgu"] for v in selection["renames"] if v["owner"]=="ruff_workspace"}
                writes={v["cgu"] for v in selection["ordinary_native_object_writes"] if v["owner"]=="ruff_workspace"}
                report={"phase":phase,"source":rev,"reader":reader["sha256"],"archive":parsed,"reference_archive":expected[rev]["raw_sha256"],
                        "selection":sha(loc/"source-selection.json"),"hits":sorted(hits),"native_writes":sorted(writes)}
                if phase=="old":
                    need(not hits,"true empty produced a reuse hit")
                    objects=object_dict(tracking.inc_root(loc,"ruff_workspace"))
                    need(accepted<=objects.keys(),"measured CGU absent from fresh old incarnation")
                    if case_name=="round-trip":
                        oldlinks=prior_witnesses(suite/"durable-originals",objects,accepted)
                        save(case/"hardlinks-before.json",oldlinks)
                    elif case_name=="object-corrupt":
                        p=objects[chosen];b=bytearray(p.read_bytes())
                        old_hash=hashlib.sha256(b).hexdigest()
                        need(old_hash==parsed["objects"][chosen],"prior native object is not the independently observed native archive member")
                        matching=bind_prior(p.parent/"work-products.bin",b)
                        with gzip.open(case/"original-old-object.o.gz","xb") as f:f.write(b)
                        with gzip.open(case/"original-work-products.bin.gz","xb") as f:f.write((p.parent/"work-products.bin").read_bytes())
                        i=executable_byte(b);b[i]^=1
                        detached_replace(p,b,case/"object-mutation.json")
                        with gzip.open(case/"mutated-old-object.o.gz","xb") as f:f.write(p.read_bytes())
                        report["old_object_mutation"]={"cgu":chosen,"offset":i,"bound_to_previous_ordinary_hit":chosen in accepted,"record":matching}
                    elif case_name=="optional-corrupt":
                        prior=objects[chosen].parent/"work-products.bin"
                        raw=bytearray(prior.read_bytes());footer=storage.parse_footer(raw)
                        need(footer and footer["entries"],"current source did not persist its optional footer")
                        with gzip.open(case/"original-work-products.bin.gz","xb") as f:f.write(raw)
                        start=footer["offset"]+12
                        raw[start:start+4]=b"\xff"*4  # impossible first row length, legacy index and end marker preserved
                        try:storage.parse_footer(raw)
                        except ValueError:pass
                        else:raise AssertionError("collector admitted corrupt optional row")
                        detached_replace(prior,raw,case/"footer-mutation.json")
                        with gzip.open(case/"mutated-work-products.bin.gz","xb") as f:f.write(prior.read_bytes())
                        report["invalid_footer"]={"offset":footer["offset"],"prefix_sha256":footer["prefix_sha256"],"legacy_end":bytes(raw[-len(storage.END):]).decode()}
                elif case_name=="object-corrupt":
                    need(chosen not in hits and chosen in writes,"wrong old executable was accepted, or no ordinary fallback was observed")
                elif case_name=="optional-corrupt":
                    need(not hits and accepted<=writes,"invalid optional index did not fall back for the previously proven hits")
                else:
                    need(hits & accepted,"no accepted CGU on the second LLVM history")
                if oldlinks:
                    report["prior_hardlink_readback"]={}
                    for cgu,w in oldlinks.items():
                        p=Path(w["witness"]);s=p.stat()
                        current=[s.st_dev,s.st_ino,s.st_size,sha(p)]
                        need(current==[w["dev"],w["ino"],w["size"],w["sha256"]],"old finalized inode was modified")
                        report["prior_hardlink_readback"][cgu]=current
                save(loc/"durability.json",report);reports[phase]=report
            if case_name=="round-trip":
                need(set(reports["new"]["hits"]) & set(reports["return-old"]["hits"]),"rewritten object was never reused on the return")
            terminals[case_name]={k:v["archive"]["raw_sha256"] for k,v in reports.items()}
    save(dest/"complete.json",{"ordinary_hit_cgu":chosen,"reference_hits":sorted(accepted),"outcomes":terminals})
