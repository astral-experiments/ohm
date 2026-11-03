"""Replay both original Actions archives offline with Python 3.11+."""
from pathlib import Path
import gzip,hashlib,json,sys,tempfile,zipfile
HERE=Path(__file__).resolve().parent
def get(p):return json.loads(p.read_bytes())
def file_sha(p):
    with p.open("rb")as f:return hashlib.file_digest(f,"sha256").hexdigest()
def main():
    m=get(HERE/"report.json");assert m["head"]=="c126e7b93092473f751185aa83d7f6c9712037aa" and m["protocol"]=="abf765213e8552d27727ec8a731ab29afff8c63c1912b72a0e777acbc287f723"
    with tempfile.TemporaryDirectory()as tmp:
        wd=Path(tmp);src=HERE/"worker.zip";assert file_sha(src)==m["worker_archive"]
        with zipfile.ZipFile(src)as a:
            assert len(set(a.namelist()))==len(a.namelist()) and all(k.startswith("scripts/")and ".." not in Path(k).parts for k in a.namelist());a.extractall(wd)
        n=wd/"scripts/driver-bind-21577";assert file_sha(n/"protocol.json")==m["protocol"]
        for ln in (n/"SHA256SUMS").read_text().splitlines():
            digest,k=ln.split("  ",1);assert Path(k).name==k and file_sha(n/k)==digest
        for k,oid in get(n/"donor.json")["files"].items():
            raw=(wd/k).read_bytes();assert hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()==oid
        mechanism=HERE/"mechanism";layout=get(n/"layout.json");plan=get(n/"protocol.json")
        for name,digest in m["mechanism_files"].items():assert Path(name).name==name and file_sha(mechanism/name)==digest
        patch=get(mechanism/"patch.json");assert patch["modifications"]==8733 and patch["prototype"]==plan["prototype"] and patch["original"]==plan["signed"] and patch["original_reconstructed"] is True
        for env in ("signed","prototype"):
            for pre in ("","-preload"):
                audit=json.loads(gzip.decompress((mechanism/("audit-"+env+pre+".json.gz")).read_bytes()))
                assert audit["all_slots"]==len(audit["normalized_loaded_slot"])==8733 and audit["all_exports"]==7516 and audit["all_slot_runtime_permissions"]==["r--p"] and audit["preload"]==bool(pre) and audit["driver"]==plan[env]
                assert audit["exported_override_won_in_RTLD_DEFAULT"]==bool(pre)
                owners=[row[-1]for row in audit["normalized_loaded_slot"]];assert set(owners)<= {"driver","override"} and owners.count("override")==int(bool(pre)and env=="signed")
        sys.path.insert(0,str(n));import replay
        h=get(n/"prior-hosts.json");boots=set(h["boot_uuids"]);ids=set(h["runner_ids"]);names=set(h["runner_names"]);prior=[];both={}
        assert len(boots)==41
        for label in ("first","independent"):
            item=m["hosts"][label];d=HERE/label
            for path,dig in item["files"].items():assert Path(path).name==path and file_sha(d/path)==dig
            service=get(d/"original-service.json");start=get(d/"original-run.json");job=get(d/"original-job.json");early=get(d/"boot-service.json");att=get(d/"boot-attestation.json");bd=d/"boot.zip";orig=d/"original.zip"
            assert service["workflow_run"]["id"]==early["workflow_run"]["id"]==start["id"]==job["run_id"]==att["run"]==item["run"]
            assert start["repository"]["private"] and start["actor"]["login"]==start["triggering_actor"]["login"]=="charliermarsh" and start["head_branch"]=="charlie/codex-21577-driver-binding-check" and start["event"]=="workflow_dispatch" and start["conclusion"]==job["conclusion"]=="success"
            assert start["repository"]["id"]==1319437234==service["workflow_run"]["repository_id"]==early["workflow_run"]["repository_id"] and start["run_attempt"]==job["run_attempt"]==1
            assert job["id"]==att["job"]==item["job"] and job["runner_id"]==att["runner_id"] and job["runner_name"]==att["runner_name"] and att["head"]==job["head_sha"]==service["workflow_run"]["head_sha"]==start["head_sha"]==m["head"]
            assert early["name"]==f"uv-21577-{label}-boot" and service["name"]==f"uv-21577-{label}-original" and service["id"]==item["original"]
            assert service["digest"]=="sha256:"+file_sha(orig) and service["size_in_bytes"]==orig.stat().st_size and early["digest"]=="sha256:"+file_sha(bd)
            with zipfile.ZipFile(bd)as z:assert z.namelist()==["boot-attestation.json"] and z.read("boot-attestation.json")==(d/"boot-attestation.json").read_bytes()
            assert att["series"]==label and att["prior_calibrated"]==prior and set(att["excluded"])==boots and set(att["excluded_ids"])==ids and set(att["excluded_names"])==names
            assert att["boot"] not in boots and att["runner_id"]not in ids and att["runner_name"]not in names
            boots.add(att["boot"]);ids.add(att["runner_id"]);names.add(att["runner_name"]);prior.append({"run":att["run"],"job":att["job"],"id":early["id"],"sha256":file_sha(bd)})
            v=replay.wheel(orig,att,m["head"]);assert v["run"]==item["run"] and v["primary_qualified"]==item["primary"] and v["pairs"]==item["pairs"] and v["endpoints"]==item["endpoints"];both[label]=v["primary_qualified"]
        assert all(both.values())==m["both_workers_qualified"];print(json.dumps({"series":both,"both_workers_qualified":all(both.values()),"primary":{k:m["hosts"][k]["endpoints"]["uv_warnings"]for k in both}},indent=1))
if __name__=="__main__":main()
