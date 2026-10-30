"""Verify the preceding signed check and test-build acquisition with the original ZIP."""
import gzip
import hashlib
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath

HERE=Path(__file__).resolve().parent
if not __debug__:raise SystemExit("Use Python without -O.")
if len(sys.argv)!=2:raise SystemExit("Usage: python3 -IB signed.py apple-zmij-signed-verbs.zip")
zfile=Path(sys.argv[1])
digest=lambda b:hashlib.sha256(b).hexdigest()
read=lambda p:json.loads(p.read_bytes())
unzip=lambda p:gzip.decompress(p.read_bytes())
a=digest(zfile.read_bytes())
assert a=="d91085ee544c70231dc3e18a2d9c3db8f2a02b6f5a53270a8bb853f19b108447" and zfile.stat().st_size==320324
z=zipfile.ZipFile(zfile)
assert z.testzip() is None
members=[n for n in z.namelist() if not n.endswith("/")]
assert len(set(members))==len(members)==160
data=zipfile.Path(z)
release=read(data/"release.json");ruff=read(data/"ruff.json")
assert release["archive"]=="7cd292583785c25a315f67bf85c8f028a15ccb0be5461ac39ce6e46720807bb8"
assert release["packed_cargo"]["sha256"]==release["cargo"]["sha256"]=="505008003127f597cf2bdbd967d2bac9158d706b55a18f8bf17790e9ea3bbac9"
assert release["rustc"]["sha256"]=="a3fcb16dbc02716452b1f1ac3db6dea0b9083c722a08633c233c27e7286173ca"
assert release["driver"]["sha256"]=="a315a19bcb43a251a9cb83fc3950357852652f8f0f0a678b83bb05a80f428cc3"
assert "7e71d3150938ff8ed82aca03416439d7e5b87ef3" in release["rustc_version"] and "2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c" in release["cargo_version"]
assert (ruff["old"],ruff["new"],ruff["lock"])==("b5dba861cc38e3f7fb4524c9ceba3e01a474ea13","7b13f01ba1569887a25670820764b24c206da8e5","839edc8250480bb523619b8d24bd57176a6e1f57c152cca85c5adc61ea5f94eb")
assert len(ruff["archives"])==423
oracle=read(data/"observer.json");ol,=[(r["path"],r["cdhash"]) for r in oracle["rows"] if PurePosixPath(r["path"]).name=="ld"]
assert oracle["exit"]==29 and oracle["executable"]==digest(unzip(data/"observer-probe/observed/output.macho.gz"))
cal=read(data/"calibration/result.json")
assert cal["host"]["machine"]=="arm64" and cal["tree_CPU_calibrated"] and cal["retired_instruction_scope"]=="unavailable-or-inconclusive"
phases=["empty-old/clean","empty-new/clean","visit/cold","visit/edit","visit/repeat-1","visit/repeat-2","visit/invalid","visit/repair"]
results={}; signed_cd={}; individual={}; qualified_links=set()
for verb in ("check","test"):
   folder=data/"signed-verbs"/verb
   report=read(folder/"result.json"); rows={}; inventory={}
   for rel in phases:
      p=folder/rel;record=read(p/"verified.json");state=record["state"];ok=state!="invalid";native=record["native"];prod=record["product"]
      assert record["status"]==(0 if ok else 101) and native["scope"]=="kernel-exec" and record["role"]=="S"
      streams={s:unzip(p/f) for s,f in {"stdout":"stdout.gz","stderr":"stderr.gz","native_events":"exec.json.gz"}.items()}
      assert {s:digest(v) for s,v in streams.items()}==record["streams"]
      cargo_stream=[json.loads(l) for l in streams["stdout"].splitlines()]
      assert cargo_stream[-1]=={"reason":"build-finished","success":ok}
      artifacts=[c for c in cargo_stream if c["reason"]=="compiler-artifact"]
      def unit(c):return [c["package_id"],c["target"]["name"],",".join(c["target"]["kind"]),c["features"],json.dumps(c["profile"],sort_keys=True,separators=(",",":"))]
      assert sorted(unit(c) for c in artifacts)==record["roster"] and sorted(unit(c) for c in artifacts if not c["fresh"])==record["dirty"]
      codes=[c["message"]["code"]["code"] for c in cargo_stream if c["reason"]=="compiler-message" and c["message"].get("code")]
      assert codes==record["codes"]==([] if ok else ["E0425"])
      if not ok: assert b"ohm_test_build_missing_28335" in streams["stdout"] and prod is None
      es=json.loads(streams["native_events"]);seq=[r["seq"] for r in es];assert seq==sorted(set(seq))
      full=[];relink=[];links=[];cargo=[]
      for row in es:
         path=row["path"];name=PurePosixPath(path).name;argv=row["argv"]
         if path.endswith("/signed/bin/cargo") or path.endswith("/signed/bin/rustc"):
            signed_cd.setdefault(name,set()).add(row["cdhash"])
         if path.endswith("/signed/bin/cargo"):cargo.append(row)
         if path.endswith("/signed/bin/rustc") and "--crate-name" in argv:
            crate=argv[argv.index("--crate-name")+1]
            if crate=="___" and any(x.startswith("--print") for x in argv): continue
            (relink if any("link-only" in x for x in argv) else full).append(crate)
         if name in ("ld","ld64","ld-classic","ld-prime","ld64.lld","ld.lld","wild","wild-ld","rust-lld"):
            assert (path,row["cdhash"])==ol
            links.append(argv)
      assert len(cargo)==native["cargo"]==1 and sorted(full)==native["full"] and sorted(relink)==native["link_only"]
      assert [x["argv"] for x in native["linkers"]]==links and all(x["stock"] and x["sha"]==oracle["ld"] for x in native["linkers"])
      for argv in links:
         if "-o" in argv:qualified_links.add(PurePosixPath(argv[argv.index("-o")+1]).name)
      zmij,=[c for c in artifacts if c["target"]["name"]=="zmij" and c["target"]["kind"]==["lib"]]
      assert zmij["fresh"]==record["fresh_zmij"] and int(not zmij["fresh"])==full.count("zmij")
      dep=unzip(p/"zmij.dep.gz");marker={"sha256":digest(dep),"hard":b"ohm-untracked-relink-inputs" in dep,"recheck":b"/dev/null/ohm-recheck-dependent-links" in dep}
      assert marker==record["marker"] and b"zmij-1.0.10/src/lib.rs" in dep and marker["hard"]==(verb=="test") and not marker["recheck"]
      if ok:
         selected,=[c for c in artifacts if c["target"]["name"]=="ruff_python_ast" and bool(c["executable"])==(verb=="test")]
         if verb=="check":
            expected=64 if state=="old" else 56
            assert prod["layout"]==expected and selected["filenames"][0].endswith(".rmeta")
            for size in (56,64):
               side=p/("layout-"+str(size));assert unzip(side/"stdout.gz")==b""
               diagnostics=[json.loads(l) for l in unzip(side/"stderr.gz").splitlines()]
               if size==expected: assert not diagnostics
               else: assert [r["code"]["code"] for r in diagnostics if r.get("code")]==["E0308"]
         else:
            tests=prod["tests"]
            assert sorted(set(tests))==tests and selected["profile"]["test"] and selected["executable"]
            assert ("nodes::tests::f_string_parts" in tests)==(state=="new") and "nodes::tests::size" in tests
            for case in ["size"]+(["f_string_parts"] if state=="new" else []):
               verdict=unzip(p/(case+".gz"));assert ("test nodes::tests::"+case+" ... ok").encode() in verdict and b"1 passed; 0 failed" in verdict
      proto={"full":sorted(full),"relink":sorted(relink),"ld":len(links),"typed":len(artifacts),"status":record["status"],"marker":marker["hard"],"product":prod,"streams":record["streams"]}
      rows[rel]=proto
      if rel.startswith("visit/"):
         assert native==report["physical"][rel.split("/")[1]]
   for s,ref in (("old",rows["empty-old/clean"]["product"]),("new",rows["empty-new/clean"]["product"])):
      assert report["clean"][s]==ref
   if verb=="test":
      o,n=(set(rows["empty-"+s+"/clean"]["product"]["tests"]) for s in ["old","new"])
      assert n-o=={"nodes::tests::f_string_parts"} and not o-n
   for label in ["cold","edit","repeat-1","repeat-2","repair"]:
      ref=report["clean"]["old" if label=="cold" else "new"];observed=rows["visit/"+label]["product"]
      assert {k:(observed[k]==v) for k,v in ref.items()}==report["clean_comparisons"][label]
   assert report["both_repeats_compile_zmij"]==all("zmij" in rows["visit/"+label]["full"] for label in ["repeat-1","repeat-2"])
   results[verb]={"phases":rows,"clean_comparisons":report["clean_comparisons"]}
assert set(signed_cd)=={"rustc","cargo"} and all(len(v)==1 for v in signed_cd.values())
receipt={"run":41051991519,"head":"8fb888395d94179bf969f60e5667df473b16b17c","archive_sha256":a,"archive_size":zfile.stat().st_size,"file_count":len(members),"scope":"kernel-exec, typed Cargo JSON, on-host product digests and tests, independently read Mach-O calibration probe and stored reader streams; no timed P/C comparison","subjects":{"release_archive":release["archive"],"cargo":release["cargo"]["sha256"],"rustc":release["rustc"]["sha256"],"driver":release["driver"]["sha256"],"stdlib_files":len(release["std"]),"old":ruff["old"],"new":ruff["new"],"lock":ruff["lock"],"registry_files":len(ruff["archives"])},"observer":{"cargo_and_rustc_cdhash":{k:next(iter(v)) for k,v in signed_cd.items()},"ld_sha256":oracle["ld"],"ld_cdhash":ol[1],"ld_output_basenames":sorted(qualified_links),"counter":cal["retired_instruction_scope"]},"verbs":results}
assert receipt==json.loads(gzip.decompress((HERE/"signed-observations.json.gz").read_bytes()))
print("Verified signed check and test-build, 160 members, two independent clean states per command, zero paired clocks.")
