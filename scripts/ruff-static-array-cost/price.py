"""Price the complete Ruff command and the one affected rustc against the same two SDKs."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess as sp
import sys
import time
import tomllib
import urllib.request

kit=Path(__file__).resolve().parent
sys.path.insert(0,str(kit))
import transport
reg=transport.REGISTER
gitroot=Path(os.environ["GITHUB_WORKSPACE"])/"ruff"
work=Path(os.environ["RUNNER_TEMP"])/"unicode-price"
proof=work/"proof"
sdk=work/"sdk"
alias=work/"rustup/toolchains/ohm"
home=work/"cargo-home"
target=work/"target"
shared=work/"shared"
boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip()
block=os.environ["PRICE_BLOCK"]
order=reg["orders"][block]
case=os.environ["ARRAY_CASE"]
fixture=reg["cases"][case]
old,new=fixture["old"],fixture["new"]
sha=transport.sha
put=transport.jsonfile
rustc=sdk/"bin/rustc"
wild=sdk/"lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"

def git(*args):return sp.check_output(["git",*args],cwd=gitroot,text=True).strip()
def standard():
    e={k:os.environ[k] for k in ("PATH","HOME","USER","LANG","TZ","TMPDIR") if k in os.environ}
    return dict(e,RUSTUP_HOME=str(alias.parent.parent),CARGO_HOME=str(home),CARGO_TARGET_DIR=str(target),
                CARGO_BUILD_BUILD_DIR=str(shared),CARGO_BUILD_JOBS="2",CARGO_NET_OFFLINE="true")
def switch(commit):
    assert not git("status","--porcelain","--untracked-files=all")
    if git("rev-parse","HEAD")!=commit:sp.run(["git","switch","--detach",commit],cwd=gitroot,check=True)
    assert git("rev-parse","HEAD")==commit
def hw(path):
    e=json.loads(path.read_bytes())
    assert e["instructions"]>0 and e["enabled"]==e["running"]>0 and e["status"]==0,e
    return e["instructions"]
def ident(path):
    s=path.stat();return (s.st_dev,s.st_ino)
def enroll():
    proof.mkdir(parents=True)
    assert git("rev-parse",new+"^")==old and git("diff","--name-only",old,new).splitlines()==fixture["paths"]
    assert sha(gitroot/"Cargo.lock")==reg["lock"] and not git("status","--porcelain")
    for name,spec in reg["sources"].items():assert sha(kit/name)==spec["sha256"]
    for name in ("whole_count","exec_count","calibrate"):
        sp.run(["cc","-O2","-pthread","-Wall","-Wextra","-Werror",kit/(name+".c"),"-o",work/name],check=True)
    readings={}
    for mode in ("single","fork"):
        log=proof/("calibrate-"+mode+".json")
        sp.run([work/"whole_count",log,work/"calibrate",work/"calibrate",mode],check=True)
        readings[mode]=hw(log)
    assert 1.99<readings["fork"]/readings["single"]<2.01
    put(proof/"host.json",{"boot":boot,"order":order,"head":os.environ["GITHUB_SHA"],"case":case,"target_case":[old,new],
        "cpuinfo":Path("/proc/cpuinfo").read_text().split("\n\n")[0],"affinity":sorted(os.sched_getaffinity(0)),
        "registration_sha256":sha(kit/"registration.json"),"transports_sha256":sha(kit/"transports.json")})
    cases={}
    for role in order:
        cases[role]=transport.fetch(role,work/"archives",proof/("sdk-"+role))
        verdict=json.loads((proof/("sdk-"+role)/"probes/verdict.json").read_bytes())
        assert verdict["marked_arrays"]==(4 if role=="C" else 0)
        assert verdict["native_repaired"]==verdict["native_empty"]!=verdict["native_old"]
    assert (proof/"sdk-C/bootstrap.json").read_bytes()==(proof/"sdk-P/bootstrap.json").read_bytes()
    os.environ.pop("GH_TOKEN",None)
    return cases
def seed():
    e=standard();e.pop("CARGO_NET_OFFLINE")
    switch(new)
    sp.run(["cargo","+ohm","fetch","--locked"],env=e,cwd=gitroot,check=True)
    cache,=(home/"registry/cache").iterdir()
    packages=[p for p in tomllib.loads((gitroot/"Cargo.lock").read_text())["package"] if "source" in p]
    for pkg in packages:
        assert pkg["source"]=="registry+https://github.com/rust-lang/crates.io-index"
        archive=cache/(pkg["name"]+"-"+pkg["version"]+".crate")
        if not archive.is_file():
            with urllib.request.urlopen("https://static.crates.io/crates/"+pkg["name"]+"/"+archive.name,timeout=80)as src,archive.open("xb")as out:
                shutil.copyfileobj(src,out)
    hashes={p.name:sha(p) for p in cache.glob("*.crate")}
    assert hashes==reg["archives"] and len(hashes)==505
    home.rename(work/"enrolled-cargo-home")
    for p in (target,shared):
        if p.exists():p.rename(work/("fetch-"+p.name))
    put(proof/"cargo-inputs.json",hashes)
def lifetimes(tasks):
    images={};selected=[];total=None
    for line in (tasks/"epochs.tsv").read_text().splitlines():
        fields=line.split()
        if fields[0]=="I":
            num,pid=int(fields[1]),int(fields[2])
            data=(tasks/f"{num:05}.nul").read_bytes().split(b"\0")
            assert data.pop()==b"" and int(data[0])==pid
            images[num]=(pid,tuple(map(int,data[1:3])),list(map(os.fsdecode,data[4:])),fields[-1])
        if fields[0]=="R":
            num,pid,ins,enabled,running,status=map(int,fields[1:])
            process,executable,argv,origin=images[num]
            assert pid==process and origin=="exec" and enabled==running>0 and ins>0 and status==0
            tool="rustc" if executable==ident(rustc) else "Wild" if executable==ident(wild) else None
            assert tool
            name=argv[argv.index("--crate-name")+1] if "--crate-name" in argv else None
            selected.append({"image":num,"tool":tool,"crate":name,"instructions":ins,"argv":argv})
        if fields[0]=="W":
            total,en,ran,status=map(int,fields[1:])
            assert total>0 and en==ran>0 and status==0
    assert total and selected
    unit,=[r for r in selected if r["tool"]=="rustc" and r["crate"]=="unicode_names2"]
    assert "crates/ruff_unicode_names2/src/lib.rs" in unit["argv"] and "-Zlink-only" not in unit["argv"]
    return {"actual":selected,"target_rustc":unit["instructions"],"traced_total":total}
def object_payloads(lib):
    members=sp.check_output(["ar","t",lib],text=True).splitlines()
    assert members and len(set(members))==len(members) and {n for n in members if not n.endswith(".o")}=={"lib.rmeta","lib.rmeta-link"}
    rows={}
    checked={}
    link=sp.check_output(["ar","p",lib,"lib.rmeta-link"])
    for m in members:
        raw=sp.check_output(["ar","p",lib,m])
        assert raw.startswith(b"\x7fELF"),m
        rows[m]=hashlib.sha256(raw).hexdigest()
        if m.endswith(".o"):
            match=re.fullmatch(r"(.+)\.([a-z0-9]{7})\.rcgu\.o",m)
            assert match and link.count(m.encode())==1,m
            stable=match[1]+"._______.rcgu.o"
            assert stable not in checked
            checked[stable]=rows[m]
            link=link.replace(m.encode(),stable.encode())
    checked["lib.rmeta"]=rows["lib.rmeta"]
    checked["lib.rmeta-link"]=hashlib.sha256(link).hexdigest()
    return {"physical":rows,"verified_renames":checked}
def reader(at,artifacts,lib,commit):
    dirs={str(Path(f).parent) for a in artifacts for f in a["filenames"] if f.endswith((".rlib",".rmeta",".so"))}
    reader_source=kit/fixture["reader"]
    assert sha(reader_source)==fixture["reader_sha256"]
    argv=["rustc","+ohm","--edition=2024",reader_source,"--extern","unicode_names2="+str(lib)]
    for path in sorted(dirs):argv+=["-L","dependency="+path]
    argv+=["-o",at/"reader"]
    sp.run(argv,cwd=gitroot,env=standard(),check=True,stdout=sp.DEVNULL)
    output=sp.check_output([at/"reader"],cwd=gitroot,env=standard(),text=True)
    assert output==fixture["old_stdout" if commit==old else "new_stdout"]
    return {"stdout":output,"elf":sha(at/"reader")}
def visit(role,mode,label,commit,trace=False,invalid_at=None):
    at=proof/role/mode/label
    at.mkdir(parents=True)
    assert git("rev-parse","HEAD")==commit
    args=["cargo","+ohm",mode,"-p","ruff_unicode_names2","--lib","--locked","--offline","--message-format=json"]
    command=[work/"whole_count",at/"hardware.json",shutil.which("cargo"),*args]
    if trace:
        tasks=at/"execs"
        tasks.mkdir()
        command=[work/"exec_count","--lifetime",rustc,"--also",wild,tasks,*command]
    if invalid_at is not None:command=args
    start=time.monotonic_ns()
    with (at/"stdout.jsonl").open("wb") as out,(at/"stderr").open("wb") as err:
        rc=sp.run(command,cwd=gitroot,env=standard(),stdout=out,stderr=err).returncode
    elapsed=time.monotonic_ns()-start
    msgs=[json.loads(l) for l in (at/"stdout.jsonl").read_bytes().splitlines() if l.startswith(b"{")]
    assert msgs and msgs[-1]=={"reason":"build-finished","success":rc==0},(at,rc,(at/"stderr").read_text()[-900:])
    diag=[m["message"] for m in msgs if m["reason"]=="compiler-message"]
    if invalid_at is not None:
        errors=[d for d in diag if d["level"]=="error" and (d.get("code") or {}).get("code")=="overflowing_literals"]
        assert rc!=0 and any(any(s["is_primary"] and (s["byte_start"],s["byte_end"])==(invalid_at,invalid_at+3) for s in e["spans"]) for e in errors),diag
        put(at/"error.json",errors)
        return
    assert rc==0 and not diag,(at,diag[:2])
    artifacts=[m for m in msgs if m["reason"]=="compiler-artifact"]
    main,=[a for a in artifacts if a["target"]["name"]=="unicode_names2" and a["target"]["kind"]==["lib"]]
    lib,=[Path(f) for f in main["filenames"] if f.endswith(".rlib" if mode=="build" else ".rmeta")]
    gens=[Path(m["out_dir"]) for m in msgs if m["reason"]=="build-script-executed" and "/ruff_unicode_names2#" in m["package_id"]]
    assert len(gens)==1,gens
    generated={p.name:sha(p) for p in gens[0].glob("generated*.rs")}
    assert generated==fixture["old_generated" if commit==old else "new_generated"]
    rec={"commit":commit,"command":args,"dirty":sorted(a["target"]["name"] for a in artifacts if not a["fresh"]),
         "hardware":hw(at/"hardware.json"),"wall_ns":elapsed,"generated":generated,"product_sha256":sha(lib),"unit_count":len(artifacts)}
    if mode=="build":rec.update(native=reader(at,artifacts,lib,commit),members=object_payloads(lib))
    if trace:rec["lifetime"]=lifetimes(tasks)
    put(at/"result.json",rec)
    print(role,mode,label,len(rec["dirty"]),rec["hardware"],str(rec.get("lifetime",{}).get("target_rustc","")),flush=True)
    return rec
def stash(label,copy=False):
    store=work/"histories"/label
    store.mkdir(parents=True)
    for path in (home,target,shared):
        if copy:shutil.copytree(path,store/path.name)
        else:path.rename(store/path.name)
    return store
def trial(role,mode):
    shutil.copytree(work/"enrolled-cargo-home",home)
    switch(old);cold=visit(role,mode,"cold-old",old)
    donor=stash(role+"-"+mode+"-donor",copy=True)
    switch(new);edit=visit(role,mode,"ordinary-edit",new);warm=visit(role,mode,"unchanged",new)
    moved=stash(role+"-"+mode+"-after-ordinary")
    assert moved.parent==work/"histories" and moved.is_dir()
    shutil.rmtree(moved)
    for path in (home,target,shared):(donor/path.name).rename(path)
    actual=visit(role,mode,"observed-edit",new,trace=True)
    assert cold["unit_count"]==20 and len(cold["dirty"])==20 and edit["dirty"]==actual["dirty"]==["build-script-build","unicode_names2","unicode_names2_generator"]
    assert not warm["dirty"] and cold["generated"]!=edit["generated"]==actual["generated"]==warm["generated"]
    matches=[edit,warm,actual]
    if mode=="build":
        rust=gitroot/"crates/ruff_unicode_names2/src/lib.rs"
        original=rust.read_bytes()
        suffix=b'\n#[deny(overflowing_literals)]\nstatic OHM_ARRAY_RANGE_GUARD: &[u8] = &['+b'1,'*1023+b'256];\n'
        try:
            rust.write_bytes(original+suffix)
            for mark in ("invalid","invalid-again"):visit(role,mode,mark,new,invalid_at=len(original)+suffix.rindex(b"256"))
        finally:rust.write_bytes(original)
        assert not git("status","--porcelain")
        matches.append(visit(role,mode,"repaired",new))
    stash(role+"-"+mode+"-observed")
    shutil.copytree(work/"enrolled-cargo-home",home)
    clean=visit(role,mode,"empty-new",new)
    assert len(clean["dirty"])==20 and clean["generated"]==edit["generated"]
    matches.append(clean)
    stash(role+"-"+mode+"-empty")
    shutil.copytree(work/"enrolled-cargo-home",home)
    clean_trace=visit(role,mode,"observed-empty-new",new,trace=True)
    assert clean_trace["dirty"]==clean["dirty"] and clean_trace["generated"]==clean["generated"]
    matches.append(clean_trace)
    if mode=="build":
        for r in matches:
            assert r["native"]==clean["native"] and r["members"]["verified_renames"]==clean["members"]["verified_renames"]
    else:assert all(r["product_sha256"]==clean["product_sha256"] for r in matches)
    stash(role+"-"+mode+"-observed-empty")
    return {"cold":cold["hardware"],"whole_edit":edit["hardware"],"target_rustc":actual["lifetime"]["target_rustc"],
            "observed_whole":actual["hardware"],"unchanged":warm["hardware"],"empty":clean["hardware"],
            "empty_target_rustc":clean_trace["lifetime"]["target_rustc"],"whole_native":clean.get("native"),"all_products_checked":True}
def main():
    sdks=enroll()
    results={}
    for role in order:
        tar,spec=sdks[role]
        transport.install(tar,spec,sdk,alias)
        assert reg["parent" if role=="P" else "candidate"] in sp.check_output(["rustc","+ohm","-vV"],env=standard(),text=True)
        if not (work/"enrolled-cargo-home").exists():seed()
        results[role]={}
        for mode in ("check","build"):
            results[role][mode]=trial(role,mode)
            put(proof/"result.json",results)
        assert alias.resolve()==sdk.resolve()
        alias.unlink();sdk.rename(work/("used-sdk-"+role))
    print("Complete",block,boot,flush=True)
if __name__=="__main__":main()
