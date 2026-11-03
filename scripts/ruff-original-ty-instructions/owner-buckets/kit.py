"""Read immutable GitHub Actions kit/receipt pairs and validate the sealed compiler factory."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

REPO = "astral-experiments/ohm"
def acquire(w, binding):
    code=Path(os.environ["GITHUB_WORKSPACE"])/"factory-src/scripts/ruff-matched-stage"
    root=w.root/"owner-kit";root.mkdir()
    env=dict(os.environ,GH_TOKEN=os.environ["OHM_SDK_READ_TOKEN"])
    def gh(*args, **kw):
        return subprocess.run(["gh","api",f"repos/{REPO}/"+args[0]],check=True,env=env,**kw)
    def api(path):return json.loads(gh(path,capture_output=True).stdout)
    assert subprocess.check_output(["git","-C",code,"rev-parse","HEAD"],text=True).strip()==binding["head"]
    assert not subprocess.check_output(["git","-C",code,"status","--porcelain","--untracked-files=all"])
    run=binding["run"];r=api(f"actions/runs/{run}")
    assert [r["head_repository"]["full_name"],r["head_branch"],r["head_sha"],r["event"],r["run_attempt"],r["conclusion"]]==[REPO,binding["branch"],binding["head"],"workflow_dispatch",1,"success"]
    assets={v["name"]:v for v in api(f"actions/runs/{run}/artifacts")["artifacts"]}
    for key in ("receipts","kit"):
        name,identifier,size,sha=binding[key];actual=assets[name];path=root/(key+".zip")
        assert [actual["id"],actual["size_in_bytes"],actual["digest"],actual["expired"],actual["workflow_run"]["id"]]==[identifier,size,"sha256:"+sha,False,run]
        assert 0<size<500*2**20
        with path.open("xb")as output:gh(f"actions/artifacts/{identifier}/zip",stdout=output,timeout=600)
        assert path.stat().st_size==size and w.hf(path)==sha
    with zipfile.ZipFile(root/"receipts.zip")as z:
        def record(name):
            assert z.getinfo(name).file_size<8*2**20
            return json.loads(z.read(name))
        reg=record("registration.json");accepted=record("accepted.json");smoke=record("smoke.json")
        assert z.read("registration.json")== (code/"registration.json").read_bytes() and accepted["registration"]==w.hf(code/"registration.json")
        assert {role:row["revision"] for role,row in reg["roles"].items()}==binding["source"]
        assert set(smoke["arms"])=={"normal","defer"} and all(x["invalid"]=="E0308" for x in smoke["arms"].values())
        epochs=record("bucket-epochs.json");assert set(epochs)=={"PC","CP"} and not any(v["simulated"]for v in epochs.values())
        expected=z.read("archive.sha256").decode()
        assert re.fullmatch(r"[0-9a-f]{64}  matched-stage\.tar\.zst\s*",expected)
        docs={s:record(s+".json")for s in ("P","C")};w.put(w.proof/"factory-consumed.json",dict(binding=binding,source=reg["roles"],qualified=accepted,epochs=epochs,smoke=smoke,drivers={s:next(v[0] for k,v in row["files"].items()if k.startswith("lib/librustc_driver-") and k.endswith(".so"))for s,row in docs.items()}))
    packed=root/"kit.tar.zst"
    with zipfile.ZipFile(root/"kit.zip") as z:
        assert z.namelist()==["matched-stage.tar.zst"] and z.getinfo("matched-stage.tar.zst").file_size<500*2**20
        with z.open("matched-stage.tar.zst") as source,packed.open("xb") as output:shutil.copyfileobj(source,output,2**20)
    assert w.hf(packed)==expected.split()[0]
    (root/"capsule/objects").mkdir(parents=True);seen=set();total=0
    with subprocess.Popen(["zstd","-qdc",packed],stdout=subprocess.PIPE) as dec:
        with tarfile.open(fileobj=dec.stdout,mode="r|") as tf:
            for item in tf:
                n=item.name.rstrip("/")
                if n in ("capsule","capsule/objects"):
                    assert item.isdir();continue
                assert (n in ("capsule/C.json","capsule/P.json","capsule/qualified.json") or re.fullmatch(r"capsule/objects/[0-9a-f]{64}",n)) and item.isfile() and n not in seen and 0<item.size<700*2**20 and 0<item.mode<=0o777
                total+=item.size;assert total<5200*2**20
                dest=root/n
                with tf.extractfile(item) as source,dest.open("xb")as target:shutil.copyfileobj(source,target,2**20)
                os.chmod(dest,item.mode);seen.add(n)
        assert dec.wait()==0
    assert all(json.loads((root/f"capsule/{s}.json").read_bytes())==docs[s] for s in docs)
    spec=importlib.util.spec_from_file_location("signed_source_kit",code/"capsule.py")
    decoder=importlib.util.module_from_spec(spec);spec.loader.exec_module(decoder)
    manifest=decoder.reopen(root/"capsule",root/"reopened")
    for role,label in (("P","normal"),("C","defer")):
        sdk=Path(manifest["arms"][label]["root"]);assert w.hf(sdk/"bin/cargo")==w.hf(w.sdk/"bin/cargo")
        driver,=(sdk/"lib").glob("librustc_driver-*.so");assert w.hf(driver)==binding["driver"][role]
    return {s:Path(manifest["arms"][label]["root"])for s,label in (("P","normal"),("C","defer"))}
