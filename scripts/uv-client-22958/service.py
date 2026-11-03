"""Compare a signed or matched-corrected -23 compiler with the remaining rustc changes."""
from pathlib import Path
import json
import os
import subprocess
import sys
import uuid

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"uv-callables-21041"))
import core as old
sys.path.insert(0,str(HERE))
m=old.m
import split_binding as binding
import split_host

register=m.read(HERE/"prospective-23.json")
case=m.read(HERE/"case.json")
split_register=m.read(HERE/"split-prospective.json")
assert m.filesha(HERE/"split-prospective.json")==binding.REGISTRATION
pair=m.read(HERE/"split-pair.json")
assert m.filesha(HERE/"split-pair.json")==binding.NATIVE_PAIR
CONTRAST=os.environ["UV_22958_CONTRAST"]
LOCK_PATH=HERE/"signed-23-split-lock.json"
lock=m.read(LOCK_PATH)
assert m.filesha(HERE/"prospective-23.json")==binding.PROSPECTIVE
assert m.filesha(HERE/"r2-amendment.json")==binding.AMENDMENT
assert m.filesha(HERE/"signed-23-split-choice.json")==lock["choice_sha256"]==binding.CHOICE
choice=m.read(HERE/"signed-23-split-choice.json")
CONTROL,ORDERS=binding.select(lock,register,m.read(HERE/"r2-amendment.json"),choice,split_register,pair,CONTRAST)
binding.require_media(lock)
ROLES=(CONTROL,"F")
SOURCES=lock["sources"]
assert case["A"]==register["input"]["A"] and case["B"]==register["input"]["B"]
assert m.filesha(HERE/"original-registry-22958.json")==register["input"]["registry"]
assert m.filesha(HERE/"original-source-22958.json")==register["input"]["source_sha256"]
source_record=m.read(HERE/"original-source-22958.json")
registry_record=m.read(HERE/"original-registry-22958.json")
assert m.filesha(HERE/"edit.patch")==case["source_patch"]==source_record["patch_sha256"]
assert registry_record["source"]==register["input"]["source_sha256"]
assert [entry["path"] for entry in source_record["files"]]==case["files"]==source_record["B"]["changed"]
assert {state:source_record[state]["tree"] for state in ("A","B")}==case["trees"]
case.update(registered=binding.REGISTRATION, branch=lock["branch"], parent=lock["parent"])
m.P.update(branch=case["branch"],roles=SOURCES,signed_cargo_sha256=lock["signed_cargo"])
old.P["edited_workspace_roster"]=["uv_client","uv_configuration"]
CHECK=old.CHECK=[str(m.SDK/"bin/cargo"),*register["argv"][1:]]
assert CHECK[1:]==["check","-p","uv-client","--locked","--offline","-j8"]
m.ENV.update(LC_ALL="C",GIT_CONFIG_NOSYSTEM="1",GIT_CONFIG_GLOBAL="/dev/null",GIT_ALLOW_PROTOCOL="file",GIT_NO_LAZY_FETCH="1",RUSTC_BOOTSTRAP="1")
m.ENV.pop("CARGO_TERM_COLOR",None)

def host():
    w,t=m.host();co=w/"coordinator";e=os.environ
    assert e["GITHUB_REPOSITORY_ID"]=="1319437234" and e["RELEASE_LOCK"]==m.filesha(LOCK_PATH)
    assert m.sha_git(co,"rev-parse","HEAD").decode().strip()==e["REVIEWED_HEAD"] and m.sha_git(co,"rev-parse","HEAD^").decode().strip()==case["parent"]
    boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    assert str(uuid.UUID(boot))==boot and boot not in split_host.baseline(lock)
    return w,t,boot

def compact_host():
    w,t,_=host()
    return w,t

old.host=compact_host

def main(mode):
    w,tmp,boot=host();out=w/"trait-results"
    if mode=="placement":
        import release_intake
        return split_host.record(w,boot,CONTRAST,lock,m.filesha(LOCK_PATH),binding.REGISTRATION,release_intake.transport(),m.save)
    placement=split_host.verify_placement(m.read(out/"placement.json"),CONTRAST,lock,m.filesha(LOCK_PATH),binding.REGISTRATION)
    assert placement["contrast"]==CONTRAST and placement["control"]==CONTROL and placement["treatment"]=="F"
    assert placement["coordinator"]==os.environ["REVIEWED_HEAD"] and placement["run"]==int(os.environ["GITHUB_RUN_ID"])
    assert placement["boot"]==boot and boot not in placement["excluded"] and placement["release_lock"]==m.filesha(LOCK_PATH)
    if mode=="calibrate":
        m.pmu(w,tmp)[0].calibrate()
        cal=m.read(out/"calibration.json");assert cal["ready"]["boot"]==boot and cal["unmultiplexed_calibration_clocks"]==28
        mask=set(cal["ready"]["affinity"]);assert len(mask)==8 and mask<=os.sched_getaffinity(0)
        os.sched_setaffinity(0,mask)
        import scoped
        scoped.calibrate()
        where=out/"blocking-clock-pre";subprocess.run([sys.executable,"-ISBu",HERE/"clock-check.py",where],check=True)
        admit=m.read(where/"verified.json")
        assert admit["eligible_blocking_calibration"] and admit["boot"]==boot and admit["affinity"]==sorted(mask)
        m.save(out/"boot-attestation.json",dict(placement,workspace=str(w),placement_sha256=m.filesha(out/"placement.json"),
              inherited=m.filesha(out/"calibration.json"),threads=m.filesha(out/"per-rustc-calibration/calibration.json"),
              blocking=m.filesha(where/"verified.json"),affinity=sorted(mask)))
    elif mode=="admit":
        import release23_package
        release23_package.admit()
    elif mode=="migration":
        import release_intake
        release_intake.migration()
    elif mode=="study":
        import native
        native.run()
    elif mode=="reduce":
        import release_intake
        release_intake.latest(out/"latest-after-study.json")
        import result
        result.close(out)
    else:raise ValueError(mode)
if __name__=="__main__":main(*sys.argv[1:])
