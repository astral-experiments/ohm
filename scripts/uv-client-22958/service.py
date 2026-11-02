"""Compare corrected stock, the stack through #328 and its direct #336 child on the same edit."""
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
component=m.read(HERE/"component-plan.json")
ROLES=("S","P","F")
SOURCES=lock["sources"]
ORDERS=component["orders"]
assert ORDERS==[list(row) for row in ("SPF","FPS","PFS","SFP","FSP","PSF","SPF","FPS")]
assert case["registered"]==lock["registration"]==m.filesha(HERE/"component-plan.json")=="5871772a0a844bd11c83c1326e2310bd1bf15f1b488d4e68fced3ad124d2c166"
assert lock["authority_prior"]==m.filesha(HERE/"registration.json")=="187a9ff09d03ce98eb5afecc31001db24147c51f9d08d1527b00cd97ef54d8b3"
assert lock["preceding_source_sha256"]==m.filesha(HERE/"preceding-material.json")==component["P_F_material_receipts"]["production/rehearsed-77ce-material.json"]
assert component["argv"]==register["argv"] and component["uv"]==[case["A"],case["B"]]
assert m.filesha(HERE/"clock-amendment.json")==lock["clock"] and m.filesha(HERE/"trigger-carrier-addendum.json")==lock["trigger"]
assert m.filesha(HERE/"prespecified-transfer.json") == register["authority_sha256"]
assert m.filesha(HERE/"eligibility-addendum.json") == register["eligibility_addendum"]
assert m.filesha(HERE/"replication-plan.json")==register["independent_replication"]
prior=m.read(HERE/"heldout-passed.json")
assert prior["primary_and_secondary"]==[True,True] and prior["raw_sha256"]==lock["heldout_original"]
assert SOURCES["S"]["commit"]==component["S"]["rust"] and SOURCES["P"]==component["P"] and SOURCES["F"]==component["F"]
assert set(SOURCES)==set(ROLES) and lock["signed_cargo"]==component["signed_minus22_cargo_sha256"]
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
    assert len(absent)==len(lock["excluded"])>=25 and all(str(uuid.UUID(x))==x for x in absent|{boot}) and boot not in absent
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
        release_intake.pinned_release(out/"fixed-release-after-study.json")
        import result
        result.close(out)
    else:raise ValueError(mode)
if __name__=="__main__":main(*sys.argv[1:])
