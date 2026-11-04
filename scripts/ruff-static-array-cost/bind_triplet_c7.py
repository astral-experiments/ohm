"""Bind only the registered successful C7 factory transport after an independent SDK readback."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile

kit = Path(__file__).resolve().parent
args = argparse.ArgumentParser(description=__doc__)
args.add_argument("record",type=Path,help="Independently qualified transport record, including SDK tar and driver SHA")
args.add_argument("--gh-auto",required=True)
a=args.parse_args()
assert __debug__
registration=json.loads((kit/"registration.json").read_bytes())
transports=kit/"transports.json"
roles=json.loads(transports.read_bytes());assert roles["C7"] is None
c=json.loads(a.record.read_bytes());arm=registration["compiler_arms"]["C7"]
assert c["run"] == arm["factory_run"] and c["qa"] == arm["factory_head"]
assert all(c[k] == roles["C5"][k] == roles["F5"][k] for k in ("config","script"))
def call(path,*opts):
    return subprocess.check_output([a.gh_auto,"api",*opts,"repos/astral-experiments/ohm/actions/"+path],cwd=kit)
def official(path):return json.loads(call(path))
run=official(f"runs/{c['run']}");job=official(f"jobs/{c['job']}")
assert run["run_attempt"]==1 and run["event"]=="workflow_dispatch" and run["head_sha"]==c["qa"]
assert run["status"]==job["status"]=="completed" and run["conclusion"]==job["conclusion"]=="success"
assert job["head_sha"]==c["qa"] and job["run_id"]==c["run"] and job["run_attempt"]==1
for kind in ("qualification","sdk"):
    ident,digest=c[kind];m=official(f"artifacts/{ident}")
    assert not m["expired"] and m["digest"]=="sha256:"+digest and m["workflow_run"]["head_sha"]==c["qa"]
    assert m["workflow_run"]["id"]==c["run"]
    if kind=="qualification":
        # The archive also carries the three independently runnable native guards.
        assert 0 < m["size_in_bytes"] < 4*1024*1024
        raw=call(f"artifacts/{ident}/zip","--allow-escape-sequences")
        assert len(raw)==m["size_in_bytes"] and hashlib.sha256(raw).hexdigest()==digest
        with ZipFile(io.BytesIO(raw))as z:
            assert len(z.namelist()) == len(set(z.namelist()))
            assert sum(i.file_size for i in z.infolist()) < 32*1024*1024
            assert all(z.getinfo(name).file_size < 64*1024 for name in (
                "source.json", "sdk.json", "training.json", "sdk-sha256", "bootstrap.toml"))
            assert z.testzip() is None
            src=json.loads(z.read("source.json"));sdk=json.loads(z.read("sdk.json"));trained=json.loads(z.read("training.json"))
            assert src["role"]==arm["factory_role"] and src["source"]==arm["source"] and src["tree"]==arm["tree"]
            assert src["factory"]==c["qa"] and int(src["run"])==c["run"]
            assert sdk["driver"]==c["driver"] and sdk["role"]==arm["factory_role"] and arm["source"] in sdk["versions"]["rustc"]
            assert registration["cargo"] in sdk["versions"]["cargo"] and z.read("sdk-sha256").decode().strip()==c["tar"]
            assert trained["config"]==c["config"]==hashlib.sha256(z.read("bootstrap.toml")).hexdigest()
            assert trained["script"]==c["script"] and set(trained["profiles"])=={"rustc","rustdoc","clippy","rustfmt"}
            assert all(len(h)==64 and n>0 for h,n in trained["profiles"].values())
    else:assert 0<m["size_in_bytes"]<900*2**20
roles["C7"]={k:c[k]for k in ("run","qa","job","qualification","sdk","tar","driver","script","config")}
transports.write_text(json.dumps(roles,sort_keys=True,indent=2)+"\n")
print("Bound the C7 source, driver, training recipe, full SDK hash and both Actions originals. No dispatch.")
