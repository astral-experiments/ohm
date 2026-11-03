"""Identify live hard-linked Cargo rlibs without relying on their crate spelling."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import tomllib

def keep(raw,label,out):
    key=hashlib.sha256(raw).hexdigest();p=out/(label+"-"+key+".gz")
    if not p.exists():p.write_bytes(gzip.compress(raw,compresslevel=4,mtime=0))
    return {"bytes":len(raw),"sha256":key,"raw":p.name}

def records(root,owners):
    assert owners and len(set(owners))==len(owners)
    rows={}
    for raw in owners:
        p=Path(raw)
        assert p==p.resolve(strict=True) and p.name=="Cargo.toml" and p.is_relative_to(root/"compiler")
        b=p.read_bytes();toml=tomllib.loads(b.decode());src=(p.parent/toml.get("lib",{}).get("path","src/lib.rs")).resolve()
        rows[str(p)]={"name":toml["package"]["name"],"sha256":hashlib.sha256(b).hexdigest(),"lib":str(src)}
    return rows

def opened(w,d):
    root=(w/"source/rust").resolve(strict=True);triple="x86_64-unknown-linux-gnu";build=root/"build"/triple
    assert (d/"driver").read_bytes()==os.fsencode((root/"compiler/rustc_driver").resolve(strict=True))
    owners=records(root,json.loads((d/"owners").read_bytes()))
    opened={}
    try:
        for p in sorted(d.glob("*.rlib")):
            f=p.open("rb");st=os.fstat(f.fileno());key=f"{st.st_dev:x}-{st.st_ino:x}"
            assert stat.S_ISREG(st.st_mode) and p.name==key+".rlib" and key not in opened and st.st_nlink>=2
            opened[key]={"f":f,"paths":[],"receipt":str(p),"dev":st.st_dev,"ino":st.st_ino,"mode":st.st_mode,"nlink":st.st_nlink,"bytes":st.st_size,"mtime_ns":st.st_mtime_ns}
        assert opened,"no source-owned nonlocal Cargo artifact inode observed"
        for stage in build.glob("stage*-rustc"):
            profiles={*stage.glob("*/release"),stage/"release",*stage.glob("*/debug"),stage/"debug"}
            dirs={d for profile in profiles for d in (profile,profile/"deps",*profile.glob("build/*/*/out"))}
            for dep in dirs:
                if not dep.is_dir():continue
                for f in dep.glob("*.rlib"):
                    try:st=f.stat()
                    except FileNotFoundError:continue
                    key=f"{st.st_dev:x}-{st.st_ino:x}"
                    if key in opened:opened[key]["paths"].append(str(f))
        for row in opened.values():assert row["paths"],("no matching actual staged rlib",row["receipt"])
    except BaseException:
        for row in opened.values():row["f"].close()
        raise
    return root,owners,opened

def finish(snapshot,out):
    root,owners,rows=snapshot
    try:
        for row in rows.values():
            f=row["f"];row["sha256"]=hashlib.file_digest(f,"sha256").hexdigest();tail=os.fstat(f.fileno())
            assert (tail.st_dev,tail.st_ino,tail.st_size,tail.st_mtime_ns)==tuple(row[k] for k in ("dev","ino","bytes","mtime_ns"))
            pair=[]
            for name in sorted(row["paths"]):
                a=Path(name);dep=a.with_name(a.name.removeprefix("lib").removesuffix(".rlib")+".d")
                if not dep.is_file():continue
                raw=dep.read_bytes();assert 0<len(raw)<32<<20
                relevant=[s.partition(b": ")[2] for s in raw.splitlines() if s.startswith(os.fsencode(name)+b": ")]
                if not relevant:continue
                inputs=shlex.split(os.fsdecode(relevant[0]));assert inputs
                input_file=(root/inputs[0]).resolve(strict=True)
                claims=[p for p,v in owners.items() if Path(v["lib"])==input_file]
                if len(claims)==1:
                    pair.append({"rlib":name,"manifest":claims[0],"source":str(input_file),"dep_info":keep(raw,"rlib-dep-info",out)})
            assert pair and len({p["manifest"] for p in pair})==1,("artifact lacks a unique registered source",row["paths"])
            row["observed_native_sources"]=pair
    finally:
        for row in rows.values():row.pop("f").close()
    return {"owners":owners,"receipts":rows,"provenance":"Archive identity and source comes from native device/inode, the staged bytes and rustc dep-info. Bootstrap creates a hard link only after its own Cargo manifest and target-ownership checks."}
