"""Reopen the single successful physical stage1 factory before touching a Ruff target."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BRANCH, CRATES, HERE, REPO, capsule, enrollment, need, save, sha, source_binding

FACTORY = 41475100027
FACTORY_QA = "c70846481f9b00d1b991275eb565e7bfd3a133c8"


def api(path, output=None):
    argv = ["gh", "api"]
    if output is not None:
        with output.open("xb") as f:
            subprocess.run([*argv, path], check=True, stdout=f)
        return
    return json.loads(subprocess.check_output([*argv, path]))


def archive(run, qa, name, dest, cap, *, current=False):
    meta = api(f"repos/{REPO}/actions/runs/{run}")
    terminal=meta["conclusion"] == "success"
    if current:
        need(int(os.environ["GITHUB_RUN_ID"])==run and os.environ["GITHUB_SHA"]==qa,"cannot bypass a previous workflow conclusion")
        terminal=meta["status"]=="in_progress" or terminal
    need(terminal and meta["head_sha"] == qa and meta["head_branch"] == BRANCH
         and meta["run_attempt"] == 1 and meta["event"] == "workflow_dispatch"
         and meta["head_repository"]["full_name"] == REPO, "wrong or incomplete immutable source workflow")
    rows = api(f"repos/{REPO}/actions/runs/{run}/artifacts?per_page=100")["artifacts"]
    candidates = [r for r in rows if r["name"] == name]
    need(len(candidates) == 1, "missing or ambiguous workflow artifact")
    row = candidates[0]
    need(not row["expired"] and row["workflow_run"]["id"] == run and 0 < row["size_in_bytes"] <= cap, "ineligible archive")
    need(shutil.disk_usage(dest.parent).free > (15 << 30) + row["size_in_bytes"], "original 15-GiB receiving reserve")
    api(f"repos/{REPO}/actions/artifacts/{row['id']}/zip", dest)
    need(dest.stat().st_size == row["size_in_bytes"] and row["digest"] == "sha256:" + sha(dest), "GitHub transport digest mismatch")
    return {k:row[k] for k in ("id","name","size_in_bytes","digest")}


def install(root, *, registration=None):
    # External QA may supply its independently authenticated, identical registration.
    reg = enrollment() if registration is None else registration
    need(reg == source_binding() and capsule.REG == reg and Path(capsule.HERE).resolve() == HERE,
         "receiver requires the exact enrolled Rust revisions and physical capsule implementation")
    need(int(os.environ["PLACEMENT_FACTORY"]) == FACTORY, "unscheduled SDK source")
    root.mkdir()
    outer = root / "actual-factory.zip"
    row = archive(FACTORY, FACTORY_QA, "placement-matched-stage", outer, 769 << 20)
    need(row["id"] == 13157906963 and row["size_in_bytes"] == 204868392 and
         row["digest"] == "sha256:41fd6d11cf5aeb578c73dbb93a7ac61cccd517c436f9b2e78aa987b290efd034",
         "different physical matched source factory archive")
    packed = root / "placement-sdk.tar.zst"
    with zipfile.ZipFile(outer) as z:
        need(sorted(z.namelist()) == ["placement-sdk.tar.zst","seal.json"] and z.getinfo("seal.json").file_size < 8192, "unexpected SDK transport layout")
        seal = json.loads(z.read("seal.json"))
        need(seal["factory_run"] == FACTORY and seal["qa"] == FACTORY_QA and seal["candidate"] == reg["roles"]["C"]["revision"]
             and seal["bytes"] == z.getinfo("placement-sdk.tar.zst").file_size < 768 << 20, "incorrect content address")
        with z.open("placement-sdk.tar.zst") as inp, packed.open("xb") as out:
            shutil.copyfileobj(inp,out)
    need(sha(packed) == seal["sha256"], "altered matched stage1 archive")
    names = set()
    total = 0
    with subprocess.Popen(["zstd","-qdc",packed],stdout=subprocess.PIPE) as proc:
        with tarfile.open(fileobj=proc.stdout,mode="r|") as tf:
            for item in tf:
                rel=Path(item.name)
                need(not rel.is_absolute() and ".." not in rel.parts and str(rel)==item.name and item.name not in names
                     and rel.parts[0] in ("capsule","documentation","logs"), "unsafe constructor member")
                names.add(item.name)
                where=root/rel
                if item.isdir():
                    where.mkdir(parents=True,exist_ok=True)
                    continue
                need(item.isreg() and 0<item.size<700<<20 and item.mode & 0o7000 == 0, "nonregular or oversized constructor member")
                total += item.size
                need(total<3<<30,"excess constructor archive")
                where.parent.mkdir(parents=True,exist_ok=True)
                with tf.extractfile(item) as inp, where.open("xb") as out:
                    shutil.copyfileobj(inp,out)
                where.chmod(item.mode&0o777)
        need(proc.wait()==0,"truncated compressed kit")
    logs=root/"logs"
    need(seal["factory"]==sha(logs/"factory.json"),"wrong factory result")
    factory=json.loads((logs/"factory.json").read_bytes())
    need(factory["roles"]==reg["roles"] and factory["qualified"]==sha(root/"capsule/qualified.json")
         and factory["registration"]==sha(HERE/"registration.json"),"source registration differs")
    capsule.reopen(root/"capsule",root/"parked")
    manifests=capsule.admit(root/"capsule")
    docs={}
    physical={}
    for role,label in (("P","normal"),("C","defer")):
        built=json.loads((logs/(role+"-constructed.json")).read_bytes())
        need(built["source"]==reg["roles"][role] and set(built["rustc_crates"])==set(CRATES)
             and all(built["rustc_crates"].values()) and built["cxx"]["OhmRegisterCoalescer.cpp"]
             and bool(built["cxx"]["OhmSourcePlacement.cpp"])==(role=="C")
             and sha(logs/(role+"-constructors.jsonl.gz"))==built["native_selection"],"incomplete physical compiler construction")
        park=root/"parked"/label
        doc=root/"documentation"/role/"rustdoc"
        proof=json.loads((logs/(role+"-docs.json")).read_bytes())
        need(proof["source"]==reg["roles"][role]["revision"] and proof["rustdoc"]==factory["docs"][role]
             and [sha(doc),doc.stat().st_size,stat.S_IMODE(doc.stat().st_mode)]==proof["rustdoc"],"incorrect role documentation")
        doc.chmod(0o555)
        d=root/"doc-products"/role
        d.mkdir(parents=True)
        os.link(doc,d/"rustdoc")
        os.link(doc,park/"bin/rustdoc")
        version=subprocess.check_output([park/"bin/rustdoc","-vV"],env={"PATH":"/usr/bin:/bin","LD_LIBRARY_PATH":str(park/"lib")},text=True)
        docs[role]=proof|{"version":version}
        driver=factory["physical"][role]["driver"]
        need(manifests[role][driver["member"]][0]==sha(park/driver["member"])==driver["sha256"],"different actual compiler DSO")
        physical[role]={"driver":driver["sha256"]}
    save(root/"source-qualification.json",{"factory_run":FACTORY,"factory_qa":FACTORY_QA,"archive":row,"seal":seal,"physical":physical,
         "source":reg["roles"],"qualified":sha(root/"capsule/qualified.json")})
    save(root/"docs-qualification.json",{"actual":docs})
    logs.rename(root/"source-receipts")


if __name__=="__main__":
    install(Path(sys.argv[1]))
