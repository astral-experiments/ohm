"""Exercise the two independently built providers at identical canonical scratch paths."""
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"ruff-indexed-check-pmu"))
from acquire import LOG, REG, ROOT, need, json_save

work = ROOT / "provider-work"
installed = json.loads((LOG/"compiler-installations.json").read_bytes())["arms"]
results = {}
for role, label in (("P","normal"),("C","defer")):
    arm=installed[label]
    sha,=[v for k,v in arm["files"].items() if k.startswith("lib/librustc_driver-") and k.endswith(".so")]
    commit=REG["compiler_parent" if role=="P" else "compiler_candidate"]
    out=LOG/("provider-"+role)
    subprocess.run([sys.executable,"-IB",HERE/"providers/verify_owner.py","--sdk-root",arm["root"],
                    "--factory-receipts",ROOT/"factory-receipts.zip","--expect-commit",commit,
                    "--expect-driver-sha256",sha,"--work",work,"--out",out],check=True)
    result=json.loads((out/"terminal.json").read_bytes())
    need(result["success"] and result["commit"]==commit and result["rustc_driver"]==sha
         and result["state_count"]==11 and result["independent_histories"]==2,"incomplete provider proof")
    results[role]=result
    if work.exists():
        need(not work.is_symlink() and work.parent==ROOT and not (ROOT/("done-"+role)).exists(),"scratch moved")
        work.rename(ROOT/("done-"+role))
need(results["P"]["states"].keys()==results["C"]["states"].keys(),"different tested provider states")
json_save(LOG/"accepted-providers.json",dict(head=os.environ["REVIEWED_HEAD"],results=results))
