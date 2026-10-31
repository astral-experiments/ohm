"""One fresh candidate bootstrap. The exact matched native parent was physically built in the original run."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import controls
from inputs import C,P,COMPILER,FIXTURE,BOOT_ARGS, MANIFEST, QA,RUN,JOB,ATTEMPT,MEMBERS,build,source,need,materialize,parent

def main(root):
    need(root==build.ROOT and root.resolve()==root and shutil.disk_usage(root).free>32*2**30,"unexpected root/capacity")
    repo=root/"rust"; rec=root/"receipts"; transfer=root/"transfer"
    for role in ("P","C"): (rec/role).mkdir()
    transfer.mkdir()
    m=parent(root/"incoming")
    roles=materialize(repo)
    source.git(repo,"checkout","--detach",C)
    build.check_source(repo,C)
    launcher=build.launcher(repo)
    sdks={"P":root/"parent-sdk","C":root/"candidate-sdk"}
    parent_files=build.manifest({Path(n):sdks["P"]/n for n in m["files"]})
    need(parent_files==m["files"],"original tested native parent mutated")
    for path,source_path in [(root/"cargo/cargo-301",sdks["P"]/"bin/cargo"),(root/"packages/sdk-21"/build.WILD,sdks["P"]/build.WILD)]:
        path.parent.mkdir(parents=True,exist_ok=True);os.link(source_path,path)
    build.write(rec/"source.json",dict(roles=roles,qa=os.environ["GITHUB_SHA"],run=os.environ["GITHUB_RUN_ID"],attempt=os.environ["GITHUB_RUN_ATTEMPT"],launcher=launcher,llvm=build.LLVM,stage0=build.STAGE0,parent_run=RUN,parent_job=JOB,parent_qa=QA,parent_manifest=MANIFEST))
    need(not (repo/"build").exists(),"preexisting candidate build")
    build.succeeded(BOOT_ARGS,repo,rec/"C/bootstrap.log")
    stage=repo/"build"/build.HOST/"stage1"
    found={"source":build.sha(repo/"src/stage0"),**{k:build.sha(stage.parent/"stage0/bin"/k) for k in ("rustc","cargo")}}
    need(found==build.STAGE0,"different compiler bootstrap inputs")
    selected=build.collect(stage,root); actual=build.manifest(selected)
    driver=m["driver"]
    diff={n:[parent_files.get(n),actual.get(n)] for n in sorted(set(parent_files)|set(actual)) if parent_files.get(n)!=actual.get(n)}
    build.write(rec/"C/physical-files.json",actual)
    build.write(rec/"C/differences.json",diff)
    need(set(actual)==set(parent_files) and driver in diff and actual[driver][0]!=parent_files[driver][0],"missing/identical source driver")
    for n in ("bin/cargo","bin/rustc",str(build.WILD),*[n for n in parent_files if n.startswith("lib/libLLVM") or n.endswith("/rust-lld")]):
        need(actual[n]==parent_files[n],"bootstrap or native tool unexpectedly differs: "+n)
    sdk=sdks["C"]; sdk.mkdir()
    for name,p in selected.items():
        dest=sdk/name;dest.parent.mkdir(parents=True,exist_ok=True);os.link(p.resolve(),dest)
    build.archive({Path(n):sdk/n for n in diff},transfer/"changed-native.tar.zst")
    version=subprocess.check_output([sdk/"bin/rustc","-vV"])
    need(version.decode()==m["compiler_verbose"],"parent/candidate version stamp mismatch")
    build.write(transfer/"manifest.json",dict(roles=roles,parent_run=RUN,parent_qa=QA,parent_job=JOB,parent_attempt=ATTEMPT,
        parent_archives=MEMBERS,parent_manifest=MANIFEST,qa=os.environ["GITHUB_SHA"],run=os.environ["GITHUB_RUN_ID"],
        attempt=os.environ["GITHUB_RUN_ATTEMPT"],files=actual,differences=diff,driver=driver,
        delta=[build.sha(transfer/"changed-native.tar.zst"),(transfer/"changed-native.tar.zst").stat().st_size],same_non_driver=len(actual)-len(diff)))
    args=["./x",*build.OPTIONS,"--set","rust.verbose-tests=true","test",*build.HOST_FLAGS,"tests/run-make/"+FIXTURE]
    native=rec/"C/checked-in.log"; rc=build.log_run(args,repo,native)
    if rc:print(native.read_text(errors="replace")[-6000:],flush=True)
    # Preserve genuine parent red even when the new native compiler fails the same checked-in assertions.
    runner=repo/"build"/build.HOST/"test/run-make"/FIXTURE/"rmake"
    need(runner.is_file(),"the exact checked-in rmake failed to compile")
    controls.checked_in(root,repo,"P",sdks["P"],runner)
    controls.checked_in(root,repo,"C",sdks["C"],runner)
    build.verdict(native.read_text(errors="replace"),FIXTURE,True,rc)
    for test in ("rdr-public-hash-private-trait-impl","rdr-public-hash-module-child-spans",
                 "rdr-public-hash-proc-macro-foreign-bytes"):
        file=rec/"C"/(test+".log");rc=build.log_run([*args[:-1],"tests/run-make/"+test],repo,file)
        if rc: print(file.read_text(errors="replace")[-6500:],flush=True)
        build.verdict(file.read_text(errors="replace"),test,True,rc)
    controls.wire(root,repo,sdks)
    from restore_candidate import restore_candidate
    restore_candidate(sdks["P"],m,transfer,root/"reopened-candidate",os.environ["GITHUB_SHA"],os.environ["GITHUB_RUN_ID"],os.environ["GITHUB_RUN_ATTEMPT"])
    for role,q in sdks.items():
        expected=parent_files if role=="P" else actual
        need(build.manifest({Path(n):q/n for n in expected})==expected,"mutated runtime after controls")
    build.check_source(repo,C)
    build.write(rec/"qualified.json",dict(qa=os.environ["GITHUB_SHA"],run=os.environ["GITHUB_RUN_ID"],attempt=os.environ["GITHUB_RUN_ATTEMPT"],roles=roles,baseline_driver=parent_files[driver],candidate_driver=actual[driver],same_non_driver=len(actual)-len(diff),differences=sorted(diff),transfer=build.sha(transfer/"manifest.json"),wire=build.sha(rec/"wire/qualified.json"),P=build.sha(rec/"P/rmake.json"),C=build.sha(rec/"C/rmake.json")))

if __name__=="__main__": main(Path(sys.argv[1]))
