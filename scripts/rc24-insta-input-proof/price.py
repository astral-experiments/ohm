"""Price immutable Cargo binaries on one source checkout and reopen native and compiler verdicts."""
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess as sp
import tarfile
import time
import tomllib
import urllib.request
from zipfile import ZipFile

kit=Path(__file__).resolve().parent
workspace=Path(os.environ["GITHUB_WORKSPACE"])
source=workspace/"ruff"
pair=workspace/"pair"
reg=json.loads((kit/"registration.json").read_bytes())
enroll=json.loads((kit/"pricing.json").read_bytes())
work=Path(os.environ["RUNNER_TEMP"])/"insta-price"
proof=work/"proof"
target=work/"target"
shared=work/"shared"
sdk=work/"sdk"
rustup=work/"rustup"
home=work/"cargo-home"
role=os.environ["PRICE_BLOCK"]
prefix=reg["normal_project"]["command"]
old=reg["normal_project"]["old"]
new=reg["normal_project"]["new"]
assert role in enroll["orders"] and prefix[:2]==["cargo","+ohm"]

def sha(path):
    with path.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()

def write(path,data):
    path.write_text(json.dumps(data,sort_keys=True,indent=2)+"\n")

def git(*args):
    return sp.check_output(["git",*args],cwd=source,text=True).strip()

def standard():
    e={k:os.environ[k] for k in ("PATH","HOME","USER","LANG","TZ","TMPDIR") if k in os.environ}
    e.update(CARGO_TARGET_DIR=str(target),CARGO_BUILD_BUILD_DIR=str(shared),CARGO_HOME=str(home),
             RUSTUP_HOME=str(rustup),CARGO_NET_OFFLINE="true")
    return e

def install():
    proof.mkdir(parents=True)
    manifest=json.loads((kit/"release-compiler.json").read_bytes())
    lookup={v["source"]:(k,v) for k,v in manifest["members"].items()}
    env={"PATH":os.environ["PATH"],"HOME":os.environ["HOME"],"GH_TOKEN":os.environ.pop("OHM_READ_TOKEN")}
    ep="repos/astral-experiments/ohm/releases/assets/707031606"
    row=json.loads(sp.check_output(["gh","api",ep],env=env))
    assert row["digest"]=="sha256:"+manifest["tar_sha256"] and row["size"]==360088078
    archive=work/"release.tar.gz"
    with archive.open("xb") as f:sp.run(["gh","api","-H","Accept: application/octet-stream",ep],env=env,stdout=f,check=True)
    assert sha(archive)==reg["release_sha256"]==manifest["tar_sha256"]
    artifact="repos/astral-experiments/ohm/actions/artifacts/"+str(enroll["pair_asset"])
    received=json.loads(sp.check_output(["gh","api",artifact],env=env))
    assert received["digest"]=="sha256:"+enroll["pair_zip"] and received["workflow_run"]["id"]==enroll["producer_run"]
    original=work/"pair.zip"
    with original.open("xb") as f:sp.run(["gh","api",artifact+"/zip"],env=env,stdout=f,check=True)
    assert sha(original)==enroll["pair_zip"] and original.stat().st_size==received["size_in_bytes"]
    with ZipFile(original) as z:
        assert sorted(n for n in z.namelist() if not n.endswith("/"))==["build.json","candidate/cargo","parent/cargo"]
        for name in ("build.json","candidate/cargo","parent/cargo"):
            dest=pair/name
            dest.parent.mkdir(parents=True,exist_ok=True)
            with z.open(name) as f,dest.open("xb") as out:shutil.copyfileobj(f,out)
    done=set()
    with tarfile.open(archive,"r|gz") as tar:
        for m in tar:
            if m.name not in lookup:continue
            n,record=lookup[m.name]
            assert m.isfile() and m.size==record["bytes"] and n not in done and not Path(n).is_absolute() and ".." not in Path(n).parts
            p=sdk/n
            p.parent.mkdir(parents=True,exist_ok=True)
            with tar.extractfile(m) as f,p.open("xb") as to:shutil.copyfileobj(f,to)
            assert sha(p)==record["sha256"]
            p.chmod(0o755 if m.mode & 0o111 else 0o644)
            done.add(n)
    assert done==set(manifest["members"]) and len(done)==79
    (rustup/"toolchains").mkdir(parents=True)
    (rustup/"toolchains/ohm").symlink_to(sdk)
    assert git("rev-parse",new+"^")==old and git("diff","--name-only",old,new).splitlines()==enroll["ruff_paths"]
    assert sha(source/"Cargo.lock")==enroll["ruff_lock"]
    assert not git("status","--porcelain")
    e=standard()
    vv=sp.check_output(["rustc","+ohm","-vV"],cwd=source,env=e,text=True)
    assert reg["rust"] in vv
    proof_pair=json.loads((pair/"build.json").read_bytes())
    assert proof_pair["qa"]==enroll["producer_head"] and proof_pair["run"]==str(enroll["producer_run"])
    for arm in ("parent","candidate"):
        assert sha(pair/arm/"cargo")==enroll["cargo"][arm]==proof_pair["cargo"][arm]["sha256"]
        assert reg[arm]==proof_pair["cargo"][arm]["source"]
        (pair/arm/"cargo").chmod(0o755)
    online=dict(e,CARGO_NET_OFFLINE="false")
    sp.run(["cargo","+ohm","fetch","--locked"],cwd=source,env=online,check=True)
    lock=tomllib.loads((source/"Cargo.lock").read_text())
    required={p["name"]+"-"+p["version"]+".crate":p["checksum"] for p in lock["package"] if "source" in p}
    cache,=list((home/"registry/cache").iterdir())
    for pkg in (p for p in lock["package"] if "source" in p):
        f=cache/(pkg["name"]+"-"+pkg["version"]+".crate")
        if not f.exists():
            with urllib.request.urlopen("https://static.crates.io/crates/"+pkg["name"]+"/"+f.name,timeout=60) as resp,f.open("xb") as dest:
                shutil.copyfileobj(resp,dest)
    archives={p.name:sha(p) for p in cache.glob("*.crate")}
    assert required and required==archives
    home.rename(work/"enrolled-cargo-home")
    write(proof/"admission.json",{"source":new,"old":old,"release":reg["release_sha256"],"rustc":vv,
          "pair":proof_pair,"archives":archives,"boot":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
          "cpus":sorted(os.sched_getaffinity(0)),"order":enroll["orders"][role],"head":os.environ["GITHUB_SHA"]})
    for name in ("whole_count","exec_count","calibrate"):
        assert sha(kit/(name+".c"))==enroll["counter_sources"][name]
        sp.run(["cc","-O2","-Wall","-Wextra","-o",work/name,kit/(name+".c")],check=True)
    readings={}
    for mode in ("single","fork"):
        file=proof/("calibration-"+mode+".json")
        sp.run([work/"whole_count",file,work/"calibrate",mode],check=True)
        readings[mode]=hardware(file)
    assert 1.99<readings["fork"]/readings["single"]<2.01,readings

def hardware(path):
    r=json.loads(path.read_bytes())
    assert r["instructions"]>0 and r["enabled"]==r["running"]>0 and r["status"]==0,r
    return r["instructions"]

def set_binary(arm):
    current=sdk/"bin/cargo"
    new_file=current.with_name("next-cargo")
    shutil.copy2(pair/arm/"cargo",new_file)
    os.replace(new_file,current)
    assert sha(current)==enroll["cargo"][arm]
    version=sp.check_output(["cargo","+ohm","-vV"],cwd=source,env=standard(),text=True)
    assert reg[arm] in version

def observe_tasks(td):
    def ident(p):
        s=p.stat()
        return (s.st_dev,s.st_ino)
    binaries={ident(sdk/"bin/rustc"):"rustc",ident(sdk/"bin/cargo"):"cargo",
              ident(sdk/"lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"):"Wild"}
    rows={}
    counts=defaultdict(lambda:[0,0,0])
    for line in (td/"epochs.tsv").read_text().splitlines():
        f=line.split()
        if f[0]=="C":
            epoch,tg,tid,i,en,run=map(int,f[1:])
            assert min(i,en,run)>=0 and en>=run
            for idx,n in enumerate((i,en,run)):counts[epoch][idx]+=n
        if f[0]!="I":continue
        _,idx,tg,tid,when,why=f
        idx=int(idx)
        record=td/f"{idx:05}.nul"
        args=record.read_bytes().split(bytes([0]))
        assert args[-1]==b"" and int(args[0])==int(tg)
        tool=binaries.get(tuple(map(int,args[1:3])))
        if why!="exec" or tool is None:continue
        argv=list(map(os.fsdecode,args[4:-1]))
        crate=argv[argv.index("--crate-name")+1] if "--crate-name" in argv else None
        link_only=any(a in ("-Zlink-only","-Zlink-only=yes") or i>0 and argv[i-1]=="-Z" and a in ("link-only","link-only=yes") for i,a in enumerate(argv))
        rows[idx]={"tool":tool,"crate":crate,"link_only":link_only,"argv_sha256":sha(record),"thread_group":int(tg)}
    for key,r in rows.items():
        r["epoch_count"]=counts[key]
    return list(rows.values())

def visit(arm,label,command,commit,kind="whole",expect_error=False):
    out=proof/arm/label
    out.mkdir(parents=True)
    assert git("rev-parse","HEAD")==commit
    e=standard()
    argv=[shutil.which("cargo",path=e["PATH"]),*command[1:]]
    if kind=="whole": measured=[work/"whole_count",out/"hardware.json",*argv]
    elif kind=="observe":
        tasks=out/"tasks"
        tasks.mkdir()
        measured=[work/"exec_count",tasks,*argv]
    else:measured=argv
    started=time.monotonic_ns()
    with (out/"stdout.jsonl").open("xb") as o,(out/"stderr").open("xb") as err:
        p=sp.run(measured,cwd=source,env=e,stdout=o,stderr=err)
    elapsed=time.monotonic_ns()-started
    messages=[json.loads(l) for l in (out/"stdout.jsonl").read_bytes().splitlines() if l.startswith(b"{")]
    errors=[m["message"] for m in messages if m["reason"]=="compiler-message" and m["message"]["level"]=="error"]
    if expect_error:
        assert p.returncode and messages[-1]=={"reason":"build-finished","success":False}
        assert any((m.get("code") or {}).get("code")=="E0308" and any(s["is_primary"] and
           s["file_name"].endswith("/insta-1.48.0/src/settings.rs") for s in m["spans"]) for m in errors)
        write(out/"verdict.json",{"exit":p.returncode,"codes":[(m.get("code") or {}).get("code") for m in errors]})
        return
    assert p.returncode==0 and not errors and messages[-1]=={"reason":"build-finished","success":True}
    result={"argv":command,"head":commit,"elapsed_ns_descriptive":elapsed}
    arts=[x for x in messages if x["reason"]=="compiler-artifact"]
    result["total_units"]=len(arts)
    result["scheduled"]=[x["target"]["name"] for x in arts if not x["fresh"]]
    if kind=="whole":result["instructions"]=hardware(out/"hardware.json")
    if kind=="observe":result["processes"]=observe_tasks(tasks)
    if "test" in command:
        selected=[Path(x["executable"]) for x in arts if x["target"]["name"]=="ty_project" and x["profile"]["test"] and x.get("executable")]
        assert len(selected)==1
        exe=selected[0]
        listing=sp.check_output([exe,"--list"],cwd=source,env=e)
        (out/"native.list").write_bytes(listing)
        names=[x[:-6] for x in listing.decode().splitlines() if x.endswith(": test")]
        added="db::tests::unrelated_file_change_does_not_advance_revision"
        assert (added in names)==(commit==new) and len(names)==(78 if commit==new else 77)
        result["native_sha256"]=sha(exe)
        result["native_list_sha256"]=hashlib.sha256(listing).hexdigest()
        result["native_bytes"]=exe.stat().st_size
        if commit==new:
            native=sp.check_output([exe,"--exact",added],cwd=source,env=e)
            assert b"1 passed" in native
            (out/"native.result").write_bytes(native)
        retained=work/"native"/arm/result["native_sha256"]
        if not retained.exists():retained.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(exe,retained)
        assert sha(retained)==result["native_sha256"]
    write(out/"verdict.json",result)
    print(arm,label,result.get("instructions"),result["total_units"],result.get("native_sha256"),flush=True)
    return result

def retire(arm,label):
    unused=work/"retired"/arm/label
    unused.mkdir(parents=True)
    for d in (target,shared):
        if d.exists():d.rename(unused/d.name)

def history(arm):
    assert not target.exists() and not shared.exists() and not home.exists()
    shutil.copytree(work/"enrolled-cargo-home",home,symlinks=True)
    set_binary(arm)
    assert not git("status","--porcelain")
    git("checkout","--quiet","--detach",old)
    cold=visit(arm,"old",prefix,old)
    old_warm=visit(arm,"old-repeat",prefix,old)
    git("checkout","--quiet","--detach",new)
    edit=visit(arm,"edit",prefix,new)
    warm=visit(arm,"first-unchanged",prefix,new)
    later=visit(arm,"second-unchanged",prefix,new)
    traced=visit(arm,"third-unchanged-observed",prefix,new,"observe")
    positives=[r for r in traced["processes"] if r["tool"]=="rustc" and r["crate"] and not r["link_only"]]
    actual=Counter(r["crate"] for r in positives)
    assert actual["ron"]==1 and actual["insta"]==(arm=="parent"),actual
    expected_same=[edit,warm,later,traced]
    check={}
    for sub in ("check","build"):
        cmd=["cargo","+ohm",sub,"-p","ty_project","--lib","--locked","--offline","-j4","--message-format=json"]
        transition=visit(arm,sub+"-after-test",cmd,new)
        first=visit(arm,sub+"-unchanged",cmd,new)
        second=visit(arm,sub+"-second-unchanged",cmd,new)
        check[sub]=[transition["instructions"],first["instructions"],second["instructions"]]
    source_file,=list((home/"registry/src").glob("*/insta-1.48.0/src/settings.rs"))
    original=source_file.read_bytes()
    st=source_file.stat()
    anchor=b'snapshot_path: "snapshots".into(),'
    bad=b'snapshot_path: false'+b' '*(len(anchor)-len(b'snapshot_path: false,'))+b','
    assert len(anchor)==len(bad) and original.count(anchor)==1
    def mutate(raw):
        source_file.chmod(stat.S_IMODE(st.st_mode)|stat.S_IWUSR)
        source_file.write_bytes(raw)
        os.utime(source_file,ns=(st.st_atime_ns,st.st_mtime_ns))
        source_file.chmod(stat.S_IMODE(st.st_mode))
        cur=source_file.stat()
        assert (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)==(cur.st_dev,cur.st_ino,cur.st_size,cur.st_mtime_ns)
    try:
        mutate(original.replace(anchor,bad))
        for name in ("invalid","invalid-again"):visit(arm,name,prefix,new,"ordinary",True)
    finally:mutate(original)
    repaired=visit(arm,"repaired",prefix,new,"ordinary")
    expected_same.append(repaired)
    markers={n:[p.stat().st_size for p in target.rglob("dep-lib-"+n)] for n in ("ron","insta","insta_cmd")}
    all_markers=[p for p in target.rglob("dep-*") if p.is_file() and p.parent.name=="fingerprint"]
    footprint={"registry":markers,"translated_files":len(all_markers),"translated_bytes":sum(p.stat().st_size for p in all_markers)}
    retire(arm,"history")
    clean=visit(arm,"empty-new",prefix,new)
    expected_same.append(clean)
    retire(arm,"empty")
    home.rename(work/("used-cargo-home-"+arm))
    variants={r["native_sha256"] for r in expected_same}
    if len(variants)>1:
        mismatch=proof/arm/"whole-elf-differences"
        mismatch.mkdir()
        for digest in variants:shutil.copyfile(work/"native"/arm/digest,mismatch/digest)
    return {"cold":cold["instructions"],"old_repeat":old_warm["instructions"],"edit":edit["instructions"],
            "primary_first_unchanged":warm["instructions"],"second_unchanged":later["instructions"],"control":check,
            "footprint":footprint,"full_rustcs":dict(actual),"elf_matches":len(variants)==1,
            "all_native_sha256":[r["native_sha256"] for r in expected_same],"test_list_matches":all(r["native_list_sha256"]==clean["native_list_sha256"] for r in expected_same)}

if __name__=="__main__":
    install()
    result={}
    for side in enroll["orders"][role]:
        result[side]=history(side)
        write(proof/"result.json",result)
    assert all(r["test_list_matches"] for r in result.values())
