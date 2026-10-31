"""Authenticate only source-built Full and its completed native source tests from the refused job."""
import json
import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from registration import api, need, sha, write, SOURCE, REPO
from restore import extract

RUN=41198740643
JOB=124530126763
HEAD="172164400c7e99ed2bfcf074ae55c76cf92023db"
INPUTS={"observations":(13041084875,"branch-return-source-observations",122242,"897962e3c24957f9b80c5e96d1ac2b99e9c4f665569a7f1db0169dc563c7786d"),
        "full":(13041139543,"branch-return-unqualified-partial-native",234444958,"f081870df83a87ad765ccedf2ceab06ccadfcabb4f6b0e32881f7aad72c4f81a")}
NATIVE=["fbc494b4706cdbc171b61df3db3c18071322e0bb8aaad0f64643a254bdb7674e",234444818]
INVENTORY="c008008a6b483c3613c0f7f3089cb95383016fc5ca3943dedee0ec9e37aeacf6"


def acquire(root):
    source=api(f"runs/{RUN}");jobs=api(f"runs/{RUN}/attempts/1/jobs")["jobs"];job,=jobs
    need((source["head_sha"],source["run_attempt"],source["event"],source["conclusion"],job["head_sha"],job["id"],job["conclusion"])==
         (HEAD,1,"workflow_dispatch","failure",HEAD,JOB,"failure"),"unqualified source origin changed")
    need([s["name"] for s in job["steps"] if s["conclusion"]=="failure"]==["Independently bootstrap both complete SDKs and exercise branch flags, corruption and native input changes"],"other originating failure")
    catalog=api(f"runs/{RUN}/artifacts")["artifacts"];need(len(catalog)==2,"unexpected original artifact roster")
    inbox=root/"full-input";inbox.mkdir()
    for key,(ident,name,size,h) in INPUTS.items():
        found,=[a for a in catalog if a["id"]==ident]
        need(not found["expired"] and found["name"]==name and found["digest"]=="sha256:"+h and found["size_in_bytes"]==size and
             found["workflow_run"]["head_sha"]==HEAD and found["workflow_run"]["id"]==RUN,"wrong original source artifact")
        dest=inbox/(key+".zip")
        with dest.open("xb") as f:subprocess.run(["gh","api",f"repos/{REPO}/actions/artifacts/{ident}/zip"],stdout=f,check=True)
        need(dest.stat().st_size==size and sha(dest)==h,"downloaded source escrow does not match")
    return inbox


def reopen(root,inbox,repo,log,transfer,b,frontend):
    checked=root/"receipts/full-source-origin";checked.mkdir();orig=inbox/"observations.zip"
    need(sha(orig)==INPUTS["observations"][3] and sha(inbox/"full.zip")==INPUTS["full"][3],"unauthenticated original archives")
    shutil.copyfile(orig,checked/"previous-observations.zip")
    full=SOURCE()["roles"]["F"]
    with zipfile.ZipFile(orig) as z:
        def raw(n):return z.read("receipts/F/"+n)
        def data(n):return json.loads(raw(n))
        def positive(label):
            report=data(label+".command.json");need(report["returncode"]==0 and report["output_sha256"]==hashlib.sha256(raw(label+".log")).hexdigest(),"bad original "+label)
            return report
        before=raw("before-tests.json")
        need(raw("inventory.json")==before and hashlib.sha256(before).hexdigest()==INVENTORY,"unaligned Full tests and native products")
        expected=json.loads(before);need(len(expected)==81,"wrong Full inventory")
        original=data("source.json")
        need(all(original[k]==v for k,v in full.items()) and original["llvm"]==b.LLVM and
             (original["qa"],original["run"],original["attempt"])==(HEAD,str(RUN),"1"),"wrong source tree or actual Full job")
        build=positive("bootstrap");reassembly=positive("reassemble")
        sdk_args=["./x",*b.OPTIONS,"build",*b.HOST_FLAGS,*b.SDK_COMPONENTS]
        need(build["argv"]==sdk_args==reassembly["argv"] and build["cwd"]==reassembly["cwd"]==str(b.ROOT/"rust"),"different native compiler build")
        tests,mac=frontend.unit_names(repo,"F");actual=data("checked-in-tests.json")
        frontend.unit_verdict(raw("rustc-units.log").decode(),tests,mac)
        test_args=["./x",*b.OPTIONS,"--set","rust.verbose-tests=true","test",*b.HOST_FLAGS]
        units=positive("rustc-units")
        need(units["argv"]==[*test_args,"compiler/rustc_fs_util","compiler/rustc_incremental"] and units["cwd"]==build["cwd"],"altered source unit command")
        need(actual["unit"]==tests and actual["run_make"]==frontend.NATIVE_TESTS and
             actual["original_sources"]=={n:sha(repo/"tests/run-make"/n/"rmake.rs") for n in frontend.NATIVE_TESTS},"different actual checked-in test inventory")
        stems=["bootstrap","reassemble","rustc-units"]
        for n in frontend.NATIVE_TESTS:
            c=positive(n)
            need(c["argv"]==[*test_args,"tests/run-make/"+n] and c["cwd"]==build["cwd"],"changed run-make argv or source")
            b.verdict(raw(n+".log").decode(),n,True,c["returncode"]);stems.append(n)
        need(data("rustdoc-invalid.command.json")["returncode"]==1 and raw("rustdoc-invalid.log").decode().count("error[E0425]: cannot find type `UnavailableBranchQaType` in this scope")==1,"previous failure was not the recorded diagnostic expectation")
        need(positive("rustdoc-content"),"previous positive rustdoc control")
        for n in ("before-tests.json","inventory.json","checked-in-tests.json","unit-platforms.json","source.json"):
            (log/n).write_bytes(raw(n))
        for name in stems:
            for suffix in (".log",".log.resource",".command.json"):
                (log/(name+suffix)).write_bytes(raw(name+suffix))
    arc=transfer/"F-sdk.tar.zst"
    with zipfile.ZipFile(inbox/"full.zip") as z:
        need(z.namelist()==["F-sdk.tar.zst"],"wrong unqualified escrow layout")
        with z.open("F-sdk.tar.zst") as f,arc.open("xb") as out:shutil.copyfileobj(f,out)
    need([sha(arc),arc.stat().st_size]==NATIVE,"different physical Full SDK")
    dest=root/"original-full-sdk";dest.mkdir();extract(arc,dest,expected,False)
    files={Path(n):dest/n for n in expected}
    need(b.manifest(files)==expected,"reopened Full native files differ")
    origin={"run":RUN,"attempt":1,"job":JOB,"qa":HEAD,"original_run_conclusion":"failure","artifacts":INPUTS,"archive":NATIVE,
            "inventory_sha256":INVENTORY,"source":full,"native_build_and_checked_in_tests":"authenticated from original Full job",
            "operational_requalification":"the new job reruns ordinary Rustup, strict Cargo, native linker, doc and provider validation on the exact same archived bytes"}
    write(log/"build-origin.json",origin);write(checked/"origin.json",origin)
    return files,expected,origin
