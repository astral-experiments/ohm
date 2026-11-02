"""Price ordinary package test builds after authenticating separate complete signed references."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import price
import reference
import study
from factory import need,save,sha


def get_bank(root):
    record=json.loads((HERE/"official-test-reference.json").read_bytes())
    run=price.api("actions/runs/"+str(record["run"]));art=price.api("actions/artifacts/"+str(record["artifact"]))
    job=price.api("actions/jobs/"+str(record["job"]))
    need(job["id"]==record["job"] and job["run_id"]==record["run"] and job["head_sha"]==record["head"] and
         job["conclusion"]=="success" and art["name"]=="ruff-example-replay-harness-signed-reference" and
         run["conclusion"]=="success" and run["run_attempt"]==1 and run["head_sha"]==record["head"] and
         run["event"]=="workflow_dispatch" and art["workflow_run"]["id"]==record["run"] and
         art["digest"]=="sha256:"+record["sha256"] and not art["expired"],"completed signed reference enrollment")
    archive=root/"signed-reference.zip"
    with archive.open("xb")as f:
        subprocess.run(["gh","api","repos/astral-experiments/ohm/actions/artifacts/"+str(record["artifact"])+"/zip"],
                       stdout=f,check=True)
    need(sha(archive)==record["sha256"],"authentic original signed reference")
    with ZipFile(archive)as z:
        load=lambda n:json.loads(z.read(n+".json"))
        terminal=load("terminal");families=load("families");cases=load("reference-cases")
        need(terminal["head"]==record["head"] and int(terminal["run"])==record["run"] and
             load("registered-cause")==json.loads((HERE/"official-wild-cause.json").read_bytes()),
             "bound source/causal gate")
        all_shas={h for state in families.values()for group in state.values()for h in group}
        need(all_shas==set(terminal["objects"]),"every physical reference object admitted and used")
        for digest in sorted(all_shas):
            data=subprocess.check_output(["zstd","-qdc"],input=z.read("reference-objects/"+digest+".zst"))
            need(hashlib.sha256(data).hexdigest()==digest and len(data)==terminal["objects"][digest]["size"],
                 "actual complete signed ELF bytes")
    archive.unlink()
    return {"record":record,"families":families,"cases":cases,"terminal":terminal}


def main():
    ws=Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True);head=os.environ["GITHUB_SHA"]
    need(os.environ["GITHUB_REPOSITORY"]=="astral-experiments/ohm" and os.environ["GITHUB_REF"]==study.BRANCH
         and os.environ["GITHUB_RUN_ATTEMPT"]=="1" and os.environ["REVIEWED_HEAD"]==head and
         os.environ["PRICE_SCOPE"]=="confirm-tests","registered nonrelease tests")
    for d,h in (("enrolled",head),("historical",study.RENDERER)):
        need(subprocess.check_output(["git","-C",ws/d,"rev-parse","HEAD"]).decode().strip()==h,"source registration")
    sys.path.insert(0,str(ws/"historical/scripts/gnu-example-ceiling"))
    import workload as w
    import pmu
    position=int(os.environ["POSITION"]);need(1<=position<=6,"registered position")
    root=Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)/"ruff-example-price";root.mkdir()
    out=root/"evidence";out.mkdir()
    admission=price.admit_worker(out,head,position,"confirm-tests")
    bank=get_bank(root)
    need(admission["boot"]!=bank["terminal"]["boot"],"separate signed reference boot")
    save(out/"signed-reference.json",bank)
    binaries=price.enroll(root,ws,out,json.loads((HERE/"official-pilot.json").read_bytes()))
    cpus=admission["affinity"][:4];need(len(cpus)==4,"matched four cores");os.sched_setaffinity(0,cpus)
    bins=pmu.compilers(root);pmu.calibration(bins,out)
    study.select(root,binaries,"parent")
    src=w.source(root);env=w.env_for(root);seed=w.prepare_registry(root,src,env,out)
    reference.prepare_runtime(root,env,seed,w)
    need("WILD_FILES_PER_GROUP" not in env and not env.get("RUSTFLAGS"),"ordinary unmodified measured environment")
    outcomes=[]
    def validate(state,paths,images,where):
        refs=bank["families"][state]
        need(set(images)==set(refs) and all(v[0]in refs[k]for k,v in images.items()),("exact signed full ELF membership",state))
        actual={k:[path,*images[k][:2]]for k,path in paths.items()if k in refs}
        cases=reference.outcomes(root,src,env,where/(state+"-real-tests"),actual,state)
        normalized=json.loads(json.dumps(cases))
        need(normalized==bank["cases"][state],("actual signed test verdicts",state))
        save(where/(state+"-validated.json"),{"images":{k:v[:2]for k,v in sorted(images.items())},"verdicts":normalized})
        w.sources(src,"old"if state=="old"else "corrected")
    arm_order=["parent","candidate"] if position%2 else ["candidate","parent"]
    for repeat,order in enumerate((arm_order,arm_order[::-1])):
        for arm in order:
            label=f"tests-{repeat}-{arm}";dest=out/label
            row=price.history(root,src,env,dest,w,seed,binaries,bins/"plain",arm,"tests",inspect=repeat==0,validate=validate)
            save(out/(label+".json"),row);outcomes.append(row)
            if repeat==0:
                owners=json.loads((dest/"physical-owners.json").read_bytes())
                need(set(owners["owners"])==w.NAMES and all(owners["linked"].count(n)==1 and
                     owners["owners"][n]["relink"]==(arm=="candidate") for n in w.NAMES),"all twelve observed native links")
    # Preserve the ordinary consecutive measured calls above. This separate unmetered
    # history opens the actual output immediately on return from each source edit, so an
    # initially stale NEW binary cannot be hidden by its subsequent unchanged command.
    patch=Path(w.__file__).parent/"renderer.patch"
    for arm in ("parent","candidate"):
        study.select(root,binaries,arm);study.reset(env,seed,w)
        w.git(src,"apply","--reverse",patch);w.sources(src,"old")
        for phase,state in (("old","old"),("edit","new"),("first-unchanged","new")):
            if phase=="edit":
                w.git(src,"apply",patch);w.sources(src,"corrected")
            immediate=study.execute(root,src,env,out/("immediate-"+arm+"-"+phase),reference.FULL)
            refs=bank["families"][state]
            actual={k:v for k,v in immediate["executables"].items()if k.startswith(("test/","example/"))}
            need(set(actual)==set(refs) and all(v[1] in refs[k] and
                 v[2]==bank["terminal"]["objects"][v[1]]["size"] for k,v in actual.items()),
                 ("each immediate source-state image is an already enrolled complete signed file",arm,phase))
    study.select(root,binaries,"parent");study.reset(env,seed,w)
    dst=out/"tests-independent-new";raw=study.execute(root,src,env,dst,reference.FULL)
    paths={k:v[0]for k,v in raw["executables"].items()}
    images=price.behaviors(paths,src,env,w.NAMES,"tests");validate("new",paths,images,dst)
    examples={k:v for k,v in images.items()if k.startswith("example/")}
    need(len(examples)==12 and all(all(r["new_images"][k]==v for k,v in examples.items())for r in outcomes),
         "whole bytes plus both streams for twelve ordinary examples")
    save(out/"terminal.json",{"schema":2,"scope":"confirm-tests","head":head,"run":os.environ["GITHUB_RUN_ID"],
         "job":os.environ["GITHUB_JOB"],"position":position,"boot":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
         "runner":os.environ["RUNNER_NAME"],"cpus":cpus,"ordering":arm_order,"workflows":["tests"],
         "signed":sha(root/"distribution/bin/rustc"),"wild":sha(root/"distribution"/study.WILD),
         "cargo":{arm:sha(file)for arm,file in binaries.items()},"reference":bank["record"]})


if __name__=="__main__":
    main()
