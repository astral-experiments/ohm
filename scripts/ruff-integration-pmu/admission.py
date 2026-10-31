"""Reopen the independently admitted unscored structure job before enrolling a new boot."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

HERE=Path(__file__).resolve().parent
RUN=41227421360
JOB=124614372056
HEAD="0b6d516c86350e5a00af5db8cd0b04871d5de106"
ART=13052154384
SIZE=239193166
SHA="cbe8a61f3efdb85a06ed0de95ce05649c1dfebe3402b89afd6582de68c491bb3"
REPO="astral-experiments/ohm"
ARMS=("Foff","Fon")
VISITS=("cold-A","first-B","return-A","return-B","unchanged-B","invalid","repair")


def need(ok,message):
    if not ok:raise ValueError(str(message))


def canonical_hash(data):
    value=(json.dumps(data,sort_keys=True,separators=(",",":"))+"\n").encode()
    return hashlib.sha256(value).hexdigest()


def project(original):
    original.seek(0)
    with zipfile.ZipFile(original) as z:
        read=lambda path:json.loads(gzip.decompress(z.read(path)) if path.endswith(".gz") else z.read(path))
        registration=read("enrollment.json"); verified=read("independent-readback.json")
        need(registration["head"]==verified["head"]==HEAD and registration["run"]==RUN and
             verified=={"head":HEAD,"clocks":0,"intentional_errors":2,"structural_cargo_invocations":18,
                        "unique_full_elf_bodies":8,"valid":16,"verified":True}, "changed structural gate")
        complete=read("complete.json");need(complete["qualified"] and complete["clocks"]==0 and len(complete["histories"])==14,"source structure terminal")
        expected={}
        for a in ARMS:
            for v in VISITS:
                prefix=f"history/{a}/{v}/"
                r=read(prefix+"visit.json"); typed=read(prefix+"roster.json.gz")
                item={k:r[k] for k in ("code","typed","distinct_dirty","full","link_only","wild")}
                item.update(typed_sha256=canonical_hash(typed["units"]),dirty_sha256=canonical_hash(typed["dirty"]))
                if v!="invalid":
                    o=read(prefix+"libtest.json");need(o["total"]==o["passed"]==96,"missing full native suite")
                    item["test_inventory"]=o["inventory"];item["typed_layout"]=r["typed_layout"]
                expected[a+"/"+v]=item
        return {"original":{"run":RUN,"job":JOB,"head":HEAD,"artifact":ART,"bytes":SIZE,"sha256":SHA},
                "boot":registration["boot"],"source":registration["f"],"cargo":registration["cargo"],
                "wild":registration["wild"],"argv":registration["argv"],"structural":expected}


def qualify():
    api=lambda p:json.loads(subprocess.check_output(["gh","api",f"repos/{REPO}/actions/{p}"]))
    r=api(f"runs/{RUN}");j=api(f"jobs/{JOB}");a=api(f"artifacts/{ART}")
    need((r["head_sha"],r["run_attempt"],r["conclusion"],r["head_branch"])==
         (HEAD,1,"success","charlie/qa-ruff-integration-structure-20261031"),"wrong source admission run")
    need((j["run_id"],j["head_sha"],j["name"],j["conclusion"])==(RUN,HEAD,"Structural F Ruff integration test","success"),
         "wrong native GNU job")
    need((a["id"],a["name"],a["workflow_run"]["id"],a["workflow_run"]["head_sha"],a["expired"],a["size_in_bytes"],a["digest"])==
         (ART,"ruff-integration-structure",RUN,HEAD,False,SIZE,"sha256:"+SHA),"wrong official archive")
    with tempfile.TemporaryFile() as raw:
        subprocess.run(["gh","api",f"repos/{REPO}/actions/artifacts/{ART}/zip"],stdout=raw,check=True,timeout=600)
        need(raw.tell()==SIZE,"wrong ZIP length");raw.seek(0)
        need(hashlib.file_digest(raw,"sha256").hexdigest()==SHA,"wrong original bytes")
        observed=project(raw)
    need(observed==json.loads((HERE/"structure.json").read_bytes()),"different actual graph, compilers, links or tests")
    return observed
