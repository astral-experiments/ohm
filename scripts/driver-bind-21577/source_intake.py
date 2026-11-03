"""Verify the production-build artifact and install the signed Cargo for all three toolchains."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from zipfile import ZipFile

from common21577 import HERE, PLAN, ENV, blob, read, save, sha, SDK
from media import Transport
import source_sdk_extract

ROLES = ("S", "R", "T")
PRODUCERS = {role: PLAN["producers"][role] for role in ("R", "T")}
SOURCE = {role: producer["sha"] for role, producer in PRODUCERS.items()}
TREES = {role: producer["tree"] for role, producer in PRODUCERS.items()}
SIGNED_CARGO = "f7cfe387ec3bd7e2e367d80596f379349faa23530194bf7cd7ba80a33adc6dee"
REPO = "astral-experiments/ohm"

def file_record(p):
    return [*blob(p), p.stat().st_mode & 0o777]

def verified_run(lock):
    records={}
    for role,src in lock["roles"].items():
        owner=src["run"];head=src["coordinator"];path=f"repos/{REPO}/actions/runs/{owner}"
        run=Transport.gh_json("api",path)
        jobs=Transport.gh_json("api",path+"/jobs?per_page=100")
        arts=Transport.gh_json("api",path+"/artifacts?per_page=100")
        assert run["id"]==owner and run["head_sha"]==head and run["head_branch"]==src["branch"]
        assert run["event"]=="workflow_dispatch" and run["run_attempt"]==1 and run["path"]==".github/workflows/ci.yml"
        assert run["status"]=="completed" and run["conclusion"]==src["run_conclusion"] in ("success","failure")
        assert run["actor"]["login"]==run["triggering_actor"]["login"]=="charliermarsh"
        assert run["repository"]["private"] and run["repository"]["id"]==run["head_repository"]["id"]==PLAN["repo_id"]
        assert jobs["total_count"]==len(jobs["jobs"]) and arts["total_count"]==len(arts["artifacts"])
        job,=[j for j in jobs["jobs"] if j["id"]==src["job"]]
        assert job["run_id"]==owner and job["head_sha"]==head and job["status"]=="completed" and job["conclusion"]=="success" and job["runner_id"]==src["runner_id"]
        for flavor in ("sdk","qa"):
            want=src[flavor];item,=[a for a in arts["artifacts"]if a["id"]==want["id"]]
            assert item["name"]==want["name"] and item["size_in_bytes"]==want["bytes"] and item["digest"]=="sha256:"+want["sha256"]
            assert not item["expired"] and item["workflow_run"]["id"]==owner and item["workflow_run"]["head_sha"]==head
        records[role]={"run":run,"job":job,"artifacts":arts}
    return records

def fetch(item,out):
    assert len(item["sha256"])==64 and item["bytes"]>0
    dest=out/(str(item["id"])+".zip")
    Transport.gh_bytes(f"repos/{REPO}/actions/artifacts/{item['id']}/zip",dest,item["bytes"],item["sha256"])
    return dest

def unwrap(path,rows):
    with ZipFile(path) as z:
        allfiles=[x for x in z.infolist()if not x.is_dir()]
        assert len(allfiles)==len({x.filename for x in allfiles}) and sum(x.file_size for x in allfiles)<4<<30
        for name,(size,digest) in rows.items():
            with z.open(name) as f: actual=hashlib.file_digest(f,"sha256").hexdigest()
            assert z.getinfo(name).file_size==size and actual==digest,(name,actual,digest)

def unpack_role(archives,out,audit,role,locked):
    out.mkdir()
    for flavor,path in archives.items():unwrap(path,locked["members"][flavor])
    with ZipFile(archives["sdk"]) as z,z.open(locked["archive_member"]) as src,(out/"ohm.tar.gz").open("xb")as dest:
        shutil.copyfileobj(src,dest,1<<20)
    assert blob(out/"ohm.tar.gz")==[locked["archive_bytes"],locked["archive_sha256"]]
    for key in ("source","role"):
        flavor,name=locked[key+"_member"]
        with ZipFile(archives[flavor]) as z: data=z.read(name)
        assert hashlib.sha256(data).hexdigest()==locked[key+"_sha256"]
        (audit/(role+"-"+key+".json")).write_bytes(data)
    product=read(audit/(role+"-role.json"));src=read(audit/(role+"-source.json"))
    assert src["role"]==product["role"]==role and src["coordinator"]==locked["coordinator"]
    assert src["commit"]==locked["source_commit"]==SOURCE[role] and src["tree"]==locked["source_tree"]==TREES[role]
    assert product["source_sha256"]==locked["source_sha256"] and product["archive_sha256"]==locked["archive_sha256"]
    assert product["effective_cargo"]["sha256"]==SIGNED_CARGO and product["execution_pgo"]=="verified executed PGO profile coverage for rustc, rustdoc, Cargo, Clippy, rustfmt, and cargo-fmt"
    installed=out/"extracted";installed.mkdir()
    tree,inventory=source_sdk_extract.extract(out/"ohm.tar.gz",installed);inv=read(inventory)
    assert sha(inventory)==product["sdk_inventory_sha256"]==locked["inventory_sha256"]
    assert sha(installed/"component-inventory.json")==locked["component_inventory_sha256"]
    driver,=[n for n in inv if n.startswith("lib/librustc_driver-")and n.endswith(".so")]
    assert len(inv)==142 and inv[driver]["sha256"]==locked["driver_sha256"]
    for name in ("sdk-inventory.json","component-inventory.json"):shutil.copyfile(installed/name,audit/(role+"-"+name))
    return tree,inv

def prepare(out,tmp):
    import sys
    sys.path.insert(0,str(HERE.parent/"uv-client-22958"))
    import os
    os.environ.setdefault("UV_22958_CONTRAST","signed")
    import release23_package,release_intake
    lock=read(HERE/"source-sdk-lock.json")
    assert lock["source_disposition"]["eligible_for_performance"]
    qualified = lock["source_disposition"]["qualified_regressions"]
    service_members = lock["roles"]["T"]["members"]["qa"]
    observed = lock["source_disposition"]["pre_ThinLTO"]
    assert observed["service_record"]==service_members["source-observation.json"][1] and observed["qa"]==lock["roles"]["T"]["qa"]["sha256"]
    assert (observed["source_observed_run"],observed["source_observed_job"])==(lock["roles"]["T"]["run"],lock["roles"]["T"]["job"])
    assert observed["matches"]>0 and observed["protected"]>0 and observed["late_objects"]>0 and observed["producer_rustc"]!=observed["final_lld"]
    assert observed["retired_original"]=="379d5f2b8369bafbc4533526f0aa95505f9c252f85d43f79f45f2891b408b0eb"
    assert qualified["service_link_modes"] == service_members["link-modes.json"][1]
    assert qualified["service_linker_executions"] == service_members["linker-executions.json"][1]
    assert set(lock["roles"])=={"R","T"} and all(lock["roles"][r]["source_commit"]==SOURCE[r]for r in ("R","T"))
    for role, producer in PRODUCERS.items():
        actual = lock["roles"][role]
        assert actual["source_tree"] == producer["tree"]
        assert all(actual[key] == producer[key] for key in ("run", "coordinator", "job"))
    assert lock["refusals"] and lock["performance_samples"]==0 and sha(HERE/"source-sdk-pair.json")==lock["pair_sha256"]
    pair=read(HERE/"source-sdk-pair.json")
    assert pair["performance_samples"]==0 and pair["physical_local_functions"]>1000 and pair["foreign_functions_still_named"]>5
    for role in ("R","T"):
        probe=pair["role_preload_proof"][role]
        assert probe["foreign_override"] and probe["compiler_override"]==(role=="R") and pair["frozen_source_commit"][role]==SOURCE[role]
    audit=out/"intake";audit.mkdir()
    transfer=tmp/"driver-binding-transfer";transfer.mkdir()
    pool=tmp/"driver-binding-sdks";pool.mkdir()
    save(audit/"source-producer-service.json",verified_run(lock))
    shutil.copyfile(HERE/"source-sdk-pair.json",audit/"pair.json")
    official=release23_package.official(Transport,audit,transfer)
    release_intake.install_archive(official,pool/"S","R")
    registered=release_intake.role_sdk("R",pool/"S",audit/"signed")
    assert registered["runtime"]==read(HERE/"signed-native.json")["runtime"] and registered["source"]==read(HERE/"signed-native.json")["source"]
    for role in ROLES:
        if role=="S":
            inv=read(HERE/"signed-sdk.json")
            assert sha(pool/"S/bin/cargo")==SIGNED_CARGO
        else:
            locked=lock["roles"][role];paths={n:fetch(locked[n],transfer)for n in ("sdk","qa")}
            tree,inv=unpack_role(paths,transfer/role,audit,role,locked)
            tree.rename(pool/role)
            shutil.copyfile(pool/"S/bin/cargo",pool/role/"bin/cargo")
            assert sha(pool/role/"bin/cargo")==SIGNED_CARGO
        effective={n:[v["bytes"],v["sha256"],v["mode"]]for n,v in inv.items()}
        effective["bin/cargo"]=file_record(pool/"S/bin/cargo")
        save(audit/("effective-"+role+".json"),effective)

def check(role,expected,source=None):
    assert role in ROLES and not any(p.is_symlink() for p in SDK.rglob("*"))
    actual={str(p.relative_to(SDK)):file_record(p) for p in SDK.rglob("*") if p.is_file()}
    assert actual==expected and len(actual)==142 and actual["bin/cargo"][1]==SIGNED_CARGO
    banners={n:subprocess.check_output([SDK/"bin"/n,"-vV"],env=ENV,text=True).strip()for n in ("rustc","cargo")}
    assert banners["cargo"]==read(HERE/"signed-native.json")["banners"]["cargo"].strip()
    assert "commit-hash: "+(source or SOURCE.get(role,SOURCE["R"])) in banners["rustc"].splitlines()
    assert subprocess.check_output([SDK/"bin/rustc","--print","sysroot"],env=ENV,text=True).strip()==str(SDK)
    libs=subprocess.check_output(["ldd",SDK/"bin/rustc"],env=ENV,text=True)
    assert "not found" not in libs
    entry,=[line for line in libs.splitlines()if "librustc_driver-" in line]
    driver=Path(entry.split("=>")[1].split()[0]).resolve()
    llvm_entry,=[line for line in libs.splitlines()if "libLLVM.so." in line]
    llvm=Path(llvm_entry.split("=>")[1].split()[0]).resolve()
    assert driver.parent==llvm.parent==SDK/"lib" and llvm.name=="libLLVM.so.23.1-rust-1.99.0-beta"
    return {"role":role,"driver":actual[str(driver.relative_to(SDK))][1],"cargo":actual["bin/cargo"][1],"count":len(actual),
            "full_members":actual,"native_banners":banners,"loaded_driver":str(driver),"loaded_llvm":str(llvm),"llvm":actual[str(llvm.relative_to(SDK))][1]}

