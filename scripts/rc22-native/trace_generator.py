"""Trace the generator and its consumers on the exact published #330 qualification binary."""
import collections
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
import common
import sdk
from warm_ty import WARNING

REV = "8269d772aa1ef02e5efaa331dfb40eb55d71f719"
FROZEN = "f54d8da43340a9317ce26a8cbd2279b68702fa33bf406929caca5660258cf600"
BINARY = "3e6948caba617c5f776641df2ade87fe772d0b656a53b538cd93b63351c56c53"
def digest(data):return hashlib.sha256(data).hexdigest()
def generated(out):
    return {str(f.relative_to(out)): dict(sha256=common.sha(f),mode=f.stat().st_mode,mtime=f.stat().st_mtime_ns) for f in sorted(out.rglob("*")) if f.is_file()}

def main():
    tmp=Path(os.environ["RUNNER_TEMP"])
    out=tmp/"generator-recheck";out.mkdir()
    reports=out/"reports";reports.mkdir()
    kit=out/"kit";donor=sdk.reopen(tmp/"rc22-inbox",kit)
    archive=tmp/"standalone.zip"
    common.require(common.host()==common.GNU and common.sha(archive)==FROZEN,"wrong archived GNU control")
    with zipfile.ZipFile(archive) as z:
        binary=z.read("rc22-cargo330/cargo");stamp=json.loads(z.read("rc22-cargo330/reports/candidate330.json"))
    common.require(digest(binary)==BINARY==stamp["sha256"] and stamp["commit"]==REV and stamp["driver"]==donor["rust"]["driver_sha256"],"wrong native subjects")
    install=kit/"sdk/bin/cargo-generator-control"
    install.write_bytes(binary);install.chmod(0o755);install.replace(kit/"sdk/bin/cargo")
    work=out/"work";work.mkdir();env=common.context(work,kit/"sdk")
    common.require(common.run(["cargo","+ohm","-Vv"],env=env)==stamp["version_verbose"],"wrong installed reader")
    root=common.seed("ruff");source=root/"crates/ty_project/src/lib.rs";original=source.read_bytes()
    assert not common.git(root,"status","--porcelain")
    args=["cargo","+ohm","check","-p","ty_project","--tests","--locked","--offline","-j4","--message-format=json"]
    subprocess.run(["cargo","+ohm","fetch","--locked","--target",common.GNU],cwd=root,env=env,check=True)
    try:
        previous=None
        for step in ("clean","edit","repeat","trace"):
            if step=="edit":source.write_bytes(original+WARNING)
            e=dict(env)
            a=args
            if step=="trace":
                e.update(CARGO_LOG="cargo::compiler::fingerprint=trace,cargo::compiler=info")
                a=[*args,"-vv"]
            start=time.monotonic();proc=subprocess.run(a,cwd=root,env=e,capture_output=True);elapsed=time.monotonic()-start
            for name,data in (("stdout",proc.stdout),("stderr",proc.stderr)):(reports/(step+"."+name+".gz")).write_bytes(gzip.compress(data,mtime=0))
            proc.check_returncode()
            rows=[json.loads(l) for l in proc.stdout.splitlines()];assert rows[-1]=={"reason":"build-finished","success":True}
            artifacts=[r for r in rows if r["reason"]=="compiler-artifact"]
            warnings=[r["message"]["message"] for r in rows if r["reason"]=="compiler-message" and "OHM_QA_PRESERVED_WARNING" in r["message"]["message"]]
            assert bool(warnings)==(step!="clean") and len(artifacts)==303
            scripts=[r for r in rows if r["reason"]=="build-script-executed" and "/ruff_unicode_names2#" in r["package_id"]]
            script,=scripts;od=Path(script["out_dir"]);outputs=generated(od)
            assert {"generated.rs","generated_phf.rs","generated_alias.rs"}<=set(outputs)
            namespaces=work/"shared"/"workspaces"
            markers=[str(f.relative_to(namespaces)) for f in namespaces.rglob(".ohm-worktree-seed*") if f.is_file()]
            artifact,=[r for r in artifacts if r["target"]["kind"]==["custom-build"] and "/ruff_unicode_names2#" in r["package_id"]]
            executables={name:common.sha(name) for name in artifact["filenames"] if Path(name).is_file()}
            records=[str(f.relative_to(work)) for f in (work/"shared").rglob(".ohm-worktree-result-v1") if "ruff_unicode_names2" in str(f)]
            dirty=[dict(package=r["package_id"],target=r["target"]["name"],kinds=r["target"]["kind"]) for r in artifacts if not r["fresh"]]
            info=dict(step=step,command=a,elapsed_s=elapsed,source=common.sha(source),warnings=warnings,units=len(artifacts),dirty=dirty,script=script,outputs=outputs,executables=executables,markers=sorted(markers),result_records=records,job=common.job(),cargo=BINARY)
            common.save(reports/(step+".json"),info)
            if previous is not None and step in ("repeat","trace"):
                identical=all(previous["outputs"][name]["sha256"]==v["sha256"] for name,v in outputs.items()) and set(previous["outputs"])==set(outputs)
                print(step,len(dirty),round(elapsed,3),"generated files byte-identical",identical,"generator executable unchanged",executables==previous["executables"],"markers",sorted(Path(n).name for n in markers),"result records",len(records),flush=True)
            previous=info
    finally:source.write_bytes(original)
if __name__=="__main__": main()
