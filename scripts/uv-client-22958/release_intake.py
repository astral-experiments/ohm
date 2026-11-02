"""Verify the signed GNU distribution and the qualified release-trained compiler before running uv."""
from pathlib import Path,PurePosixPath
import hashlib
import json
import os
import runpy
import shutil
import subprocess
import tarfile
import zipfile
import service as s

m=s.m
REPO="astral-experiments/ohm"
DIST="rust-1.99.0-dev-x86_64-unknown-linux-gnu"
COMP=("rustc","cargo","rust-std-x86_64-unknown-linux-gnu")

def transport():
    w,_,_=s.host();_,prior=m.check_sources(w)
    return m.load("signed_release_intake",prior/"intake.py")

def pinned_release(dest):
    source=s.lock["signed_release"]
    data=transport().gh_json("api","--method","GET","repos/"+REPO+"/releases/tags/"+source["tag"])
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

def production(proof,temp,donor,role):
    assert role in ("P", "F")
    if role == "P":
        subject=m.read(s.HERE/"preceding-material.json")
        f=subject["compiler"]
        members={"qa":subject["qa_members"],"sdk":subject["sdk_members"]}
        archive=subject["archive"]
    else:
        f=s.lock["production_compiler"]
        members={"qa":s.lock["production_qa_members"],"sdk":s.lock["production_member_sha256"]}
        archive=s.lock["production_archive"]
    assert f["source"]==s.SOURCES[role]["commit"] and f["tree"]==s.SOURCES[role]["tree"]
    prefix="repos/"+REPO+"/actions/runs/"+str(f["run"])
    run,jobs,art=[donor.gh_json("api","--method","GET",prefix+x) for x in ("","/attempts/1/jobs?per_page=100","/artifacts?per_page=100")]
    for n,row in (("run",run),("jobs",jobs),("artifacts",art)):m.save(proof/(n+".json"),row)
    job,=jobs["jobs"]
    assert jobs["total_count"]==1 and run["event"]=="workflow_dispatch" and run["run_attempt"]==job["run_attempt"]==1
    assert run["id"]==job["run_id"]==f["run"] and job["id"]==f["job"] and run["head_sha"]==job["head_sha"]==f["coordinator"]
    assert run["repository"]["id"]==run["head_repository"]["id"]==1319437234 and run["conclusion"]==job["conclusion"]=="success"
    items={q["name"]:q for q in art["artifacts"]}
    assert len(items)==art["total_count"]==2 and set(items)=={f["sdk"]["name"],f["qa"]["name"]}
    for kind in ("qa","sdk"):
        expect=f[kind];actual=items[expect["name"]]
        assert all(actual[k]==expect[k]for k in ("id","name","size_in_bytes","digest")) and not actual["expired"]
        assert actual["workflow_run"]["id"]==f["run"] and actual["workflow_run"]["head_sha"]==f["coordinator"]
        assert actual["workflow_run"]["repository_id"]==actual["workflow_run"]["head_repository_id"]==1319437234
        dst=temp/(kind+".zip");donor.gh_bytes("repos/"+REPO+"/actions/artifacts/"+str(actual["id"])+"/zip",dst,expect["size_in_bytes"],expect["digest"][7:])
        memberlock=members[kind]
        with zipfile.ZipFile(dst)as z:
            files={i.filename:i for i in z.infolist() if not i.is_dir()}
            assert len(files)==sum(not i.is_dir()for i in z.infolist()) and files.keys()==(set(memberlock)|({"ohm.tar.gz"}if kind=="sdk"else set()))
            for name,checksum in memberlock.items():
                assert files[name].file_size<=80<<20 and not PurePosixPath(name).is_absolute() and ".."not in PurePosixPath(name).parts
                raw=z.read(name);assert m.digest(raw)==checksum
                if kind=="sdk":
                    p=proof/name;p.write_bytes(raw)
            if kind=="sdk":
                target=temp/"production.tar.gz"
                with z.open("ohm.tar.gz")as stream:copy_checked(stream,target,archive["bytes"],archive["sha256"])
    native=m.read(proof/"role.json");source=m.read(proof/"source.json")
    assert source["source"]["commit"]==native["source_commit"]==f["source"] and source["source"]["tree"]==native["source_tree"]==f["tree"]
    assert source["source_pack_sha256"]==f["source_pack"] and source["training_objects"]==f["training_objects"]
    assert native["bolt_note"]is True and native["epoch"]==f["epoch"] and native["execution_pgo"] and native["installed_callable_tests"]
    assert native["installed_original_runmake"] and native["installed_crate_domain_test"]["both_solvers"]
    if role == "F":
        projection=m.read(s.HERE/"derive-projection.json")
        assert source["source"]==projection["source"] and projection["pack_sha256"]==f["derive_pack"]
        assert source["source"]["metadata_epoch"]==source["source"]["epoch"]==43319
        generated=native["installed_generated_impl_test"]
        assert generated["final_linked_output"]=="(5, 11, 7)"
        assert generated["fixture_blobs"]=={p:v["after"]["oid"] for p,v in projection["files"].items() if p.startswith("tests/run-make/proc-derive-impl-identity/")}
    else:
        assert native["role"]=="callables_ctfe318_incoherent_domain" and native["epoch"]==43317
        assert m.filesha(proof/"source.json")==subject["arm"]["source_sha256"] and m.filesha(proof/"role.json")==subject["arm"]["role_sha256"]
    assert native["effective_benchmark_cargo_sha256"]==s.lock["signed_cargo"] and m.read(proof/"sdk-inventory.json")==s.lock["raw"][role]
    return target

def role_sdk(role,path,proof):
    raw=s.lock["raw"][role];expected={n:q["sha256"]for n,q in raw.items()};expected["bin/cargo"]=s.lock["signed_cargo"]
    seen={str(p.relative_to(path)):m.filesha(p) for p in path.rglob("*") if p.is_file()}
    assert seen==expected and not any(p.is_symlink() for p in path.rglob("*"))
    digest=hashlib.sha256(json.dumps(seen,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    assert digest==s.lock["effective_hashes"][role]
    env={"PATH":str(path/"bin")+":/usr/bin:/bin","LC_ALL":"C"}
    rustc,cargo=path/"bin/rustc",path/"bin/cargo"
    banners={n:subprocess.check_output([b,"-Vv"],env=env,text=True).strip() for n,b in (("rustc",rustc),("cargo",cargo))}
    assert ("commit-hash: "+s.SOURCES[role]["commit"])in banners["rustc"].splitlines() and "commit-hash: ed0ae15d22da9a0af9afb3d0fdeb4ceb8a71b770"in banners["cargo"].splitlines()
    assert Path(subprocess.check_output([rustc,"--print","sysroot"],env=env,text=True).strip()).resolve()==path.resolve()
    libs=subprocess.check_output(["ldd",rustc],env=env,text=True);assert "not found" not in libs
    runtime={n:expected[n]for n in ("bin/rustc","bin/rustdoc","bin/cargo")}
    for term in ("librustc_driver-","libLLVM.so."):
        line,=[v for v in libs.splitlines() if term in v];lib=Path(line.split("=>",1)[1].split()[0]).resolve()
        assert path.resolve()/"lib" in lib.parents;rel=str(lib.relative_to(path.resolve()));runtime[rel]=expected[rel]
    proof.mkdir(parents=True,exist_ok=True);m.save(proof/"sdk-inventory.json",raw)
    data={"source":s.SOURCES[role],"runtime":runtime,"effective_inventory":digest,"files":len(seen),"banners":banners,"libraries":libs}
    m.save(proof/"registered.json",data);return data

def stock_production(proof,temp,donor):
    anchor=s.lock["stock"];role=anchor["role"];registered=role["service"]
    route="repos/"+REPO+"/actions/runs/"+str(registered["run"])
    def original(tail,name):
        data=donor.gh_json("api","--method","GET",route+tail);m.save(proof/(name+".json"),data);return data
    run=original("","run")
    assert run["id"]==registered["run"] and run["head_sha"]==registered["head"] and run["head_branch"]==registered["branch"] and run["run_attempt"]==1
    assert run["status"]=="completed"and run["conclusion"]=="success" and run["repository"]["id"]==run["head_repository"]["id"]==1319437234
    jobs=original("/attempts/1/jobs?per_page=100","jobs");assert len(jobs["jobs"])==jobs["total_count"]==3
    actual_jobs={str(j["id"]):{k:j[k]for k in ("name","runner_name","labels")}for j in jobs["jobs"]}
    assert actual_jobs==anchor["jobs"] and all(j["head_sha"]==registered["head"]and j["run_id"]==run["id"] and j["run_attempt"]==1 and j["status"]=="completed"and j["conclusion"]=="success"for j in jobs["jobs"])
    arts=original("/artifacts?per_page=100","artifacts");assert len(arts["artifacts"])==arts["total_count"]==5
    rows={a["name"]:a for a in arts["artifacts"]};assert set(rows)==set(registered["members"])
    for name,c in registered["members"].items():
        a=rows[name];r=a["workflow_run"]
        assert a["digest"]=="sha256:"+c["sha256"] and a["id"]==c["id"] and a["size_in_bytes"]==c["bytes"] and not a["expired"]
        assert r["id"]==registered["run"]and r["head_sha"]==registered["head"]and r["repository_id"]==r["head_repository_id"]==1319437234
    target=temp/"stock.tar.gz"
    for name in (anchor["qa"],anchor["pair"],anchor["sdk"]):
        c=registered["members"][name];dst=temp/(name+".zip")
        donor.gh_bytes("repos/"+REPO+"/actions/artifacts/"+str(c["id"])+"/zip",dst,c["bytes"],c["sha256"])
        sdk=name==anchor["sdk"];locked=anchor["files"]if sdk else anchor["archives"][name]
        with zipfile.ZipFile(dst)as z:
            files={i.filename:i for i in z.infolist()if not i.is_dir()}
            assert len(files)==sum(not i.is_dir()for i in z.infolist()) and set(files)==set(locked)|({"ohm.tar.gz"}if sdk else set())
            for path,h in locked.items():
                assert files[path].file_size<80<<20 and not PurePosixPath(path).is_absolute()and ".."not in PurePosixPath(path).parts
                raw=z.read(path);assert m.digest(raw)==h
                if sdk:(proof/path).write_bytes(raw)
            if sdk:
                with z.open("ohm.tar.gz")as content:copy_checked(content,target,anchor["tar"]["bytes"],anchor["tar"]["sha256"])
    source=m.read(proof/"source.json");native=m.read(proof/"role.json")
    assert m.filesha(proof/"source.json")==role["source_sha256"]and m.filesha(proof/"role.json")==role["role_sha256"]
    assert {k:source["source"][k]for k in s.SOURCES["S"]}==s.SOURCES["S"]and source["run_id"]==registered["run"]
    assert source["source"]["parent"]==s.lock["signed_release"]["rustc"] and source["source"]["upstream_ctfe_commit"]=="df2c077a113a709ab379c8ec34e62c94c7513325"
    assert native["role"]=="stock_ctfe318"and native["source_commit"]==s.SOURCES["S"]["commit"]and native["source_tree"]==s.SOURCES["S"]["tree"]
    assert native["epoch"]==s.SOURCES["S"]["epoch"]and native["bolt_note"]is True and native["execution_pgo"]and native["installed_original_runmake"]
    assert native["effective_benchmark_cargo_sha256"]==s.lock["signed_cargo"]and m.read(proof/"sdk-inventory.json")==s.lock["raw"]["S"]
    return target

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

def admit():
    w,tmp,_=s.host();out=w/"trait-results";proof=out/"intake";proof.mkdir();temp=tmp/"release-22958-incoming";temp.mkdir()
    sdk=tmp/"ctfe22-root-sdks";sdk.mkdir();old=transport()
    pinned_release(proof/"release.json");old.released(temp,proof)
    signed,=(temp/"signed").glob("*.tar.gz");assert m.filesha(signed)==s.lock["signed_release"]["sha256"]
    cargo=signed_cargo(signed,temp/"official-22-cargo")
    stock=proof/"corrected-stock";stock.mkdir();control=stock_production(stock,temp,old)
    archives={"S":control}
    for role in ("P","F"):
        product=proof/("production-"+role);product.mkdir();incoming=temp/role;incoming.mkdir()
        archives[role]=production(product,incoming,old,role)
    for r,a in archives.items():
        install_archive(a,sdk/r,r)
        assert m.filesha(sdk/r/"bin/cargo")==s.lock["raw"][r]["bin/cargo"]["sha256"]
        shutil.copy2(cargo,sdk/r/"bin/cargo")
    result={r:role_sdk(r,sdk/r,proof/"role-material"/r)for r in s.ROLES}
    m.save(out/"intake.json",{"installed":result,"signed_cargo_sha256":s.lock["signed_cargo"],"release_lock":m.filesha(s.HERE/"release-lock.json")})

def migration():
    w,tmp,_=s.host()
    verify_migrations(tmp/"ctfe22-root-sdks",w/"trait-results/intake",tmp)

def verify_migrations(pool,out,tmp):
    env={"PATH":"/usr/bin:/bin","LC_ALL":"C","RUSTC_BOOTSTRAP":"1"}
    results={}
    for first,second in ((a,b) for a in s.ROLES for b in s.ROLES if a!=b):
        scope=tmp/("fixture-22958-"+first+second);scope.mkdir();src=scope/"main.rs";bin=scope/"fixture";rows=[]
        for role,val,cache in ((first,7,"shared"),(second,19,"shared"),(second,19,"independent")):
            src.write_text('const VALUE: i32 = '+str(val)+'; fn main() { println!("{}", VALUE); }\n')
            argv=[str(pool/role/"bin/rustc"),"--edition=2021","--crate-name","cross_fmt",str(src),"-Cincremental="+str(scope/cache),"-o",str(bin)]
            proc=subprocess.run(argv,capture_output=True,env=env,timeout=120);assert proc.returncode==0 and not proc.stderr
            observed=subprocess.check_output([bin],env=env);assert observed==(str(val)+"\n").encode()
            rows.append(dict(role=role,argv=argv,observed=observed.decode().strip(),source=m.filesha(src),binary=m.filesha(bin)))
        assert rows[1]["binary"]==rows[2]["binary"]
        results[first+"-"+second]=rows
    expected = {"S": (43310, 3), "P": (43317, 3), "F": (43319, 43319)}
    wire = s.HERE / "derive-boundary"
    increment = runpy.run_path(str(wire / "epoch.py"))["run"]
    metadata = runpy.run_path(str(wire / "metadata_epoch.py"))["metadata"]
    proofs = {}
    for first, second in (("S", "P"), ("S", "F"), ("P", "F")):
        pair = first + "-" + second
        sources = {s.SOURCES[r]["commit"]: expected[r] for r in (first, second)}
        assert all(s.SOURCES[r]["epoch"] == expected[r][0] for r in (first, second))
        inc_dir = out / ("format-incremental-" + pair)
        meta_dir = out / ("format-metadata-" + pair)
        increment(pool/first, pool/second, inc_dir, "actual", expected=[(rev, value[0]) for rev, value in sources.items()])
        metadata({s.SOURCES[r]["commit"]:pool/r for r in (first, second)}, meta_dir, expected=sources)
        inc, meta = m.read(inc_dir/"passed.json"), m.read(meta_dir/"passed.json")
        assert inc["signed_argv_refusal_both_directions"] and inc["same_sdk_self_loaded_before_and_after"] and inc["reader_compilations"]==10
        assert inc["no_header_edit"] and inc["no_compiler_version_override"]
        assert meta["cross_crate_E0514"]==meta["own_crate_reads"]==meta["own_native_typecheck_errors"]==2
        assert not meta["file_edits"] and not meta["compiler_version_overrides"]
        proofs[pair] = {"incremental":m.filesha(inc_dir/"passed.json"), "metadata":m.filesha(meta_dir/"passed.json")}
    m.save(out/"release-migration.json", {"fixtures_only":True, "roles":results, "ordinary_benchmark_caches_separate":True, "native_format_proofs":proofs})
