"""Verify the signed GNU distribution and the qualified release-trained compiler before running uv."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import runpy
import shutil
import subprocess
import tarfile
import service as s

m=s.m
REPO="astral-experiments/ohm"
DIST="rust-1.99.0-dev-x86_64-unknown-linux-gnu"
COMP=("rustc","cargo","rust-std-x86_64-unknown-linux-gnu")

def transport():
    w,_,_=s.host();_,prior=m.check_sources(w)
    return m.load("signed_release_intake",prior/"intake.py")

def latest(dest):
    data=transport().gh_json("api","--method","GET","repos/"+REPO+"/releases/latest")
    source=s.lock["signed_release"]
    assert data["id"]==source["release_id"] and data["tag_name"]==source["tag"] and data["target_commitish"]==source["coordinator"]
    assert data["immutable"] and not data["draft"] and not data["prerelease"]
    m.save(dest,data)

def copy_checked(src,path,length,checksum):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("xb") as out:shutil.copyfileobj(src,out,1<<20)
    assert path.stat().st_size==length and m.filesha(path)==checksum

def install_archive(archive,dest,role):
    assert not dest.exists()
    inv=s.lock["raw"][role];seen=set();manifests={}
    dest.mkdir(parents=True)
    with tarfile.open(archive,"r|gz")as tar:
        for item in tar:
            parts=PurePosixPath(item.name).parts
            if len(parts)<3 or parts[0]!=DIST or parts[1]not in COMP:continue
            assert not item.name.startswith("/") and ".." not in parts and "\\" not in item.name
            comp=parts[1];rel="/".join(parts[2:])
            if rel=="manifest.in":
                assert comp not in manifests and item.isfile() and 0<item.size<500_000
                lines=tar.extractfile(item).read().decode().splitlines();assert all(v.startswith("file:") for v in lines)
                manifests[comp]=[v[5:]for v in lines]
                continue
            if rel not in inv or inv[rel]["component"]!=comp:continue
            row=inv[rel]
            assert rel not in seen and item.isfile() and item.size==row["bytes"] and bool(item.mode&0o111)==bool(row["mode"]&0o111)
            with tar.extractfile(item)as src:copy_checked(src,dest/rel,row["bytes"],row["sha256"])
            (dest/rel).chmod(0o755 if row["mode"]&0o111 else 0o644);seen.add(rel)
    assert seen==set(inv) and set(manifests)==set(COMP)
    for comp,rows in manifests.items():assert len(rows)==len(set(rows)) and set(rows)=={n for n,r in inv.items()if r["component"]==comp}

def role_sdk(role,path,proof):
    raw=s.lock["raw"][role];expected={n:q["sha256"]for n,q in raw.items()};expected["bin/cargo"]=s.lock["signed_cargo"]
    seen={str(p.relative_to(path)):m.filesha(p) for p in path.rglob("*") if p.is_file()}
    assert seen==expected and not any(p.is_symlink() for p in path.rglob("*"))
    digest=hashlib.sha256(json.dumps(seen,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    assert digest==s.lock["effective_hashes"][role]
    env={"PATH":str(path/"bin")+":/usr/bin:/bin","LC_ALL":"C"}
    rustc,cargo=path/"bin/rustc",path/"bin/cargo"
    banners={n:subprocess.check_output([b,"-Vv"],env=env,text=True).strip() for n,b in (("rustc",rustc),("cargo",cargo))}
    assert ("commit-hash: "+s.SOURCES[role]["commit"]) in banners["rustc"].splitlines()
    assert ("commit-hash: "+s.lock["signed_release"]["cargo"]) in banners["cargo"].splitlines()
    assert Path(subprocess.check_output([rustc,"--print","sysroot"],env=env,text=True).strip()).resolve()==path.resolve()
    libs=subprocess.check_output(["ldd",rustc],env=env,text=True);assert "not found" not in libs
    runtime={n:expected[n]for n in ("bin/rustc","bin/rustdoc","bin/cargo")}
    for term in ("librustc_driver-","libLLVM.so."):
        line,=[v for v in libs.splitlines() if term in v];lib=Path(line.split("=>",1)[1].split()[0]).resolve()
        assert path.resolve()/"lib" in lib.parents;rel=str(lib.relative_to(path.resolve()));runtime[rel]=expected[rel]
    proof.mkdir(parents=True,exist_ok=True);m.save(proof/"sdk-inventory.json",raw)
    data={"source":s.SOURCES[role],"runtime":runtime,"effective_inventory":digest,"files":len(seen),"banners":banners,"libraries":libs}
    m.save(proof/"registered.json",data);return data

def signed_cargo(archive,target):
    row=s.lock["signed_cargo_row"];assert row["sha256"]==s.lock["signed_cargo"]
    matches=0;manifest=None
    with tarfile.open(archive,"r|gz")as t:
        for item in t:
            if item.name==DIST+"/cargo/manifest.in":
                assert item.isfile()and manifest is None;manifest=t.extractfile(item).read().decode().splitlines()
            elif item.name==DIST+"/cargo/bin/cargo":
                matches+=1;assert matches==1 and item.isfile()and item.size==row["bytes"]and item.mode&0o111
                copy_checked(t.extractfile(item),target,row["bytes"],row["sha256"]);target.chmod(0o755)
    assert matches==1 and manifest.count("file:bin/cargo")==1
    return target

def migration():
    w,tmp,_=s.host()
    verify_migrations(tmp/"uv22958-release-sdks",w/"trait-results/intake",tmp)

def verify_migrations(pool,out,tmp):
    env={"PATH":"/usr/bin:/bin","LC_ALL":"C","RUSTC_BOOTSTRAP":"1"}
    results={}
    for first,second in (s.ROLES, tuple(reversed(s.ROLES))):
        scope=tmp/("fixture-22958-"+first+second);scope.mkdir();src=scope/"main.rs";bin=scope/"fixture";rows=[]
        for role,val,cache in ((first,7,"shared"),(second,19,"shared"),(second,19,"independent")):
            src.write_text('const VALUE: i32 = '+str(val)+'; fn main() { println!("{}", VALUE); }\n')
            argv=[str(pool/role/"bin/rustc"),"--edition=2021","--crate-name","cross_fmt",str(src),"-Cincremental="+str(scope/cache),"-o",str(bin)]
            proc=subprocess.run(argv,capture_output=True,env=env,timeout=120);assert proc.returncode==0 and not proc.stderr
            observed=subprocess.check_output([bin],env=env);assert observed==(str(val)+"\n").encode()
            rows.append(dict(role=role,argv=argv,observed=observed.decode().strip(),source=m.filesha(src),binary=m.filesha(bin)))
        assert rows[1]["binary"]==rows[2]["binary"]
        results[first+"-"+second]=rows
    stock, candidate = (s.SOURCES[role] for role in s.ROLES)
    epochs = {row["commit"]: (row["epoch"], row["metadata_epoch"]) for row in (stock, candidate)}
    wire = s.HERE / "derive-boundary"
    increment = runpy.run_path(str(wire / "epoch.py"))["run"]
    metadata = runpy.run_path(str(wire / "metadata_epoch.py"))["metadata"]
    inc_dir, meta_dir = out / "incremental-boundary", out / "metadata-boundary"
    increment(pool/s.CONTROL, pool/"F", inc_dir, "actual", expected=[(rev, pair[0]) for rev,pair in epochs.items()])
    metadata({stock["commit"]:pool/s.CONTROL, candidate["commit"]:pool/"F"}, meta_dir, expected=epochs)
    inc, meta = m.read(inc_dir/"passed.json"), m.read(meta_dir/"passed.json")
    assert inc["signed_argv_refusal_both_directions"] and inc["same_sdk_self_loaded_before_and_after"] and inc["reader_compilations"]==10
    assert inc["no_header_edit"] and inc["no_compiler_version_override"]
    assert meta["cross_crate_E0514"]==meta["own_crate_reads"]==meta["own_native_typecheck_errors"]==2
    assert not meta["file_edits"] and not meta["compiler_version_overrides"]
    m.save(out/"release-migration.json",{"fixtures_only":True,"roles":results,"ordinary_benchmark_caches_separate":True,
           "native_format_proofs":{"incremental":m.filesha(inc_dir/"passed.json"),"metadata":m.filesha(meta_dir/"passed.json")}})
