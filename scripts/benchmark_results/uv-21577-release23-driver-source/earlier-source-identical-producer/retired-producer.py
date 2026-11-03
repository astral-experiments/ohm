"""Reopen the original source-identical build which failed the post-ThinLTO observer."""
from pathlib import Path
from zipfile import ZipFile
import gzip,hashlib,json,shutil,sys,tempfile
SCRIPT=Path(__file__).resolve()
RUN=41629356922
JOB=125894837534
SOURCE="9b63803c29b00106e2eeb544b2387a6e8a8cba1f"
TREE="8baa0c39260b1bc23a181a1de0be4a6885f36cc1"
REFUSAL="379d5f2b8369bafbc4533526f0aa95505f9c252f85d43f79f45f2891b408b0eb"
def read(path):return json.loads(path.read_bytes())
def sha(path):
    with path.open("rb")as file:return hashlib.file_digest(file,"sha256").hexdigest()
def archive_member(archive,name):
    with archive.open(name)as file:return {"bytes":archive.getinfo(name).file_size,"sha256":hashlib.file_digest(file,"sha256").hexdigest()}
def verify(folder):
    failed=read(folder/"unpriced-original.json")
    assert sha(folder/"unpriced-original.json")==REFUSAL
    assert (failed["T_run"],failed["T_job"],failed["source"],failed["tree"],failed["runner_id"])==(RUN,JOB,SOURCE,TREE,2033)
    assert failed["performance_observations"]==0 and failed["eligible_for_performance"] is False
    reason=failed["first_failure"]
    assert reason["assertion"]=="matched and protected" and len(reason["direct_final_rlib_operands"])==4
    assert reason["actual_final_object_operands"]==259 and reason["direct_final_rlibs_matching_early_inode"]==[] and reason["original_held_supplier_rlibs"]==70
    assert len(reason["post_refusal_newly_run_native"])==10 and failed["mechanism"]["matched_local_R_slots"]==8047 and failed["mechanism"]["T_named_local_slots"]==0
    for key,file in (("original_service","service.json"),("physical_native_followup","native.json"),("two_way_physical_elf","cross-role.json"),("quarantine","quarantine.json")):
        path=folder/file;assert path.stat().st_size==failed[key]["bytes"] and sha(path)==failed[key]["sha256"]
    service=read(folder/"service.json");native=read(folder/"native.json")
    assert (service["run"],service["job"],service["job_conclusion"],service["eligible_for_performance"])==(RUN,JOB,"failure",False)
    assert service["numerical_samples"]==native["measurement_samples"]==0 and native["eligible_for_performance"] is False
    log=gzip.decompress((folder/"original-job-log.txt.gz").read_bytes())
    assert len(log)==service["job_log"]["bytes"] and hashlib.sha256(log).hexdigest()==service["job_log"]["sha256"] and b"assert matched and protected" in log
    qa,=[v for v in service["originals"].values() if v["id"]==13230695291]
    source_ownership=read(folder/"source-ownership.json")
    assert qa["bytes"]==(folder/"original-QA.zip").stat().st_size==4069503 and qa["sha256"]==sha(folder/"original-QA.zip")==source_ownership["service"]["sha256"]
    with ZipFile(folder/"original-QA.zip")as z:
        files=[i for i in z.infolist()if not i.is_dir()]
        assert len({i.filename for i in files})==len(files)==len(service["qa_members"])
        assert {i.filename:archive_member(z,i.filename)for i in files}==service["qa_members"]
        assert service["qa_members"]["driver-witness/capture.json"]["sha256"]==reason["actual_lld_and_cc_trace"]["sha256"]
    assert source_ownership["source_cargo_marks"]==70 and source_ownership["with_matching_object_name"]==69 and source_ownership["covering_observation_of_used_crate_source_inodes"] is False
    return {"run":RUN,"job":JOB,"runner_id":2033,"source":SOURCE,"tree":TREE,"old_qa":qa["sha256"],"refusal":REFUSAL,"retired_reason":"the earlier producer's final-LLD inode probe followed ThinLTO and could not qualify the pre-ThinLTO ownership decision","samples":0}
def retain(folder):
    parent=SCRIPT.parent.parent/"production-source/product-amendment"
    raw=parent/"completed-production/unpriced-original.json";j=read(raw);service=read(Path(j["original_service"]["path"]))
    folder.mkdir()
    shutil.copyfile(raw,folder/"unpriced-original.json")
    for key,file in (("original_service","service.json"),("physical_native_followup","native.json"),("two_way_physical_elf","cross-role.json"),("quarantine","quarantine.json")):
        shutil.copyfile(Path(j[key]["path"]),folder/file)
    qa,=[v for v in service["originals"].values()if v["id"]==13230695291]
    shutil.copyfile(Path(qa["path"]),folder/"original-QA.zip")
    shutil.copyfile(parent/"phase-observation/original.json",folder/"source-ownership.json")
    (folder/"original-job-log.txt.gz").write_bytes(gzip.compress(Path(service["job_log"]["path"]).read_bytes(),mtime=0))
    (folder/"retired-producer.py").write_bytes(SCRIPT.read_bytes())
    return verify(folder)
if __name__=="__main__":
    if len(sys.argv)==1:print(json.dumps(verify(SCRIPT.parent),sort_keys=True))
    elif sys.argv[1:]==["rehearse"]:
        with tempfile.TemporaryDirectory(dir=SCRIPT.parent)as tmp:print(json.dumps(retain(Path(tmp)/"original"),sort_keys=True))

