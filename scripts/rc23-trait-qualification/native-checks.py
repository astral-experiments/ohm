"""Exercise trait invalidation and cache compatibility with the native SDKs."""
import hashlib
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PINS = json.loads((HERE/"arms.json").read_bytes())
ARMS = ("base","nominal","both")
WORK, OUT, FIXTURE = map(Path,sys.argv[1:])
SDK = WORK/"active-sdk"
ROOT = WORK/"native"
PROOF = OUT/"native"
ROOT.mkdir()
PROOF.mkdir()


def check(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def save(path,value):
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n")


def select(arm):
    SDK.unlink(missing_ok=True)
    SDK.symlink_to(WORK/("sdk-"+arm),target_is_directory=True)


def env(mode):
    result = dict(PATH=f"{SDK}/bin:/usr/bin:/bin",HOME=str(ROOT),LC_ALL="C",RUSTC_BOOTSTRAP="1")
    if mode=="forced":
        result["RUSTC_FORCE_RUSTC_VERSION"]="rustc-perf"
    return result


def run(path,label,argv,cwd,e,expected=None):
    p=subprocess.run(argv,cwd=cwd,env=e,capture_output=True)
    (path/(label+".stdout")).write_bytes(p.stdout)
    (path/(label+".stderr")).write_bytes(p.stderr)
    save(path/(label+".json"),{"argv":list(map(str,argv)),"exit":p.returncode,
         "stdout_sha256":hashlib.sha256(p.stdout).hexdigest(),"stderr_sha256":hashlib.sha256(p.stderr).hexdigest()})
    if expected is not None:
        check(p.returncode==expected,f"{label} exit {p.returncode}: {p.stderr.decode(errors='replace')[-900:]}")
    return p


def trait_changes():
    e=env("native")
    cfg_steps=[([], "3 3 3 3 3"),(["unrelated"],"3 3 3 3 3"),
               (["unrelated","matching","finite"],"7 3 11 13 17"),(["unrelated","moved"],"3 7 3 3 3"),
               (["unrelated"],"3 3 3 3 3"),(["unrelated","moved"],"3 7 3 3 3"),
               (["unrelated","retired"],"3 3 3 3 3")]
    for arm in ARMS:
        select(arm)
        wd=ROOT/("trait-"+arm)
        wd.mkdir()
        for f in ("reader.rs","roster.rs"):
            shutil.copyfile(FIXTURE/f,wd/f)
        log=PROOF/("trait-"+arm)
        log.mkdir()
        for n,(cfgs,expected) in enumerate(cfg_steps):
            upstream=[SDK/"bin/rustc","roster.rs","--crate-type","rlib"]
            for flag in cfgs:
                upstream.extend(["--cfg",flag])
            run(log,f"{n}-roster",upstream,wd,e,0)
            for solver in ("default","next"):
                for cache in ("warm","clean"):
                    dest=wd/(solver if cache=="warm" else f"clean-{n}-{solver}")
                    flags=["-Znext-solver"] if solver=="next" else []
                    cmd=[SDK/"bin/rustc","reader.rs","--extern","roster=libroster.rlib",
                         "-Cincremental="+str(dest),"-Zincremental-verify-ich",*flags]
                    label=f"{n}-{solver}-{cache}"
                    run(log,label,cmd,wd,e,0)
                    actual=run(log,label+"-run",[wd/"reader"],wd,e,0).stdout.decode().strip()
                    check(actual==expected,(arm,n,solver,cache,actual,expected))


def graphs(cache):
    out=[]
    for f in sorted(cache.rglob("dep-graph.bin")):
        with f.open("rb") as stream:
            data=stream.read(262)
        check(data[:4]==b"RSIC" and len(data)>=7+data[6],"invalid dep-graph header")
        out.append({"crate":str(f.relative_to(cache).parts[0]),"format":int.from_bytes(data[4:6],"little"),
                    "version":data[7:7+data[6]].decode()})
    check(len(out)==1,("expected one seeded crate graph",out))
    return out[0]


def errors(stderr):
    diagnostics=[json.loads(line) for line in stderr.splitlines() if line.startswith(b"{")]
    return [{k:d.get(k) for k in ("code","message","level","spans","children")} for d in diagnostics
            if d.get("level")=="error" and d.get("code")]


def migration():
    wd=ROOT/"migration"
    wd.mkdir()
    a=(HERE/"probe.rs").read_bytes()
    check(hashlib.sha256(a).hexdigest()=="68ee764b7d38e2c8add4a6961b422e998f3aa47611501a247b0c2da4733bc0f8","wrong original trait probe")
    b=a.replace(b"        11\n",b"        17\n")
    bad=a.replace(b"impl Score for Left {",b"impl Score for Right {")
    cache=wd/"incremental"
    log_parent=PROOF/"migration"
    log_parent.mkdir()
    def reset(seed=None):
        if cache.exists():
            shutil.rmtree(cache)
        if seed:
            shutil.copytree(seed,cache)
    def compile_(e,log,label,source,gate=None):
        (wd/"probe.rs").write_bytes(source)
        cmd=[SDK/"bin/rustc","probe.rs","--crate-name","ohm_cache_migration","--edition","2024",
             "--sysroot",SDK,"--emit=link","-Ccodegen-units=1","-Cmetadata=ohm_cache_test",
             "-Cincremental="+str(cache),"--error-format=json","-o",wd/"probe"]
        if gate:
            cmd.append("-Zassert-incr-state="+gate)
        return run(log,label,cmd,wd,e)
    def value(e,log,label,p,want):
        check(p.returncode==0,(label,p.stderr.decode(errors="replace")[-800:]))
        actual=run(log,label+"-run",[wd/"probe"],wd,e,0).stdout.decode().strip()
        check(actual==want,(label,want,actual))
    summary={}
    for mode in ("native","forced"):
        e=env(mode)
        folder=log_parent/mode
        folder.mkdir()
        headers={}
        clean_errors={}
        for arm in ARMS:
            select(arm)
            log=folder/(arm+"-controls")
            log.mkdir()
            reset()
            value(e,log,"seed",compile_(e,log,"seed",a),"11")
            header=graphs(cache)
            check(header["format"]==(PINS["base_epoch"] if arm=="base" else PINS["epoch"]),"wrong written header")
            if mode=="forced":
                check(header["version"]=="rustc-perf","version override did not take effect")
            headers[arm]=header
            shutil.copytree(cache,wd/(mode+"-"+arm))
            reset()
            value(e,log,"clean-positive",compile_(e,log,"clean-positive",b),"17")
            reset()
            p=compile_(e,log,"clean-error",bad)
            digs=errors(p.stderr)
            check(p.returncode==1 and any(x["code"]["code"]=="E0277" and "Left" in x["message"] for x in digs),
                  "fresh compiler did not diagnose the missing trait impl")
            clean_errors[arm]=digs
        dispositions={}
        for writer,reader in itertools.product(ARMS,repeat=2):
            select(reader)
            seed=wd/(mode+"-"+writer)
            label=writer+"-to-"+reader
            log=folder/label
            log.mkdir()
            expected=headers[writer]==headers[reader]
            for name,source,want in (("unchanged",a,"11"),("positive",b,"17")):
                reset(seed)
                value(e,log,name,compile_(e,log,name,source),want)
            reset(seed)
            p=compile_(e,log,"negative",bad)
            check(p.returncode==1 and errors(p.stderr)==clean_errors[reader],(label,"cached E0277 differs"))
            for assertion in ("loaded","not-loaded"):
                reset(seed)
                p=compile_(e,log,"assert-"+assertion,b,assertion)
                if (assertion=="loaded")==expected:
                    value(e,log,"assert-"+assertion,p,"17")
                else:
                    message=(b"we asserted that the incremental cache should not be loaded" if expected else
                             b"we asserted that an existing incremental cache directory should be successfully loaded")
                    check(p.returncode==1 and message in p.stderr,(mode,label,assertion,p.returncode,p.stderr[-1000:]))
            dispositions[label]="loaded" if expected else "rejected"
        summary[mode]={"headers":headers,"transitions":dispositions}
    save(PROOF/"cache-behavior.json",summary)


trait_changes()
migration()
save(PROOF/"completed.json",{"arms":ARMS,"trait_edits":7,"solvers":["default","next"],"cache_transitions":18})
