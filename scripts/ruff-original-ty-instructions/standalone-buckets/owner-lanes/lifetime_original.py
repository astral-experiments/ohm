"""Replay only the original incremental edit against fresh compiler lifetimes and archived native bodies."""
import hashlib
import json
import os
from pathlib import Path
import subprocess as sp
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import diagnostic as d
from actor import CASES, COMMAND, CRATES, LIB, base, native_oracle, need, old, w
from member_names import native_identity

ORIGINAL = "9a1b4cffbe9c717b920c52fb3b57e6c82a7cad761ded3da6a15cad73fca209e2"

def verify_native(reference, rows, directory, role, phase):
    products = base.products(rows)
    recorded = reference(role + "/" + phase + "/native.json")
    mapped = {}
    for crate in CRATES:
        path = products[crate]["rlib"]
        current = base.read_names(path, crate)
        need(native_identity(current) == native_identity(recorded[crate]["mapping"]),
             ("different original native archive or symbol binding", role, phase, crate))
        mapped[crate] = old.record_file(path)
    w.put(directory / "native-outputs.json", mapped)

def ordinary_seed(directory, env):
    directory.mkdir()
    with (directory/"stdout.jsonl").open("xb") as out, (directory/"stderr").open("xb") as err:
        sp.run(COMMAND, cwd=w.work, env=env, stdout=out, stderr=err, check=True)
    return old.result_rows(directory, True)[0]

def main():
    need(os.environ["GITHUB_RUN_ATTEMPT"] == "1" and os.environ["REVIEWED_HEAD"] == os.environ["GITHUB_SHA"]
         and os.environ["GITHUB_REF_NAME"] == "charlie/qa-ruff-root-owner-lanes-20261103", "wrong observation")
    packet = Path(os.environ["RUNNER_TEMP"]) / "original.zip"
    with packet.open("rb") as f:
        need(hashlib.file_digest(f, "sha256").hexdigest() == ORIGINAL and packet.stat().st_size == 400903442,
             "different ordinary reference")
    archive=zipfile.ZipFile(packet)
    reference=lambda n:json.loads(archive.read(n))
    original=reference("result.json");reg=reference("registration.json")
    case="29697";old.old,old.new,old.lock,order=CASES[case]
    need(reg["source"]==[old.old,old.new] and reg["command"]==COMMAND and original["case"]==case and
         w.git("rev-parse","HEAD")==old.new and w.git("rev-parse","HEAD^")==old.old and w.hf(w.work/"Cargo.lock")==old.lock,
         "different actual Ruff input")
    cfg=json.loads((HERE/"binding.json").read_bytes())
    need(cfg==reg["binding"] and order==reg["order"],"different matched compilers")
    w.guard();trace=w.root/"exec_count";dest=w.root/"diagnostic";dest.mkdir()
    sp.run(["cc","-O2","-Wall","-Wextra","-Werror",LIB.parent/"exec_count.c","-o",trace],check=True)
    d.calibrate(dest,trace,{"PATH":os.environ["PATH"]})
    token=os.environ["OHM_SDK_READ_TOKEN"];env=w.install();roots=base.acquire(w,cfg,token);del token
    w.sdk.rename(w.root/"original-signed-reference")
    w.put(dest/"separate-source.json",{"ordinary":ORIGINAL,"ordinary_run":41706721214,"diagnostic_head":os.environ["GITHUB_SHA"],
          "boot":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),"method":"a fresh task per actual rustc exec with inherit_thread"})
    reports={}
    for index,role in enumerate(order):
        w.guard();old.remove_outputs();old.state(old.old);roots[role].rename(w.sdk);out=dest/role;out.mkdir()
        try:
            driver,=(w.sdk/"lib").glob("librustc_driver-*.so");selected=w.sdk/"bin/rustc"
            actual={"driver":old.record_file(driver),"cargo":old.record_file(w.sdk/"bin/cargo"),"rustc":old.record_file(selected)}
            original_tools=reference(role+"/tools.json")
            need(all(actual[k]["sha256"]==original_tools[k]["sha256"] for k in actual) and actual["driver"]["sha256"]==cfg["driver"][role],"different actual tools")
            w.put(out/"tools.json",actual)
            if index==0:sp.run(["cargo","+ohm","fetch","--locked","--target","x86_64-unknown-linux-gnu"],cwd=w.work,env=env,check=True)
            env["CARGO_NET_OFFLINE"]="true"
            rows=ordinary_seed(out/"old",env)
            need(old.corpus(rows)==old.corpus([json.loads(l) for l in archive.read(role+"/old/stdout.jsonl").splitlines()
                       if json.loads(l).get("reason")=="compiler-artifact"]) and all(not r["fresh"] for r in rows),"different cold closure")
            verify_native(reference,rows,out/"old",role,"old")
            before=native_oracle(case,rows,env,out/"old",old.old)
            need(before["stdout"]==original["roles"][role]["native"]["old"]["stdout"],"different old public Rust verdict")
            for name,revision in [("observed-edit",old.new),("observed-unchanged",old.new)]:
                old.state(revision);td=out/name
                readings,total=d.measure(trace,selected,COMMAND,td,env,w.work);rows,_=old.result_rows(td,True)
                dirty=sorted(r["target"]["name"]for r in rows if not r["fresh"]);census=old.census(td,env)
                real={}
                for row in readings:
                    argv=row["argv"]
                    if "--crate-name" in argv:
                        owner=argv[argv.index("--crate-name")+1];need(owner not in real,"duplicate real compiler")
                        real[owner]=row["instructions"]
                need(sorted(real)==dirty and sorted(census["real_execs"])==["rustc:"+n for n in dirty],"different compiled units")
                observed={"observed":census,"whole":total,"lifetimes":real,"raw":readings,"dirty":dirty}
                if name=="observed-edit":
                    need(dirty==original["roles"][role]["actual_dirty"] and real["ty_project"]>0,"different observed edit")
                    verify_native(reference,rows,td,role,"edit")
                    after=native_oracle(case,rows,env,td,old.new)
                    need(after["stdout"]==original["roles"][role]["native"]["edited"]["stdout"] and before["stdout"]!=after["stdout"],"different true edit behavior")
                    observed["oracle"]=after;reports[role]=observed
                else:need(not dirty and not real,"unchanged control launched a compiler")
                w.put(td/"result.json",observed)
        finally:
            w.sdk.rename(roots[role]);old.remove_outputs()
    w.put(dest/"result.json",{"case":case,"run":os.environ["GITHUB_RUN_ID"],"roles":reports,
          "affected_rustc_reduction":1-reports["C"]["lifetimes"]["ty_project"]/reports["P"]["lifetimes"]["ty_project"]})

if __name__=="__main__":
    main()
