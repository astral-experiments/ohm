"""Compare the unchanged, warned ty check with the exact two Cargo readers on Linux."""
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parent))
import campaign
import candidate330
import common
import sdk

WARNING = b'\n#[deprecated(note = "OHM_QA_PRESERVED_WARNING")]\nconst OHM_QA_OLD_CONST: u8 = 17;\n#[warn(deprecated)]\nconst _: u8 = OHM_QA_OLD_CONST;\n'
def main(bundle):
    root = Path(os.environ["RUNNER_TEMP"])/"rc22-ty"
    root.mkdir()
    receipts = root/"receipts"
    receipts.mkdir()
    kit = root/"kit"
    donor = sdk.reopen(bundle, kit)
    active = candidate330.enroll(kit, donor, receipts)
    repo = common.seed("ruff")
    source = repo/"crates/ty_project/src/lib.rs"
    original = source.read_bytes()
    common.require(common.host()==common.GNU and not common.git(repo,"status","--porcelain"), "wrong Ruff checkout")
    summaries = {}
    args = ["cargo","+ohm","check","-p","ty_project","--tests","--locked","--offline","-j4","--message-format=json"]
    try:
        for role in ("pinned",candidate330.ROLE):
            work = root/"work"
            work.mkdir()
            env = common.context(work,kit/"sdk")
            campaign.switch(kit,role,kit/"sdk",active)
            common.require(common.run(["cargo","+ohm","-Vv"],env=env) == active["cargos"][role]["version_verbose"], "wrong reader")
            dest = receipts/role
            dest.mkdir()
            subprocess.run(["cargo","+ohm","fetch","--locked","--target",common.GNU],cwd=repo,env=env,check=True)
            for step in ("clean","edit","repeat"):
                if step == "edit":
                    source.write_bytes(original + WARNING)
                stamp = time.monotonic()
                raw = subprocess.run(args,cwd=repo,env=env,capture_output=True)
                elapsed = time.monotonic()-stamp
                for stream,body in (("stdout",raw.stdout),("stderr",raw.stderr)):
                    (dest/(step+"."+stream+".gz")).write_bytes(gzip.compress(body,mtime=0))
                raw.check_returncode()
                rows=[json.loads(s) for s in raw.stdout.splitlines()]
                common.require(rows[-1]=={"reason":"build-finished","success":True}, "missing Cargo completion")
                artifacts=[r for r in rows if r["reason"]=="compiler-artifact"]
                diagnostics=[r["message"] for r in rows if r["reason"]=="compiler-message"]
                warnings=[m["message"] for m in diagnostics if "OHM_QA_PRESERVED_WARNING" in m["message"]]
                common.require(bool(warnings)==(step!="clean") and len(artifacts)>250, "wrong workload or diagnostics")
                dirty=sorted(r["target"]["name"] for r in artifacts if not r["fresh"])
                summary=dict(role=role,step=step,command=args,elapsed_s=elapsed,units=len(artifacts),dirty=dirty,warnings=warnings,source=common.sha(source),lock=common.sha(repo/"Cargo.lock"),cargo=active["cargos"][role]["sha256"])
                common.save(dest/(step+".json"),summary)
                if step=="repeat":summaries[role]=summary
            source.write_bytes(original)
            work.rename(root/("finished-"+role))
        pinned,candidate=summaries.values()
        for key in ("units","warnings","source","lock","command"):
            common.require(pinned[key]==candidate[key],("unmatched ty check",key))
        common.save(receipts/"complete.json",summaries)
        print("dirty units on the repeat", {r:len(v["dirty"]) for r,v in summaries.items()})
    finally:
        source.write_bytes(original)

if __name__=="__main__":
    main(Path(sys.argv[1]))
