"""Enforce the corrected stock and full production comparison on one genuine edited Cargo check."""
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
register=m.read(HERE/"registration.json")
case=m.read(HERE/"case.json")
lock=m.read(HERE/"release-lock.json")
ROLES=("S","F")
SOURCES=lock["sources"]
ORDERS=register["orders"]
assert ORDERS==[["S","F"],["F","S"],["F","S"],["S","F"],["F","S"],["S","F"],["S","F"],["F","S"]]
assert case["registered"]==lock["registration"]==m.filesha(HERE/"registration.json")=="d3044a1fdf0d4c244095e43e4d7fba0bdfff26041a0f1db92f0f0b09aa296b73"
assert m.filesha(HERE/"clock-amendment.json")==lock["clock"] and m.filesha(HERE/"trigger-carrier-addendum.json")==lock["trigger"]
assert m.filesha(HERE/"prespecified-transfer.json") == register["authority_sha256"]
assert m.filesha(HERE/"eligibility-addendum.json") == register["eligibility_addendum"]
prior=m.read(HERE/"heldout-passed.json")
assert prior["primary_and_secondary"]==[True,True] and prior["raw_sha256"]==lock["heldout_original"]
assert {k:w["commit"] for k,w in SOURCES.items()}=={"S":"10d56274a98801b5ef8f80aab734e835749458e1","F":"ac67101cb973e35ce8ff044cc8014c2c76bab69e"}
m.P.update(branch=case["branch"],roles=SOURCES)
old.P["edited_workspace_roster"]=["uv_client","uv_configuration"]
CHECK=old.CHECK=[str(m.SDK/"bin/cargo"),*register["argv"][1:]]
assert CHECK[1:]==["check","-p","uv-client","--locked","--offline","-j8"]
m.ENV.update(LC_ALL="C",GIT_CONFIG_NOSYSTEM="1",GIT_CONFIG_GLOBAL="/dev/null",GIT_ALLOW_PROTOCOL="file",GIT_NO_LAZY_FETCH="1",RUSTC_BOOTSTRAP="1")
m.ENV.pop("CARGO_TERM_COLOR",None)

def host():
    w,t=m.host();co=w/"coordinator";e=os.environ
    assert e["GITHUB_REPOSITORY_ID"]=="1319437234" and e["RELEASE_LOCK"]==m.filesha(HERE/"release-lock.json")
    assert m.sha_git(co,"rev-parse","HEAD").decode().strip()==e["REVIEWED_HEAD"] and m.sha_git(co,"rev-parse","HEAD^").decode().strip()==case["parent"]
    absent={r["boot"] for r in lock["excluded"].values()};boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    assert len(absent)==len(lock["excluded"])>=16 and all(str(uuid.UUID(x))==x for x in absent|{boot}) and boot not in absent
    assert e["EXCLUDED_PRODUCTION_BOOT"]==lock["boot_list_sha256"]==m.digest(("\n".join(sorted(absent))+"\n").encode())
    assert e["BUILD_RUN_ID"]==str(lock["production_compiler"]["run"]) and e["BUILD_HEAD"]==lock["production_compiler"]["coordinator"]
    return w,t,boot

def compact_host():
    w,t,_=host()
    return w,t

old.host=compact_host

def main(mode):
    w,tmp,boot=host();out=w/"trait-results"
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
        m.save(out/"boot-attestation.json",dict(boot=boot,workspace=str(w),excluded=sorted(x["boot"]for x in lock["excluded"].values()),
              run=int(os.environ["GITHUB_RUN_ID"]),coordinator=os.environ["REVIEWED_HEAD"],inherited=m.filesha(out/"calibration.json"),
              threads=m.filesha(out/"per-rustc-calibration/calibration.json"),blocking=m.filesha(where/"verified.json"),
              affinity=sorted(mask),registered=case["registered"],release_lock=m.filesha(HERE/"release-lock.json")))
    elif mode in ("admit","migration"):
        import release_intake
        getattr(release_intake,mode)()
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
