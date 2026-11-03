"""Replay both original Actions archives offline with Python 3.11+."""
from pathlib import Path
import gzip,hashlib,json,sys,tempfile,zipfile
HERE=Path(__file__).resolve().parent
def get(p):return json.loads(p.read_bytes())
def file_sha(p):
    with p.open("rb")as f:return hashlib.file_digest(f,"sha256").hexdigest()
def main():
    m=get(HERE/"report.json");assert m["head"]=="294569f5daebcdd802ac0bcf7c7ea32dc3e3149e" and m["protocol"]=="ea6faf491a4b6875f2bc1ecd94b60bfa1471a0685d8d44a1d5b01049663a2109"
    with tempfile.TemporaryDirectory()as tmp:
        wd=Path(tmp);src=HERE/"worker.zip";assert file_sha(src)==m["worker_archive"]
        with zipfile.ZipFile(src)as a:
            assert len(set(a.namelist()))==len(a.namelist()) and all(k.startswith("scripts/")and ".." not in Path(k).parts for k in a.namelist());a.extractall(wd)
        n=wd/"scripts/driver-bind-21577";assert file_sha(n/"protocol.json")==m["protocol"]
        for ln in (n/"SHA256SUMS").read_text().splitlines():
            digest,k=ln.split("  ",1);assert Path(k).name==k and file_sha(n/k)==digest
        for k,oid in get(n/"donor.json")["files"].items():
            raw=(wd/k).read_bytes();assert hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()==oid
        mechanism=HERE/"mechanism";plan=get(n/"protocol.json");lock=get(n/"source-sdk-lock.json");pair=get(n/"source-sdk-pair.json")
        assert file_sha(n/"source-sdk-pair.json")==lock["pair_sha256"] and pair["performance_samples"]==lock["performance_samples"]==0
        for name,digest in m["mechanism_files"].items():
            assert name==Path(name).name and file_sha(mechanism/name)==digest
        previous=get(mechanism/"mechanism-only-lock.json")
        assert not previous["source_disposition"]["eligible_for_performance"] and previous["performance_samples"]==0
        assert file_sha(mechanism/"mechanism-only-lock.json")==lock["earlier_mechanism_lock"]
        earlier=get(mechanism/"mechanism-only-opening.json")
        assert earlier["total_source_prices"]==0 and earlier["source_commits"]["T"]==previous["roles"]["T"]["source_commit"]!=lock["roles"]["T"]["source_commit"]
        assert lock["source_disposition"]["eligible_for_performance"] and lock["source_disposition"]["qualified_regressions"]
        qualified = get(mechanism/"qualified-regressions.json")
        bound = lock["source_disposition"]["qualified_regressions"]
        treatment = lock["roles"]["T"]
        assert file_sha(mechanism/"qualified-regressions.json") == bound["sha256"]
        assert qualified["run"] == treatment["run"] and qualified["job"] == treatment["job"] and qualified["performance_samples"] == 0
        assert qualified["treatment"] == treatment["source_commit"] and qualified["tree"] == treatment["source_tree"]
        assert qualified["source_pack"] == lock["source_packet"] == file_sha(mechanism/"corrected-P.pack")
        assert qualified["source_role"] == file_sha(mechanism/"corrected-P.json")
        candidate = get(mechanism/"corrected-candidate.json")
        assert candidate["source"] == qualified["treatment"] and candidate["tree"] == qualified["tree"]
        retired_dir=HERE/"earlier-source-identical-producer"
        retired=__import__("runpy").run_path(str(retired_dir/"retired-producer.py"))["verify"](retired_dir)
        old=get(mechanism/"corrected-producer.json");new=get(mechanism/"observed-producer.json")
        assert retired["source"]==old["source"]==new["source"]==qualified["treatment"] and retired["tree"]==new["tree"]==qualified["tree"]
        assert (retired["run"],retired["job"])==(old["run"],old["job"]) and new["run"]!=old["run"] and new["job"]!=old["job"]
        assert (new["run"],new["job"])==(qualified["run"],qualified["job"]) and new["retired_original"]==retired["refusal"] and retired["samples"]==0
        original_phase=HERE/"source-observation"
        source=__import__("runpy").run_path(str(original_phase/"phase-originals.py"))["verify"](original_phase)
        assert (source["coordinator"],source["run"],source["job"],source["source"])==(new["coordinator"],qualified["run"],qualified["job"],qualified["treatment"])
        assert source["actual"]["qa"]==treatment["qa"]["sha256"] and source["actual"]["service_record"]==treatment["members"]["qa"]["source-observation.json"][1]
        assert all(lock["source_disposition"]["pre_ThinLTO"][k]==v for k,v in source["actual"].items())
        assert qualified["source_observation"]==file_sha(mechanism/"intake-source-observation.json")
        assert qualified["service_source_observation"]==source["actual"]["service_record"]
        assert qualified["previous_same_source_refusal"]==retired["refusal"]
        assert qualified["service_installed_native_sha256"]==file_sha(mechanism/"service-installed-native.json")==treatment["members"]["qa"]["installed-native.json"][1]
        assert candidate["patch"] == file_sha(mechanism/"corrected-P.patch") and candidate["patch_same_tree"]
        assert candidate["source_pack"] == lock["source_packet"] and candidate["earlier_mechanism_lock"] == qualified["previous_mechanism_only_pair"] == lock["earlier_mechanism_lock"]
        for key, name, member in (("service_native_link_modes","service-link-modes.json","link-modes.json"),("service_native_mode_media","service-link-mode-media.json","link-modes/accepted.json"),("service_linker_executions","service-linker-executions.json","linker-executions.json")):
            assert qualified[key] == file_sha(mechanism/name) == treatment["members"]["qa"][member][1]
        assert bound["service_link_modes"] == qualified["service_native_link_modes"] and bound["service_linker_executions"] == qualified["service_linker_executions"]
        assert qualified["service_phase_replay"] == bound["phase_replay"] == file_sha(mechanism/"service-phase-replay.json")
        assert qualified["local_installed_native_replay"] == bound["installed_mode_replay"] == file_sha(mechanism/"local-native-replay.json")
        assert qualified["local_reopened_control"] == file_sha(mechanism/"control-original-reopened.json")
        for key in ("sdk","qa"):
            assert all(qualified["service_"+key][k] == v for k,v in treatment[key].items())
        fixed=get(mechanism/"source-revision-before-price.json");assert fixed["source_prices_opened"]==0
        assert all(plan[k]==v for k,v in fixed["registered_metrics_and_order"].items())
        assert file_sha(mechanism/"cross-role.json")==pair["original_independent_sha256"]
        native=get(mechanism/"actual-shared-preload.json")
        assert file_sha(mechanism/"actual-shared-preload.json")==pair["shared_native_sha256"]
        packed=mechanism/"actual-shared-functions.json.gz";raw=gzip.decompress(packed.read_bytes());rows=json.loads(raw)
        assert file_sha(packed)==pair["actual_map"]["sha256"] and hashlib.sha256(raw).hexdigest()==pair["actual_map"]["raw_sha256"]
        local=[r for r in rows if r[2]=="physical-local"];protected=[r for r in rows if r[2]=="typed-exception"]
        assert len(local)+len(protected)==len(rows)==len({r[0]for r in rows})==len({r[1]for r in rows})
        assert len(local)==pair["physical_local_functions"]>1000 and all(r[3]>0 and r[4]==0 for r in local)
        assert sum(r[4]>0 for r in protected)==pair["foreign_functions_still_named"]>5
        for role,item in lock["roles"].items():
            assert pair["frozen_source_commit"][role]==item["source_commit"]==plan["producers"][role]["sha"]
            assert file_sha(mechanism/(role+"-role.json"))==item["role_sha256"] and file_sha(mechanism/(role+"-source.json"))==item["source_sha256"]
            real=get(mechanism/(role+"-role.json"));assert real["driver"]["sha256"]==item["driver_sha256"] and real["archive_sha256"]==item["archive_sha256"]
            assert native[role]["preloaded"]["compiler"]["overridden"]==(role=="R") and native[role]["preloaded"]["foreign"]["overridden"]
        local_open=get(mechanism/"production-opening.json");assert local_open["total_source_prices"]==0 and local_open["driver"]["T"]==lock["roles"]["T"]["driver_sha256"]
        assert all(x=={"rmeta":39,"sidecars":30,"workspace":4}for x in local_open["S_and_R_byte_identical"].values())
        sys.path.insert(0,str(n));import replay
        h=get(n/"prior-hosts.json");boots=set(h["boot_uuids"]);ids=set(h["runner_ids"]);names=set(h["runner_names"]);prior=[];both={}
        assert len(boots)>=43;packets={}
        for label in ("first","independent"):
            item=m["hosts"][label];d=HERE/label
            for path,dig in item["files"].items():assert Path(path).name==path and file_sha(d/path)==dig
            service=get(d/"original-service.json");start=get(d/"original-run.json");job=get(d/"original-job.json");early=get(d/"boot-service.json");att=get(d/"boot-attestation.json");bd=d/"boot.zip";orig=d/"original.zip"
            assert service["workflow_run"]["id"]==early["workflow_run"]["id"]==start["id"]==job["run_id"]==att["run"]==item["run"]
            assert start["repository"]["private"] and start["actor"]["login"]==start["triggering_actor"]["login"]=="charliermarsh" and start["head_branch"]=="charlie/codex-21577-driver-source-check" and start["event"]=="workflow_dispatch" and start["conclusion"]==job["conclusion"]=="success"
            assert start["repository"]["id"]==1319437234==service["workflow_run"]["repository_id"]==early["workflow_run"]["repository_id"] and start["run_attempt"]==job["run_attempt"]==1
            assert job["id"]==att["job"]==item["job"] and job["runner_id"]==att["runner_id"] and job["runner_name"]==att["runner_name"] and att["head"]==job["head_sha"]==service["workflow_run"]["head_sha"]==start["head_sha"]==m["head"]
            assert early["name"]==f"uv-21577-{label}-boot" and service["name"]==f"uv-21577-{label}-original" and service["id"]==item["original"]
            assert service["digest"]=="sha256:"+file_sha(orig) and service["size_in_bytes"]==orig.stat().st_size and early["digest"]=="sha256:"+file_sha(bd)
            with zipfile.ZipFile(bd)as z:assert z.namelist()==["boot-attestation.json"] and z.read("boot-attestation.json")==(d/"boot-attestation.json").read_bytes()
            assert att["series"]==label and att["prior_calibrated"]==prior and set(att["excluded"])==boots and set(att["excluded_ids"])==ids and set(att["excluded_names"])==names
            assert att["boot"] not in boots and att["runner_id"]not in ids and att["runner_name"]not in names
            boots.add(att["boot"]);ids.add(att["runner_id"]);names.add(att["runner_name"]);prior.append({"run":att["run"],"job":att["job"],"id":early["id"],"sha256":file_sha(bd)})
            packets[label]=(orig,att)
        openings={label:replay.wheel(orig,att,m["head"],native_only=True) for label,(orig,att)in packets.items()}
        assert openings==get(HERE/"native-admitted.json") and all(len(v["native_receipts"])==27 for v in openings.values())
        wall={}
        for label,(orig,att)in packets.items():
            v=json.loads(json.dumps(replay.wheel(orig,att,m["head"])));item=m["hosts"][label]
            assert v["run"]==item["run"] and v["primary_qualified"]==item["primary"] and v["whole_wall_2x"]==item["wall_2x"] and v["pairs"]==item["pairs"] and v["comparisons"]==item["comparisons"]
            both[label]=v["primary_qualified"];wall[label]=v["whole_wall_2x"]
        assert all(both.values())==m["both_workers_qualified"] and all(wall.values())==m["whole_wall_2x"]
        out={label:{contrast:{name:round(100*value["paired_median_reduction"],5)for name,value in endpoints.items()}for contrast,endpoints in row["comparisons"].items()}for label,row in m["hosts"].items()}
        print(json.dumps({"terminal_rustc_20_percent":both,"whole_Cargo_wall_2x":wall,"median_reductions_percent":out},indent=1))
if __name__=="__main__":main()
