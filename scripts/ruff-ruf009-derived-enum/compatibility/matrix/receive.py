"""Reopen the two exact independently completed compiler factories and three physical clients."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run as m
sys.path.insert(0, str(HERE.parents[2]/"ruff-linter-check-attribution"))
import scope_matched as scope

w = scope.w
root = Path(os.environ["RUNNER_TEMP"])/"ruf009-v5-native"
root.mkdir()
w.BRANCH = "charlie/qa-ruf009-consumed-native-20261103"
w.ROOT = root
w.OUT = root / "source-receipts"
w.OUT.mkdir()
w.checked_head()
w.resources()

for person, binding in m.REG["factory"].items():
    scope.kit(person, binding)
    with zipfile.ZipFile(root/("scope-kit-"+person)/"receipts.zip") as z:
        for role,n in [("P","parent"),("C","candidate")]:
            import hashlib
            raw = z.read("scope-evidence-"+n+".tar.gz")
            assert hashlib.sha256(raw).hexdigest() == binding["guard_archives"][role]

clients = {}
for role, binding in m.REG["clients"].items():
    run = scope.api("actions/runs/"+str(binding["run"]))
    assert [run["head_repository"]["full_name"],run["head_sha"],run["event"],run["run_attempt"],run["conclusion"]] == [w.REPO,binding["head"],"workflow_dispatch",1,"success"]
    artifact = scope.api("actions/artifacts/"+str(binding["id"]))
    assert [artifact["workflow_run"]["id"],artifact["name"],artifact["size_in_bytes"],artifact["digest"],artifact["expired"]] == [binding["run"],binding["name"],binding["bytes"],"sha256:"+binding["sha256"],False]
    zpath = root/(role+".zip")
    with zpath.open("xb") as target:
        subprocess.run(w.gh("actions/artifacts/"+str(binding["id"])+"/zip"),stdout=target,check=True,timeout=300)
    assert zpath.stat().st_size == binding["bytes"] and m.sha(zpath) == binding["sha256"]
    product = root/("cargo-"+role)
    with zipfile.ZipFile(zpath) as z:
        assert z.namelist().count(binding["product"])==1 and z.getinfo(binding["product"]).file_size == binding["binary_bytes"]
        with z.open(binding["product"]) as src, product.open("xb") as out:
            shutil.copyfileobj(src,out)
    assert m.sha(product) == binding["binary"]
    product.chmod(0o755)
    identity=subprocess.check_output([product,"-Vv"],text=True)
    assert "commit-hash: "+binding["source"] in identity, (role,identity)
    m.write(w.OUT/(role+"-cargo.json"), {"source":binding,"identity":identity,"actual":m.sha(product)})
    clients[role] = product
    zpath.unlink()
alias=w.WS/"alias/scripts/ruff-join-proof/evidence/reader"
assert w.git(alias,"rev-parse","HEAD")==m.REG["reader"] and not w.git(alias,"status","--porcelain","--untracked-files=all")
current=root/"scope-kit-current/reopened"
early=root/"scope-kit-early/reopened"
subprocess.run([sys.executable,"-IB",HERE/"run.py","--root",root/"matrix","--p2",current/"normal","--q2",current/"defer",
                "--q1",early/"defer","--early",clients["early"],"--current",clients["current"],"--fixed",clients["fixed"],
                "--b3sum",shutil.which("b3sum"),"--alias-source",alias],check=True)
