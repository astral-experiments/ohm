"""Compare role-native incremental and empty outputs when only the valid LLVM input changes."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
# A separate entry can provide the original, independently authenticated compiler pair.
PROTOCOL = Path(os.environ.get("CGU_KIT_HARNESS", HERE)).resolve()
sys.path[:0] = [str(PROTOCOL), str(PROTOCOL.parent / "ohm-aarch64-linux")]
import runtime as rt
from study import digest, need, save, sha


def main(expectation, role):
    base = rt.ROOT/("pgo-"+expectation+"-"+role)
    shutil.copytree(HERE/"external-input-fixture",base)
    (base/"payload.bin").write_bytes(bytes([17]))
    active = base/"active.profdata"
    active.write_bytes((base/"0.profdata").read_bytes())
    stamp = active.stat()
    dest = rt.LOG/("pgo-"+expectation+"-"+role)
    dest.mkdir()
    env = rt.environment()
    sdk = {"role":role, "selected":rt.select(role),
           "rustc":sha(rt.SDK/"bin/rustc"), "driver":{p.name:sha(p) for p in (rt.SDK/"lib").glob("librustc_driver*.so")}}
    opts = ["rustc","+ohm","main.rs","--edition=2021","--crate-name","same_input","-Clto=off",
            "-Copt-level=2","-Ccodegen-units=16","-Cdebuginfo=0","-Cprofile-use="+str(active),
            "-Zohm-check-relink-inputs","-Zquery-dep-graph","-Zprint-mono-items=yes","--emit=link,dep-info=result.d","-o","result"]
    rows={}
    for phase,cache,i in (("old","warm",0),("repeat","warm",0),("change","warm",1),
                          ("clean-new","empty-new",1),("clean-old","empty-old",0)):
        source=base/f"{i}.profdata"
        active.write_bytes(source.read_bytes());os.utime(active, ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        now=active.stat()
        need((now.st_dev,now.st_ino,now.st_size,now.st_mtime_ns)==
             (stamp.st_dev,stamp.st_ino,stamp.st_size,stamp.st_mtime_ns) and sha(active)==sha(source),
             "external profile was not overwritten at its original identity")
        cap=dest/phase
        proc=rt.record([*opts,"-Cincremental="+str(base/cache)],cap/"compile",base,env)
        votes=dict(re.findall(rb"^CGU_REUSE (\S+) (No|PostLto)$",proc.stdout,re.M))
        def unit(function):
            (name,)=re.findall(rb"^MONO_ITEM fn "+function+rb" @@ ([^\[\n]+)\[",proc.stdout,re.M)
            return name.decode()
        # The platform-independent compiler name and the actual symbol must refer to the same object.
        profiled=unit(rb"(?:pathopt::)?choose_slot");opaque=unit(rb"opaque::native")
        objects={}
        only=[]
        for file in (base/cache).rglob("*.o"):
            need(file.stem not in objects,"ambiguous incremental object")
            objects[file.stem]=sha(file)
            if file.stem in (profiled,opaque):
                names=subprocess.check_output(["nm","-C","--defined-only",file],text=True)
                need("choose_slot" in names if file.stem==profiled else "opaque::native" in names,"unbound native symbol")
                only.append(file.stem)
                shutil.copyfile(file,cap/(file.stem+".o"))
        need(len(only)==2 and len(objects)==len(votes) and profiled!=opaque and str(active) in (base/"result.d").read_text(),
             "profile/assembly sources could not be authenticated to distinct generated modules")
        exe=base/"result"
        values=[rt.record([exe,str(v)],cap/("run-"+str(v)),base,env).stdout.decode().strip() for v in (0,1)]
        rows[phase]={"image":sha(exe),"objects":objects,"profiled":profiled,"opaque":opaque,"votes":{k.decode():v.decode() for k,v in votes.items()},
                     "profile":sha(active),"value":values,"stamp":[now.st_dev,now.st_ino,now.st_size,now.st_mtime_ns]}
        save(cap/"verified.json",rows[phase])
    a,rep,c,new,old = [rows[k] for k in ("old","repeat","change","clean-new","clean-old")]
    need(a["image"]==old["image"]==rep["image"] and a["image"]!=new["image"], "non-discriminating full native program")
    changed={k for k,v in a["objects"].items() if new["objects"].get(k)!=v}
    need(changed=={a["profiled"]} and a["opaque"] not in changed and all(r["value"]==a["value"] for r in rows.values()),
         "a different source unit or functional answer changed under the calibration profiles")
    if expectation=="original-stale":
        need(c["image"]==a["image"] and c["objects"]==a["objects"] and c["votes"][a["profiled"]]=="PostLto" and
             c["votes"][a["opaque"]]=="No","old private candidate failed to reproduce the hypothesized stale object")
    else:
        need(expectation=="protected" and c["image"]==new["image"] and c["objects"]==new["objects"] and set(c["votes"].values())=={"No"},
             "guarded compiler returned stale native output")
    save(dest/"terminal.json",{"sdk":sdk,"expectation":expectation,"source":sha(base/"main.rs"),"changed_unit":list(changed),
                              "rows":rows,"profiles":[sha(base/f"{v}.profdata") for v in (0,1)]})
    print("owner",role,expectation,"stale",c["image"]!=new["image"],"profile-only native unit",changed,flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
