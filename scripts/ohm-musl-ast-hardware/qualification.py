"""Verify the prospective independent original-backing and native lifetime qualification before any new hardware arm."""
import gzip
import io
from pathlib import Path
import sys
import json
import zipfile
from clocked import file_sha, require, sha

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"ohm-musl-ast-opaque"))
import consumer,opaque_metadata

DECODER="7a59be4dc08224ac412add823b391738beb864eebf07b58f52e2e7ee26574dec"
METHODS=("chars","literals","interpolations","fstring_literals","f_strings","fstring_elements","compare_iter","parameters","bytes","template")

def source(nodes):
    require(file_sha(Path(opaque_metadata.__file__))==DECODER and set(consumer.BAD)==set(METHODS),"unregistered classifier or native consumer")
    nodes_sha=opaque_metadata.validate_source(nodes)
    rows=[[h,q[0],q[2],q[3],q[4]] for h,q in opaque_metadata.CAPTURES.items()]
    require({(r[1],r[2]) for r in rows}=={(q[0],q[2]) for q in consumer.BAD.values()} and len(opaque_metadata.EXCLUDED)==7,"wrong source owners")
    return {"nodes":nodes_sha,"path":"crates/ruff_python_ast/src/nodes.rs","revision":"93526150df078af7dd8fc4226cdcc469539d2001",
            "tree":"62d3f106c5e41f6022847f26ff8c7dc00139f7b1","decoder":DECODER,"exact_public_receiver_captures":rows,
            "other_opaque_lifetimes_excluded":len(opaque_metadata.EXCLUDED)}
def previous(root,registration):
    rec=registration["opaque_preflight"]
    require(isinstance(rec,dict) and rec["passed"] is True and rec["zip_bytes"]>0,"no independent accepted native qualification")
    saved=root/"admitted/opaque-native.json"
    require(file_sha(saved)==rec["accepted_sha256"],"unfrozen native acceptance record")
    cert=json.loads(saved.read_bytes())
    require(cert["source_head"]==registration["source_head"] and cert["provider_head"]==registration["provider_head"]
            and cert["excluded_hardware_run"]==registration["rejected_hardware"]["run"]
            and set(cert["excluded_hardware_boots"])=={p["boot"] for p in registration["rejected_hardware"]["positions"]}
            and cert["finite_source"]["decoder"]==DECODER and len(cert["finite_source"]["exact_public_receiver_captures"])==10
            and cert["excluded_native_runs"]==[41175036887,41177297283]
            and cert["passed_artifact_sha256"]==rec["zip_sha256"] and set(cert["native_outputs"])=={"old","new"}
            and all(len(d)==64 for d in cert["native_outputs"].values()) and cert["native_outputs"]["old"]!=cert["native_outputs"]["new"],
            "incompatible independent native qualification or original failed boots")
    require(file_sha(root/"admitted/opaque-native-reopened.json")==cert["independent_reopened_sha256"]
            and file_sha(root/"admitted/opaque-native-physical.json")==cert["independent_physical_sha256"]
            and len(cert["consumer_sources"])==11,"missing independent reopens or native sources")
    return rec,cert

def recheck_api(root,registration,request):
    q,cert=previous(root,registration)
    run=json.loads(request("runs/"+str(q["run"])))
    require((run["id"],run["event"],run["head_sha"],run["status"],run["conclusion"],run["run_attempt"])==
            (q["run"],"workflow_dispatch",q["head"],"completed","success",1),"wrong independent native acceptance")
    j=json.loads(request("runs/"+str(q["run"])+"/jobs?per_page=100"))["jobs"]
    require(len(j)==1 and j[0]["id"]==q["job_id"] and j[0]["conclusion"]=="success","native acceptance job")
    a=json.loads(request("artifacts/"+str(q["artifact_id"])))
    require((a["name"],a["size_in_bytes"],a["digest"],a["workflow_run"]["id"],a["workflow_run"]["head_sha"],a["expired"])==
            ("musl-opaque-native-qualification",q["zip_bytes"],"sha256:"+q["zip_sha256"],q["run"],q["head"],False),"native artifact changed")
    raw=request("artifacts/"+str(a["id"])+"/zip")
    require(len(raw)==a["size_in_bytes"] and sha(raw)==q["zip_sha256"],"native archive integrity")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        require(z.testzip() is None,"native ZIP CRC")
        def one(end):
            got=[n for n in z.namelist() if n==end or n.endswith("/"+end)]
            require(len(got)==1,end)
            return json.loads(z.read(got[0]))
        passed=one("passed.json");custody=one("custody.json")
        require(cert["finite_source"]==one("finite-source.json")==source(gzip.decompress(z.read("nodes.rs.gz"))),"changed actual source/borrow classification")
        require(cert["consumer_sources"]==one("sources.json"),"independent native consumer inputs differ")
        prior=one("reopened-second-empty.json");require(prior["previous_head"]=="b6a2d26f30a2d334aa9933d078882ad765d9fb54" and prior["original_qualified_roles"]==[] and prior["old_compiler_completed_native_visits"]==5 and len(prior["actual"])==6,"wrong earlier P-only native result")
        require(custody["transfer"]==registration["source_transfer"] and custody["workflow"]==q["head"],"different compiler/native kit")
        for role in "PC":
            p=passed[role];require(p==one(role+"/terminal.json") and p["old_augmented_elf"]==cert["native_outputs"]["old"]
                 and p["corrected_augmented_elf"]==cert["native_outputs"]["new"],"different support-program or incomplete native run")
            want={"old","edit","measured-final","empty1","empty2"}
            require(set(p["tested_samples"])==set(p["independently_reopened"])==want
                    and p["historical_mixed_diagnostic"]==p["one_foreign_dependency_rejected"]=="E0463"
                    and p["one_foreign_dependency_repaired"] is True
                    and {n for n,x,y in p["historical_mixed_hashes"] if x!=y}=={"rustversion","castaway","char_str","thiserror","compact_str"},
                    "mixed graph not rejected separately from the matching closed graphs")
            for sample in want:
                expected={"metadata/positive":0,"archive/positive":0,**{"metadata/"+k:1 for k in METHODS}}
                require(p["tested_samples"][sample]==p["independently_reopened"][sample]==expected,"missing real, restored positive or lifetime error: "+sample)
                idx=one(role+"/proof/"+sample+"/matching-closure.json"); restored=one(role+"/restored/"+sample+"/physical-files.json")
                require(len(idx["unit_ids"])==39 and set(idx["files"])==set(restored)
                        and all((o["sha256"],o["bytes"])==(restored[n]["sha256"],restored[n]["bytes"])
                            and (o["dev"],o["ino"])!=(restored[n]["dev"],restored[n]["ino"]) for n,o in idx["files"].items()),
                        "missing independent exact graph restoration")
            old=one(role+"/literally-reopened-historical-elfs.json")
            require(old["old"]["stdout"]=="elif predicates 2, elif/else clauses 0\n" and old["empty"]==old["measured-final"]
                    and old["empty"]["stdout"]=="elif predicates 1, elif/else clauses 2\n","lost historical native visitor")
            cross=one(role+"/restored/empty1/one-foreign-then-repair/one-substitution.json")
            require(cross["logical_dependency_count"]==1 and cross["restored"] and cross["rejected"]["code"]=="E0463" and cross["actually_opened_foreign"],"single real dependency swap")
            proof=one(role+"-original-full-archive.json");require(set(proof["strict_differences"])=={"canonical_rlib","rmeta","embedded_metadata"}
                 and proof["forward"]["reencoded_ar"]==proof["forward"]["destination_ar"] and proof["reverse"]["reencoded_ar"]==proof["forward"]["source_ar"],"original failures obscured")
    return cert
