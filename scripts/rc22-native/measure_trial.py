"""Retain repeated unit decisions and output proofs for the prequalified and experimental Cargo binaries."""
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
import build_generator_trial as trial
import common
import native_generator_case
import sdk
import trace_execs
import trace_generator as control
from warm_ty import WARNING

def measure(out,kit,reported,role,reports):
    root=common.seed("ruff");source=root/"crates/ty_project/src/lib.rs";original=source.read_bytes()
    common.require(not common.git(root,"status","--porcelain"),"dirty Ruff")
    work=out/"current-work";work.mkdir()
    env=common.context(work,kit/"sdk")
    common.require(common.run(["cargo","+ohm","-Vv"],env=env)==reported["version_verbose"],"unmatched Cargo binary")
    cmd=["cargo","+ohm","check","-p","ty_project","--tests","--locked","--offline","-j4","--message-format=json"]
    subprocess.run(["cargo","+ohm","fetch","--locked","--target",common.GNU],cwd=root,env=env,check=True,stdout=subprocess.DEVNULL)
    results=[]
    try:
        for step in ("clean","edit","repeat1","repeat2","repeat3","observed"):
            if step=="edit":source.write_bytes(original+WARNING)
            launch=trace_execs.argv(cmd,work) if step=="observed" else cmd
            start=time.monotonic();proc=subprocess.run(launch,cwd=root,env=env,capture_output=True);elapsed=time.monotonic()-start
            if step=="observed":trace_execs.finish(work,reports)
            for key,b in (("stdout",proc.stdout),("stderr",proc.stderr)):(reports/(step+"."+key+".gz")).write_bytes(gzip.compress(b,mtime=0))
            proc.check_returncode()
            rows=[json.loads(l) for l in proc.stdout.splitlines()];assert rows[-1]=={"reason":"build-finished","success":True}
            artifacts=[r for r in rows if r["reason"]=="compiler-artifact"]
            warnings=[r["message"]["message"] for r in rows if r["reason"]=="compiler-message" and "OHM_QA_PRESERVED_WARNING" in r["message"]["message"]]
            assert bool(warnings)==(step!="clean") and len(artifacts)==303
            script,=[r for r in rows if r["reason"]=="build-script-executed" and "/ruff_unicode_names2#" in r["package_id"]]
            generated=Path(script["out_dir"]);files=control.generated(generated)
            assert {"generated.rs","generated_phf.rs","generated_alias.rs"}<=set(files)
            ns=next(p for p in generated.parents if p.parent.name=="workspaces")
            assert ns.is_relative_to(work)
            markers={str(p.relative_to(ns)):common.sha(p) for p in sorted(ns.rglob(".ohm-worktree-seed*")) if p.is_file()}
            result_records={str(p.relative_to(ns)):common.sha(p) for p in ns.rglob(".ohm-worktree-result-v1") if "ruff_unicode_names2" in str(p)}
            gen,=[r for r in artifacts if r["target"]["kind"]==["custom-build"] and "/ruff_unicode_names2#" in r["package_id"]]
            executables={str(Path(n).relative_to(work)):common.sha(n) for n in gen["filenames"] if Path(n).is_file()}
            dirty=[dict(package=r["package_id"],target=r["target"]["name"],kinds=r["target"]["kind"]) for r in artifacts if not r["fresh"]]
            result=dict(step=step,role=role,cargo_sha256=reported["sha256"],cargo_commit=reported["commit"],command=cmd,elapsed_s=elapsed,source_sha256=common.sha(source),warnings=warnings,units=len(artifacts),dirty=dirty,out_dir=str(generated),namespace=str(ns),markers=markers,result_records=result_records,generated=files,executables=executables)
            results.append(result);common.save(reports/(step+".json"),result)
            print(role,step,len(dirty),"dirty of 303",round(elapsed,3),"s",sorted(markers),len(result_records),flush=True)
    finally:
        source.write_bytes(original)
        work.rename(out/(role+"-finished-work"))
    return results

def main():
    tmp=Path(os.environ["RUNNER_TEMP"]);out=tmp/"generator-trial";out.mkdir()
    kit=out/"kit";donor=sdk.reopen(tmp/"rc22-inbox",kit)
    archive=tmp/"standalone.zip"
    assert common.host()==common.GNU and common.sha(archive)==control.FROZEN
    with zipfile.ZipFile(archive) as z:
        control_binary=z.read("rc22-cargo330/cargo");control_stamp=json.loads(z.read("rc22-cargo330/reports/candidate330.json"))
    assert control.digest(control_binary)==control.BINARY==control_stamp["sha256"] and control_stamp["commit"]==control.REV and control_stamp["driver"]==donor["rust"]["driver_sha256"]
    trial_stamp=trial.verify(common.read(trial.directory()/"reports/candidate330.json"),donor)
    paths={"control":(control_binary,control_stamp),"trial":((trial.directory()/"cargo").read_bytes(),trial_stamp)}
    results={}
    for role,(body,stamp) in paths.items():
        install=kit/"sdk/bin/cargo-generator-subject";install.write_bytes(body);install.chmod(0o755);install.replace(kit/"sdk/bin/cargo")
        assert common.sha(kit/"sdk/bin/cargo")==stamp["sha256"]
        reports=out/"reports"/role;reports.mkdir(parents=True);common.save(reports/"subject.json",stamp)
        results[role]=measure(out,kit,stamp,role,reports)
    common.save(out/"reports/ty-comparison.json",dict(job=common.job(),controls={k:[dict(step=q["step"],dirty=len(q["dirty"]),seconds=q["elapsed_s"]) for q in v] for k,v in results.items()}))
    # The control was already exercised on ordinary native links. The generator check is new for both binaries.
    for role,(body,stamp) in paths.items():
        if role=="control":continue
        install=kit/"sdk/bin/cargo-generator-subject";install.write_bytes(body);install.chmod(0o755);install.replace(kit/"sdk/bin/cargo")
        assert common.sha(kit/"sdk/bin/cargo")==stamp["sha256"]
        native_generator_case.exercise(out,kit/"sdk",role)
if __name__=="__main__":main()
