"""Place launch-time coverage under the existing bootstrap shim, and independently replay its result."""
import argparse
import gzip
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from read import digest,load,reduce,require,save
from origins import verify
H=Path(__file__).resolve().parent

def begin(out, env, manifest, rustc):
    out=Path(out).absolute()
    manifest=Path(manifest).resolve(strict=True)
    require((manifest/"src/lib.rs").is_file(), "missing canonical target manifest source")
    require(not any(env.get(k) for k in ("RUSTC_WRAPPER","RUSTC_WRAPPER_REAL","OHM_PHASE_OUT","OHM_PHASE_MANIFEST")),
            "earlier wrapper or prior enrollment would be overwritten")
    exe=Path(shutil.which("strace") or "").resolve(strict=True)
    require(exe.is_file() and os.access(H/"phase-wrapper",os.X_OK), "strace or bootstrap wrapper missing")
    out.mkdir(mode=0o700)
    save(out/"start.json",{"strace":str(exe),"strace_version":subprocess.check_output([exe,"--version"],text=True).splitlines()[0],
                         "strace_sha256":hashlib.file_digest(exe.open("rb"),"sha256").hexdigest(),
                         "manifest":str(manifest),"rustc":str(Path(rustc).absolute()),
                         "collector":{k:digest((H/k).read_bytes())for k in ("phase.py","phase-wrapper","observe.py","read.py","origins.py")}})
    # No change to Cargo's fingerprinted RUSTC_WRAPPER or to the compiler's command line.
    return {**env,"RUSTC_WRAPPER_REAL":str(H/"phase-wrapper"),"OHM_PHASE_OUT":str(out),"OHM_PHASE_MANIFEST":str(manifest)}

def receipt(path, ref):
    raw=gzip.decompress((path/ref["raw"]).read_bytes())
    require(len(raw)==ref["bytes"] and digest(raw)==ref["sha256"],("retained supplier/exception bytes",ref))
    return raw

def join(out,capture_path,required_foreign):
    import json
    out=Path(out); capture_path=Path(capture_path); cap=load(capture_path)
    require(cap["arm"]=="T" and cap["exit"]==0 and not cap["observer_errors"],"original late link capture refused")
    pending=list(out.glob("visit-*"));require(len(pending)==1,("actual target acquisitions",pending))
    visit=pending[0]; native=reduce(visit)
    require(native==load(visit/"observed.json"),"reopened native receipt")
    req=load(visit/"request.json"); p=capture_path.parent
    path=native["policy"]+"/"+str(native["pid"])+".exports"
    require(list(cap["policies"])==[path] and path.startswith(req["policy"]+"/"),"rustc/late exception does not join")
    rec=cap["policies"][path]; audit=json.loads(receipt(p,rec["supplier_evidence"]))
    ex=receipt(p,rec["exceptions"])
    links=[l for l in cap["links"].values()if "--export-dynamic-symbol-list="+path in l["options"]]
    require(len(links)==1 and any(s["path"]==path and receipt(p,s)==ex for s in links[0]["scripts"]),"actual lld consumed different witness")
    declared=audit["receipts"]; matched={}; missing=[]; foreign=[]
    sources=load(visit/"archives.json");verify(visit,native,sources,req["cwd"])
    for row,source in zip(native["rows"],sources):
        key=row["key"]
        if row["matched"]:
            require(key in declared,("unqualified positive",key))
            donor=declared[key]
            require(donor["sha256"]==source["sha256"],("Rust-selected archive and hard-link bytes differ",key))
            require((donor["dev"],donor["ino"],donor["bytes"])==
                    (row["physical"]["dev"],row["physical"]["ino"],row["physical"]["size"]),("archive changed",key))
            require(donor["nlink"]>=2 and donor["observed_native_sources"] and
                    all(x["manifest"] in audit["owners"] for x in donor["observed_native_sources"]),("unqualified in-tree source",key))
            matched[key]={"used_source":row["source"],"sha256":donor["sha256"],
                          "qualifying_sources":donor["observed_native_sources"]}
        else:
            for proof in source["native_sources"]:
                if proof["manifest"] not in audit["owners"]:
                    foreign.append({"key":key,"source":row["source"],"sha256":source["sha256"],"provenance":proof})
            missing.append({"key":key,"path":row["source"],"errno":row["errno"],"receipt_stat":row["receipt_stat"],
                            "also_marked_in_later_snapshot":key in declared})
    require(matched and missing and any(x["provenance"]["name"]==required_foreign for x in foreign),
            ("actual in-tree receipt, protected physical input and source-qualified foreign package required",required_foreign))
    return {"target_pid":native["pid"],"target_tid":native["tid"],"lld_pid":links[0]["pid"],"policy":path,
            "source_rows":len(native["rows"]),"qualified_matches":matched,"protected_inputs":missing,
            "physical_marks_not_observed_matching":sorted(set(declared)-set(matched)),
            "proven_foreign":foreign,"archives_sha256":digest((visit/"archives.json").read_bytes()),
            "closed_exception_sha256":digest(ex),"native_sha256":digest((visit/"observed.json").read_bytes()),
            "capture_sha256":digest(capture_path.read_bytes())}

def finish(out,capture_path):
    return join(out,capture_path,"blake3")

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("out");parser.add_argument("capture");parser.add_argument("result")
    a=parser.parse_args();save(a.result,finish(a.out,a.capture))
