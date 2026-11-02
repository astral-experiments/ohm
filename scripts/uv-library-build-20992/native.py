"""Capture the real ordinary build, its exact mutable seed and the linked production CLI witness."""
from pathlib import Path
import gzip
import hashlib
import json
import os
import tarfile
import re
import resource
import shutil
import subprocess
import sys
import time
import types
import material
import linked
import unit_graph

V=material.V;SRC=material.S;SDK=V/"sdk";TARGET=V/"target";CARGO=SDK/"bin/cargo"
CMD=["build","--locked","--offline","-j8","-p","uv-cli"]
MUT=["source","target","home","tmp","cargo-home"]
ROOT=Path(os.environ["OHM20992_RESULT"]).resolve()
TRANSIENT=Path(os.environ["OHM20992_TRANSIENT"]).resolve()
sha=material.filehash
def read(p):return json.loads(p.read_bytes())
def save(p,obj):material.save(p,obj)
def environment():
    return dict(material.E,PATH=str(SDK/"bin")+":/usr/bin:/bin",HOME=str(V/"home"),TMPDIR=str(V/"tmp"),CARGO_HOME=str(V/"cargo-home"),
        CARGO_TARGET_DIR=str(TARGET),CARGO_NET_OFFLINE="true",CARGO_TERM_COLOR="never",RUSTC=str(SDK/"bin/rustc"),TZ="UTC")
def sdk_identity(role):
    s=read(ROOT/"sdk-identities.json")[role]
    assert sha(CARGO)==s["cargo"]=="3ce4e300d4463dfc769b6c18e138d1c951b02dfb15416a39cb5301303d168871"
    driver,=(SDK/"lib").glob("librustc_driver*.so")
    assert sha(driver)==s["driver"]
    version=subprocess.check_output([SDK/"bin/rustc","-vV"],env=environment()).decode()
    assert "commit-hash: "+s["source"] in version
    stat=CARGO.stat();assert CARGO.resolve()==CARGO
    sysroot=subprocess.check_output([SDK/"bin/rustc","--print","sysroot"],env=environment(),text=True).strip();assert sysroot==str(SDK)
    launcher=(SDK/"bin/rustc").stat()
    return dict(role=role,source=s["source"],driver=s["driver"],cargo=s["cargo"],version=version,selected_driver=driver.name,cargo_file=[stat.st_dev,stat.st_ino,stat.st_size],canonical_cargo=str(CARGO.resolve()),canonical_sysroot=sysroot,launcher=sha(SDK/"bin/rustc"),launcher_file=[launcher.st_dev,launcher.st_ino,launcher.st_size])
def snapshot():
    digest=hashlib.sha256();count=0;memo={}
    for name in MUT:
        root=V/name
        for f in sorted(root.rglob("*")):
            st=f.lstat()
            if f.is_symlink():value=os.readlink(f)
            elif f.is_file():
                key=(st.st_dev,st.st_ino,st.st_size)
                if key not in memo:memo[key]=sha(f)
                value=memo[key]
            else:
                assert f.is_dir();continue
            digest.update(json.dumps([str(f.relative_to(V)),st.st_mode,st.st_mtime_ns,st.st_size,value],separators=(",",":")).encode()+b"\n");count+=1
    assert count>1608;return {"count":count,"sha256":digest.hexdigest()}
def archive_seed(seed,receipt):
    assert not seed.exists()
    subprocess.run(["/usr/bin/tar","--sort=name","--format=pax","--pax-option=delete=atime,delete=ctime","-I","zstd -T2 -2 --no-progress","-cf",seed,"-C",V,*MUT],env=environment(),check=True)
    assert 0<seed.stat().st_size<1800<<20
    seed.chmod(0o400)
    assert 0 < seed.stat().st_size <= 1 << 30, "compressed original A seed exceeds its one-GiB slot"
    save(receipt,dict(bytes=seed.stat().st_size,sha256=sha(seed),files=snapshot()))
def clear_mutable():
    assert V==Path("/tmp/ohm-over18-named-test") and (V/".owned-20992").is_file()
    for n in MUT:
        d=V/n;assert d.parent==V and d.name in MUT and not d.is_symlink()
        if d.exists():shutil.rmtree(d)
def restore(seed,receipt):
    assert seed.is_file() and seed.stat().st_size==receipt["bytes"] and sha(seed)==receipt["sha256"]
    clear_mutable();subprocess.run(["/usr/bin/tar","--zstd","--no-same-owner","-xf",seed,"-C",V],env={"PATH":"/usr/bin:/bin"},check=True)
    assert snapshot()==receipt["files"]
    return material.auth_source(SRC,"A")
def inventory():
    result={};memo={}
    for p in sorted(TARGET.rglob("*")):
        if not p.is_file() or p.is_symlink():continue
        rel=p.relative_to(TARGET)
        if "incremental" in rel.parts:continue
        st=p.stat()
        match=p.suffix in {".rmeta",".rlib",".a",".o",".so"} or p.name.endswith((".public-hash",".public-api-hash"))
        if not match and st.st_mode&0o111:
            with p.open("rb") as f:match=f.read(4)==b"\x7fELF"
        if match:
            ident=(st.st_dev,st.st_ino,st.st_size)
            if ident not in memo:memo[ident]=sha(p)
            result[str(rel)]={"sha256":memo[ident],"bytes":st.st_size}
    assert len(result)==1794 and len([n for n in result if n.endswith(".rmeta")])==448 and len([n for n in result if n.endswith((".public-hash",".public-api-hash"))])==448
    return result
def selected(prods):
    result={}
    for name,pkg in [("uv_python","uv-python"),("uv_cli","uv-cli")]:
        reg=re.compile(r"^debug/build/"+pkg+r"/([a-f0-9]{16})/out/lib"+name+r"-\1\.rlib$")
        file,=(k for k in prods if reg.fullmatch(k))
        assert (TARGET/file).is_file() and sha(TARGET/file)==prods[file]["sha256"]
        result[name]=file
    alias="debug/libuv_cli.rlib"
    assert prods[alias]==prods[result["uv_cli"]] and (TARGET/alias).read_bytes()==(TARGET/result["uv_cli"]).read_bytes()
    result["uv_cli_alias"]=alias
    return result
def run_command(out,args,env=None):
    out.mkdir(exist_ok=False,parents=True)
    with (out/"stdout").open("xb")as so,(out/"stderr").open("xb")as se:
        before=system_readings()
        start=time.monotonic_ns();p=subprocess.Popen([str(s)for s in args],cwd=SRC,env=environment() if env is None else env,stdout=so,stderr=se)
        pid,st,usage=os.wait4(p.pid,0);end=time.monotonic_ns();assert pid==p.pid
        p.returncode=os.waitstatus_to_exitcode(st)
    record=dict(argv=list(map(str,args)),source=str(SRC),exit=p.returncode,start_monotonic_ns=start,end_monotonic_ns=end,wall_ns=end-start,
        before=before,after=system_readings(),wait4={k:getattr(usage,k) for k in ["ru_utime","ru_stime","ru_minflt","ru_majflt","ru_inblock","ru_oublock","ru_nvcsw","ru_nivcsw","ru_maxrss"]},
        stdout=sha(out/"stdout"),stderr=sha(out/"stderr"))
    save(out/"record.json",record);assert p.returncode==0,(out,(out/"stderr").read_text(errors="replace")[-900:]);return record
def system_readings():
    files={k:Path(k).read_text().strip() for k in ["/proc/loadavg","/proc/pressure/cpu","/proc/pressure/io","/sys/fs/cgroup/cpu.stat"] if Path(k).is_file()}
    return {"affinity":sorted(os.sched_getaffinity(0)),"files":files}
def ordinary(out,verbose=False):
    return run_command(out,[CARGO,*CMD,*(["-vv"] if verbose else [])])
def registered_registry_units(raw,prefix,actual_root):
    comparable=json.loads(json.dumps(raw))
    packages={f"{n}-{v}":(n,v,h) for n,v,h in material.CASE["packages"]};requests={};dirs=set();units=0
    for u in comparable["units"]:
        if not u["pkg_id"].startswith("registry+"):continue
        target=u["target"];physical=Path(target["src_path"]);parts=physical.relative_to(prefix).parts
        assert len(parts)>=3 and parts[1] in packages and (actual_root/Path(*parts)).is_file() and ".."not in parts
        name,vers,checksum=packages[parts[1]];assert u["pkg_id"]==f"registry+https://github.com/rust-lang/crates.io-index#{name}@{vers}"
        dirs.add(parts[0]);units+=1;requests.setdefault(parts[1],set()).update(("Cargo.toml",Path(*parts[2:]).as_posix()))
        # Only compare the installed registry path component after authenticating each
        # actual manifest and unit source against its locked public crate archive.
        target["src_path"]=str(prefix/material.INDEX/Path(*parts[1:]))
    assert len(dirs)==1 and units==519;directory,=dirs;proof={}
    for pkg,paths in sorted(requests.items()):
        archive=actual_root.parent/"cache"/directory/(pkg+".crate");assert sha(archive)==packages[pkg][2]
        seen={}
        with tarfile.open(archive,"r|gz")as tar:
            for member in tar:
                dest=Path(member.name)
                if dest.parts[:1]!=(pkg,):continue
                name=Path(*dest.parts[1:]).as_posix()
                if name not in paths:continue
                physical=actual_root/directory/dest;assert member.isfile() and name not in seen and physical.read_bytes()==tar.extractfile(member).read()
                seen[name]=sha(physical)
        assert seen.keys()==paths;proof[pkg]={"archive":packages[pkg][2],"physical":seen}
    return comparable,proof

def graph(out):
    run_command(out,[CARGO,"build","--unit-graph","-Zunstable-options",*CMD[1:]])
    raw=json.loads((out/"stdout").read_bytes());ref=json.loads(gzip.decompress((material.HERE/"prior-unit-graph.json.gz").read_bytes()))
    prefix=V/"cargo-home/registry/src"
    comparable,proof=registered_registry_units(raw,prefix,prefix);save(out/"registry-source-roots.json",proof)
    result=unit_graph.prove(ref,comparable);assert sum(len(u["dependencies"]) for u in raw["units"])==1902
    save(out/"graph-proof.json",result);return result
def witness(where,role,state,driver):
    cache=TRANSIENT/"witness"
    if cache.exists():
        assert cache.parent==TRANSIENT;shutil.rmtree(cache)
    unit=linked.lib(TARGET)
    e=types.SimpleNamespace(TARGET=TARGET,SDK=SDK,SRC=SRC,environment=environment,ID={role:{"driver_sha256":driver}})
    q=types.SimpleNamespace(read=read,sha=sha)
    row=linked.probe(e,q,unit,unit,role,state,cache);save(where/"linked.json",row);linked.check_probe(row)
    return row
def open_seed(role,hold,donor,bank):
    where=ROOT/f"opening-{role}-{hold}";where.mkdir(parents=True)
    info=sdk_identity(role);save(where/"sdk.json",info)
    clear_mutable()
    for name in ["home","tmp","cargo-home","target"]:(V/name).mkdir()
    (V/"cargo-home/registry").symlink_to(bank.resolve(),target_is_directory=True)
    save(where/"material-A.json",material.install(donor,SRC));graph(where/"unit-graph")
    ordinary(where/"ordinary-cold-A",True)
    prods=inventory();save(where/"cold-A-products.json",prods);paths=selected(prods);save(where/"cold-A-selected.json",paths)
    witness(where,role,"A",info["driver"])
    seed=TRANSIENT/f"seed-{role}-{hold}.tar.zst";archive_seed(seed,where/"seed.json")
    return where,seed,prods,paths

