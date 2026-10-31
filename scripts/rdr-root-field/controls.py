"""Run the borrowed native fixture, plus mixed-reader, true access and legacy format controls."""
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from inputs import FIXTURE, P, C, build, need, source

HOST = build.HOST
WRAPPER = """#!/usr/bin/python3
import json, os, subprocess, sys
p=subprocess.run([os.environ['RDR_RUSTC_PROXY'],'+ohm',*sys.argv[1:]],capture_output=True)
with open(os.environ['RDR_RUSTC_LOG'],'ab') as f:
 f.write((json.dumps(dict(argv=sys.argv[1:],code=p.returncode,stdout=p.stdout.decode(errors='replace'),stderr=p.stderr.decode(errors='replace')))+'\\n').encode())
sys.stdout.buffer.write(p.stdout);sys.stderr.buffer.write(p.stderr);sys.exit(p.returncode)
"""


def env_for(root, sdk, rec):
    active = root / "active"
    if active.exists():
        need(active.is_symlink() and active.resolve() in {root/"parent-sdk", root/"candidate-sdk"}, "unrecognized current subject")
        active.unlink()
    active.symlink_to(sdk, target_is_directory=True)
    ohm = root/"rdr-rustup/toolchains/ohm"
    if not ohm.exists():
        ohm.parent.mkdir(parents=True)
        ohm.symlink_to(active, target_is_directory=True)
    need(ohm.resolve() == sdk, "Rustup subject mismatch")
    proxy = Path(shutil.which("rustup")).parent / "rustc"
    need(proxy.is_file() and os.path.samefile(proxy, Path(shutil.which("rustup"))), "not Rustup rustc proxy")
    env = {**os.environ, "RUSTUP_HOME":str(root/"rdr-rustup"), "RUSTUP_AUTO_INSTALL":"0", "RUSTC_BOOTSTRAP":"1",
           "RUST_BACKTRACE":"0", "LC_ALL":"C", "RDR_RUSTC_PROXY":str(proxy), "RDR_RUSTC_LOG":str(rec)}
    need(Path(subprocess.check_output([proxy,"+ohm","--print","sysroot"],env=env,text=True).strip()).resolve() == sdk, "wrong selected sysroot")
    return env


def checked_in(root, repo, role, sdk, runner):
    rec = root/"receipts"/role
    work = root/"rdr-rmake-work"
    work.mkdir()
    fixture = repo/"tests/run-make"/FIXTURE
    for n in ("producer.rs","bridge.rs"):
        shutil.copy2(fixture/n,work/n)
    gate = root/"record-rustc.py"
    if not gate.exists():
        gate.write_text(WRAPPER)
        gate.chmod(0o755)
    log = rec/"rmake-events.jsonl"
    env = env_for(root, sdk, log)
    s0 = repo/"build"/HOST/"stage0"
    support = sorted((repo/"build"/HOST/"bootstrap-tools"/HOST/"release/build").glob("run_make_support/*/out"))
    need(support and all(p.is_dir() for p in support), "missing native run_make_support")
    env.update(RUSTC=str(gate), HOST=HOST,TARGET=HOST,LD_LIB_PATH_ENVVAR="LD_LIBRARY_PATH",
               HOST_RUSTC_DYLIB_PATH=str(sdk/"lib"), TARGET_EXE_DYLIB_PATH=str(sdk/"lib/rustlib"/HOST/"lib"),
               LD_LIBRARY_PATH=os.pathsep.join([*map(str,support),str(s0/"lib/rustlib"/HOST/"lib"),str(s0/"lib")]),
               SOURCE_ROOT=str(repo), BUILD_ROOT=str(repo/"build"/HOST))
    child = subprocess.run([runner],cwd=work,env=env,capture_output=True)
    (rec/"rmake-stdout").write_bytes(child.stdout);(rec/"rmake-stderr").write_bytes(child.stderr)
    if child.returncode != (101 if role=="P" else 0):
        print(child.stderr.decode(errors="replace")[-4500:],flush=True)
    need(child.returncode == (101 if role=="P" else 0), "wrong native runner outcome "+role)
    if role=="P":
        need(b"an unrelated constant changed the bridge" in child.stderr and child.stderr.count(b"Public hash: ")==2, "unintended parent refusal")
    else:
        need(b"panicked" not in child.stderr, "candidate panic")
    raw = log.read_bytes()
    (rec/"rmake-events.jsonl.gz").write_bytes(gzip.compress(raw,mtime=0))
    rows=[json.loads(l) for l in raw.splitlines()]
    loaded=0; empty=0;errors=0
    for r in rows:
        loaded += "-Zassert-incr-state=loaded" in r["argv"]
        empty += "-Zassert-incr-state=not-loaded" in r["argv"]
        if r["code"]:
            need(r["code"] == 1 and "error[E0616]" in r["stderr"] and "internal compiler error" not in r["stderr"], "wrong actual rustc diagnostic")
            errors += 1
    need((len(rows),loaded,empty,errors)==(42,14,4,3),"incomplete physical fixture "+role)
    build.write(rec/"rmake.json",dict(returncode=child.returncode, rustc_calls=len(rows), loaded=loaded, fresh=empty,
                                      privacy_errors=errors, runner=build.sha(runner), actual_events=source.digest(raw)))
    work.rename(root/("rdr-rmake-"+role))


def wire(root, repo, sdks):
    rec = root/"receipts"/"wire"
    rec.mkdir()
    work=root/"wire-work"; work.mkdir()
    fixture=repo/"tests/run-make"/FIXTURE
    base=(fixture/"producer.rs").read_text()
    (work/"bridge.rs").write_bytes((fixture/"bridge.rs").read_bytes())
    cache=rec/"cas"; cache.mkdir()
    ledger=[]
    report={}
    def invoke(role, label, args, want=0, error=None, native=False):
        env=env_for(root,sdks[role],rec/"unused")
        cmd = [str(work/"reader")] if native else [env["RDR_RUSTC_PROXY"],"+ohm",*args]
        c=subprocess.run(cmd,cwd=work,env=env,capture_output=True)
        row=dict(role=role,phase=label,cmd=cmd,code=c.returncode,stdout=c.stdout.decode(errors="replace"),stderr=c.stderr.decode(errors="replace"))
        ledger.append(row)
        with (rec/"commands.jsonl").open("a") as f:
            print(json.dumps(row),file=f)
        need(c.returncode==want and b"internal compiler error" not in c.stderr,(label,role,c.returncode,row["stderr"][-600:]))
        if error: need(error.encode() in c.stderr,(label,row["stderr"][-600:]))
        if native: need(c.stdout==b"5\n" and not c.stderr,"native value")
    def keep(name):
        p=work/name
        actual=build.sha(p);target=cache/(actual+".gz")
        if not target.exists():target.write_bytes(gzip.compress(p.read_bytes(),mtime=0))
        return actual
    for policy in ("no","yes"):
        for kind, visibility in [("root","pub(super)"),("named","pub(self) "),("public","pub       ")]:
            (work/"producer.rs").write_text(base.replace("pub(super)",visibility))
            for donor in ("P","C"):
                peer="C" if donor=="P" else "P"
                label=f"{policy}-{kind}-{donor}"
                opts=["--edition=2021","-Zpublic-api-hash="+policy]
                invoke(donor,label+"/producer",["producer.rs","--crate-name","producer","--crate-type=rlib","--emit=metadata=producer.rmeta,link=libproducer.rlib",*opts])
                report[label]=dict(producer=keep("producer.rmeta"))
                for reader in (donor,peer):
                    branch=label+"/"+reader
                    invoke(reader,branch+"/bridge",["bridge.rs","--crate-name","bridge","--crate-type=rlib","--extern","producer=libproducer.rlib","--emit=metadata=bridge.rmeta,link=libbridge.rlib",*opts])
                    report[label][reader]=keep("bridge.rmeta")
                    for field in (False,True):
                        expression="bridge::make().value" if field else "bridge::read(&bridge::make())"
                        (work/"reader.rs").write_text('fn main(){println!("{}",'+expression+')}\n')
                        fail=field and kind!="public"
                        invoke(peer,branch+("/get" if field else "/read"),["reader.rs","--extern","bridge=libbridge.rlib","-Ldependency=.","-o","reader",*opts],1 if fail else 0,"error[E0616]" if fail else None)
                        if not fail:invoke(peer,branch+"/exe",[],native=True)
    for kind in ("root","named","public"):
        p,c = [report["no-"+kind+"-"+k] for k in ("P","C")]
        need(p["producer"]==c["producer"] and len({p["P"],p["C"],c["P"],c["C"]})==1,"legacy full metadata bytes differ for "+kind)
    build.write(rec/"qualified.json",dict(commands=len(ledger),observed=report))
