"""Connect the ephemeral typed exception set with the two independently captured actual ELFs."""
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import os
sys.path.insert(0,str(Path(__file__).resolve().parent))
import gate as g
import suppliers

def untar(row,out):
    raw=gzip.decompress((out/row["raw"]).read_bytes())
    assert len(raw)==row["bytes"] and hashlib.sha256(raw).hexdigest()==row["sha256"]
    return raw

def exports(raw):
    rows=raw.decode().splitlines()
    assert rows[0]=="{" and rows[-1]=="};" and len(rows)>2
    assert all(line.startswith("  ") and line.endswith(";") for line in rows[1:-1])
    return {line[2:-1] for line in rows[1:-1]}

def prove(w,arm,pre,post,pre_rows,post_rows):
    out=w/"trait-evidence/driver-witness";capture=g.read(out/"capture.json")
    assert capture["arm"]==arm and capture["exit"]==0 and capture["pre_bolt"]["sha256"]==pre["sha256"]
    assert not capture["observer_errors"],capture["observer_errors"]
    assert not pre["bolt_note"] and post["bolt_note"] and pre["sha256"]!=post["sha256"] and pre["linker"]==post["linker"]
    assert pre_rows["symbols"]==post_rows["symbols"] or {tuple(x) for x in pre_rows["symbols"]}=={tuple(x) for x in post_rows["symbols"]},"BOLT changed dynamic symbol identity or ELF kind"
    rust=w/"source/rust"
    policies={};exceptions=None
    for key,rec in capture["policies"].items():
        paths=json.loads(untar(rec["owners"],out))
        meta=suppliers.records(rust,paths);names={x["name"] for x in meta.values()}
        assert {"rustc_driver","rustc_codegen_ssa","rustc_mir_transform"}<=names
        assert not ({"rustc_demangle","rustc_apfloat","rustc_stable_hash","measureme","type_map"}&names)
        assert untar(rec["driver"],out)==os.fsencode((rust/"compiler/rustc_driver").resolve(strict=True))
        physical=json.loads(untar(rec["supplier_evidence"],out));assert physical["owners"]==meta
        rows=physical["receipts"];assert rows
        for ident,rr in rows.items():
            assert ident==f"{rr['dev']:x}-{rr['ino']:x}" and Path(rr["receipt"]).parent==Path(key).parent and Path(rr["receipt"]).name==ident+".rlib"
            assert rr["nlink"]>=2 and rr["bytes"]>0 and re.fullmatch("[0-9a-f]{64}",rr["sha256"])
            for target in rr["observed_native_sources"]:
                assert target["rlib"] in rr["paths"] and meta[target["manifest"]]["lib"]==target["source"]
                assert (os.fsencode(target["rlib"])+b": ") in untar(target["dep_info"],out)
        row=rec["exceptions"];all_exc=exports(untar(row,out))
        # Only entries for this GNU production driver qualify.
        present={sym[0] for sym in post_rows["symbols"] if sym[4]}
        assert len(all_exc&present)>1500 and len(present-all_exc)>1000
        if exceptions is not None:assert exceptions==all_exc
        exceptions=all_exc
        policies[key]={"owners":rec["owners"],"driver":rec["driver"],"supplier_evidence":rec["supplier_evidence"],"supplier_inodes":len(rows),"exceptions":row,"manifests":meta,"total_exceptions":len(all_exc),"retained_dynamic_exports":len(all_exc&present),"dynamic_complement":len(present-all_exc)}
    assert bool(policies)==(arm=="T")
    if exceptions is not None:
        for rows in (pre_rows,post_rows):
            symbols={s[0]:s for s in rows["symbols"]}
            bad=[n for _,kind,_,n,k in rows["named_relocations"] if k and symbols[n][1:]==[1,2,0,True] and n.startswith("_R") and n not in exceptions and kind in (1,6,7)]
            assert not bad,("still-preemptible eligible strong functions",bad[:8])
    return {"arm":arm,"policies":policies,"captured_linkers":len(capture["links"]),"pre_bolt":capture["pre_bolt"],"source":[] if not policies else list(policies)[0],"linker":post["linker"]},exceptions
