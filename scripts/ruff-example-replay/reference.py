"""Enroll complete physical signed OLD/NEW executable families before any test-build pricing."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import byte_probe
import factory
import price
import study
import wild_probe
from factory import need,save,sha

FULL=["test","-p",study.PACKAGE,"--no-run"]
SUBSET=["test","-p",study.PACKAGE,*[v for n in byte_probe.AFFECTED for v in ("--test",n)],"--no-run"]
TESTS={"color","examples","formatter","ruff","rustc_tests"}


def outcomes(root,src,env,dest,actual):
    # The real examples integration suite compiles a separate testing-colors variant. Its
    # nested Cargo processes and their target files must never enter a timed history.
    private=dict(env,CARGO_TARGET_DIR=str(root/"behavior-target"),
                 CARGO_BUILD_BUILD_DIR=str(root/"behavior-build"),CARGO_NET_OFFLINE="true")
    selected={tag.split("/")[1]:v for tag,v in actual.items() if tag.startswith("test/")}
    observations=byte_probe.verdicts(src,private,dest,selected)
    return {name:{"exit":r["exit"],"cases":r["cases"]} for name,r in observations.items()}


def compare_behavior(state,rows):
    if state=="new":
        need(all(r["exit"]==0 and r["cases"] and all(v=="ok" for n,v in r["cases"])
                 for r in rows.values()),"every signed NEW test case passes")
    else:
        need(rows["ruff"]["exit"]!=0 and any("multiple_insertions" in n and v=="FAILED"
             for n,v in rows["ruff"]["cases"]),"real clean OLD renderer failure")


def source_gate():
    record=json.loads((HERE/"official-wild-cause.json").read_bytes())
    result=price.api("actions/runs/"+str(record["run"]))
    official=price.api("actions/artifacts/"+str(record["artifact"]))
    need(result["head_sha"]==record["head"] and result["conclusion"]=="success" and result["run_attempt"]==1 and
         official["workflow_run"]["id"]==record["run"] and official["digest"]=="sha256:"+record["sha256"] and
         not official["expired"],"authenticated completed signed whole-file causal gate")
    b=subprocess.check_output(["gh","api","repos/astral-experiments/ohm/actions/artifacts/"+str(record["artifact"])+"/zip"])
    need(hashlib.sha256(b).hexdigest()==record["sha256"],"physical original disclosure")
    with ZipFile(io.BytesIO(b)) as z:
        t=json.loads(z.read("terminal.json"))
        proof=json.loads(z.read("input-influence.json"))
    imgs=t["images"];effect=proof["intervention"]
    need(t["head"]==record["head"] and int(t["run"])==record["run"] and
         imgs["ordinary"]["sha256"]==imgs["four"]["sha256"]==imgs["single-file"]["sha256"] and
         imgs["one"]["rodata_entsize"]==0 and imgs["four"]["rodata_entsize"]==8 and
         effect["original-copy"]["image"]["sha256"]==imgs["four"]["sha256"] and
         effect["four-byte-entity"]["image"]["rodata_entsize"]==4 and
         len({r["digest_except_note_and_rodata_entsize"]for r in
              [*imgs.values(),effect["four-byte-entity"]["image"]]})==1,"causal frozen real native input")
    return record


def main():
    ws=Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True);head=os.environ["GITHUB_SHA"]
    need(os.environ["GITHUB_REPOSITORY"]=="astral-experiments/ohm" and os.environ["GITHUB_REF"]==study.BRANCH
         and os.environ["GITHUB_RUN_ATTEMPT"]=="1" and os.environ["REVIEWED_HEAD"]==head,"registered nonrelease receiver")
    for d,h in (("enrolled",head),("historical",study.RENDERER)):
        need(subprocess.check_output(["git","-C",ws/d,"rev-parse","HEAD"]).decode().strip()==h,"checked-out source")
    sys.path.insert(0,str(ws/"historical/scripts/gnu-example-ceiling"))
    import workload as w
    root=Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)/"ruff-example-price";root.mkdir()
    out=root/"evidence";out.mkdir();objects=out/"reference-objects";objects.mkdir()
    save(out/"registered-cause.json",source_gate())
    binaries=price.enroll(root,ws,out,json.loads((HERE/"official-pilot.json").read_bytes()))
    binaries["released"]=root/"distribution/bin/cargo";study.select(root,binaries,"released")
    cpu=sorted(os.sched_getaffinity(0));need(len(cpu)>=4,"four available CPUs");os.sched_setaffinity(0,cpu[:4])
    src=w.source(root);env=w.env_for(root);seed=w.prepare_registry(root,src,env,out)
    patch=Path(w.__file__).parent/"renderer.patch";families={};reference_cases={};all_objects={}
    for state in ("old","new"):
        if state=="old":w.git(src,"apply","--reverse",patch)
        else:w.git(src,"apply",patch)
        verified_state="corrected" if state=="new" else "old";w.sources(src,verified_state)
        family={};widths={};baseline=None
        for label,args,jobs,group in (("ordinary",FULL,4,None),("mixed-group",SUBSET,1,None),
                                     ("single-file",SUBSET,1,"1")):
            stage=out/(state+"-"+label);stage.mkdir()
            study.reset(env,seed,w)
            sub=dict(env)
            if group:sub["WILD_FILES_PER_GROUP"]=group
            result=study.execute(root,src,sub,stage/"actual",args,jobs=jobs)
            values=result["executables"]
            seen={k for k in values if k.startswith("example/") or k.startswith("test/")}
            if label=="ordinary":
                need({k.split("/")[1]for k in seen if k.startswith("example/")}==w.NAMES and
                     {k.split("/")[1]for k in seen if k.startswith("test/")}==TESTS and len(seen)==17,
                     "all twelve ordinary examples and five actual integration targets")
            else:
                need(seen=={"test/"+n+"/True" for n in byte_probe.AFFECTED},"only three independently perturbed targets")
            actual={k:values[k]for k in seen}
            for key,(f,h,size) in actual.items():
                file=Path(f)
                need(sha(file)==h and file.stat().st_size==size,"physical signed reference")
                if h not in all_objects:
                    with (objects/(h+".zst")).open("xb")as dest:
                        subprocess.run(["zstd","-q","-3","-c",file],stdout=dest,check=True)
                    all_objects[h]={"size":size,"key":key}
                family.setdefault(key,set()).add(h)
                if key in {"test/"+n+"/True" for n in byte_probe.AFFECTED}:
                    image=wild_probe.read_image(file,stage/(key.split("/")[1]+"-readelf.gz"))
                    need(image["rodata_flags"]==50 and image["rodata_entsize"] in (0,8),
                         "only the two independently explained signed section header forms")
                    widths.setdefault(key,[]).append(image)
            actual_cases=outcomes(root,src,sub,stage/"real-tests",actual)
            compare_behavior(state,actual_cases)
            if baseline is None:baseline=actual_cases
            else:need(all(actual_cases[n]==baseline[n]for n in actual_cases),"same actual tests and dispositions")
            save(stage/"cases.json",actual_cases)
            save(stage/"digests.json",{key:actual[key][1:]for key in sorted(actual)})
            w.sources(src,verified_state)
        for key,images in widths.items():
            need(len({r["digest_except_note_and_rodata_entsize"]for r in images})==1 and
                 {r["rodata_entsize"]for r in images}=={0,8},("complete two-form signed family",state,key))
        save(out/(state+"-metadata-explanation.json"),widths)
        families[state]={k:sorted(v)for k,v in sorted(family.items())}
        reference_cases[state]=baseline
    save(out/"families.json",families);save(out/"reference-cases.json",reference_cases)
    save(out/"terminal.json",{"run":os.environ["GITHUB_RUN_ID"],"head":head,"job":os.environ["GITHUB_JOB"],
         "boot":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),"cpus":cpu[:4],
         "rustc":sha(root/"distribution/bin/rustc"),"wild":sha(root/"distribution"/study.WILD),
         "cargo":sha(binaries["released"]),"objects":all_objects,"recorded_invariants":"full unmodified executable bytes"})


if __name__=="__main__":
    main()
