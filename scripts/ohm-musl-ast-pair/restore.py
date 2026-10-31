"""Reopen the authenticated source transfer at one stable ordinary rustup pathname."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
if "RUNNER_TEMP" in os.environ:
    os.environ.setdefault("QA_ROOT",str(Path(os.environ["RUNNER_TEMP"])/"ohm-aarch64-linux-zmij"))
import subjects as q

s=q.s
TMP=s.DEST/"reopened"
SDK=s.rt.SDK


def restore(role,run,head,id_,digest,seal):
    assert role in ("P","C") and len(head)==40 and len(digest)==len(seal)==64
    api=lambda path:json.loads(subprocess.check_output(["gh","api",s.API+path]))
    job=api(f"runs/{run}")
    assert (job["head_sha"],job["head_branch"],job["event"],job["run_attempt"])==(head,q.REF,"workflow_dispatch",1)
    assert (job["id"]==int(os.environ["GITHUB_RUN_ID"]) and job["status"]=="in_progress") or (job["status"],job["conclusion"])==("completed","success")
    sources=[j for j in api(f"runs/{run}/jobs?per_page=100")["jobs"] if j["name"]=="Build both source SDKs and run the compiler regression"]
    assert len(sources)==1 and sources[0]["head_sha"]==head and sources[0]["conclusion"]=="success"
    a=api(f"artifacts/{id_}")
    assert (a["name"],a["workflow_run"]["id"],a["workflow_run"]["head_sha"],a["digest"],a["expired"])==("musl-285-source-transfer",run,head,"sha256:"+digest,False)
    s.LOG.mkdir(parents=True);TMP.mkdir()
    zip_path=TMP/"products.zip"
    with zip_path.open("xb") as f:subprocess.run(["gh","api",s.API+f"artifacts/{id_}/zip"],stdout=f,check=True)
    assert s.sha(zip_path)==digest and zip_path.stat().st_size==a["size_in_bytes"]
    names={"identity.json","base-sdk.tar.zst","driver-C.zst","strict-cargo.zst","signed-cargo.zst"}
    with zipfile.ZipFile(zip_path) as z:
        assert sorted(z.namelist())==sorted(names) and z.testzip() is None
        z.extractall(TMP)
    u=json.loads((TMP/"identity.json").read_text())
    assert s.sha(TMP/"identity.json")==seal and (u["run"],u["head"],u["attempt"])==(run,head,1)
    assert u["source"]==q.SOURCE and u["base"]==q.PREVIOUS["files"] and u["candidate_driver"]!=u["base"][q.DRIVER]
    assert u["rustdoc"]["operational"]==u["base"]["bin/rustdoc"] and u["rustdoc"]["fresh_candidate"]==q.docaudit.C_DOC
    assert all(len(u["rustdoc"][k])==64 for k in ("comparison","four_native_combinations"))
    assert set(u["sha256"])==names-{"identity.json"} and all(v==[s.sha(TMP/n),(TMP/n).stat().st_size] for n,v in u["sha256"].items())
    SDK.mkdir(parents=True)
    seen=set()
    with subprocess.Popen(["zstd","-qdc",TMP/"base-sdk.tar.zst"],stdout=subprocess.PIPE) as proc:
        with tarfile.open(fileobj=proc.stdout,mode="r|") as archive:
            for m in archive:
                assert m.isfile() and m.name not in seen and m.name in u["base"]
                h,sz,mode=u["base"][m.name];assert (m.size,m.mode)==(sz,mode)
                f=SDK/m.name;f.parent.mkdir(parents=True,exist_ok=True)
                with f.open("xb") as out:shutil.copyfileobj(archive.extractfile(m),out,1024*1024)
                f.chmod(mode);assert s.sha(f)==h
                seen.add(m.name)
        assert not any(proc.stdout.read()) and proc.wait()==0
    assert seen==set(u["base"])
    raw=TMP/"physical";raw.mkdir()
    files={"P":(raw/"driver-P",u["base"][q.DRIVER],q.P),
           "C":(raw/"driver-C",u["candidate_driver"],q.C),
           "aware":(raw/"cargo-aware",u["base"]["bin/cargo"],q.AWARE)}
    os.link(SDK/q.DRIVER,files["P"][0]);os.link(SDK/"bin/cargo",files["aware"][0])
    def decode(code,source,row,rev):
        f=raw/code
        subprocess.run(["zstd","-qd",source,"-o",f],check=True);f.chmod(0o755)
        assert s.sha(f)==row[0]
        return f,row,rev
    files["C"]=decode("driver-C",TMP/"driver-C.zst",u["candidate_driver"],q.C)
    for name,(digest_,rev) in q.OLD.items():
        files[name]=decode("cargo-"+name,TMP/(name+"-cargo.zst"),[digest_],rev)
    guard={k:{"path":str(f),"sha256":r[0],"source":rev} for k,(f,r,rev) in files.items()}
    guard={"sdk":str(SDK),"frontend_sha256":u["base"]["bin/rustc"][0],"driver_basename":Path(q.DRIVER).name,
           "drivers":{n:guard[n] for n in "PC"},"cargos":{n:guard[n] for n in ("signed","strict","aware")}}
    s.save(s.LOG/"guard-subjects.json",guard)
    active=SDK/q.DRIVER;tmp=active.with_suffix(".installing")
    if not active.samefile(files[role][0]):
        os.link(files[role][0],tmp);tmp.replace(active)
    physical=q.inventory(SDK)
    assert physical==q.PREVIOUS["files"]|{q.DRIVER:files[role][1]}
    s.save(s.LOG/"sdk.json",{"source":q.SOURCE,"role":role,"installed":physical,
        "source_transfer":{"run":run,"head":head,"id":id_,"archive":digest,"identity":seal,"artifact_bytes":a["size_in_bytes"]}})
    return guard


if __name__=="__main__":
    restore(sys.argv[1],int(os.environ["SOURCE_RUN"]),os.environ["SOURCE_HEAD"],int(os.environ["TRANSFER_ID"]),
            os.environ["TRANSFER_DIGEST"].removeprefix("sha256:"),os.environ["TRANSFER_SEAL"])
