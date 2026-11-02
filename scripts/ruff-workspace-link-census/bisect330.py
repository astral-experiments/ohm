"""Exercise Cargo #330 and its direct parent with the same signed -22 Rust and stock Wild."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parent))
import census

H = census.HERE
W, E, SDK = census.paths()
SOURCE = {
    "parent": ("2554a1dfaf22474b360a4298883acf41f82bd78f","39884e04e748b26929601ff217139e8a77f296f7409d52a4303e7aadf0fe8ff7",50946880),
    "child": ("8269d772aa1ef02e5efaa331dfb40eb55d71f719","3e6948caba617c5f776641df2ade87fe772d0b656a53b538cd93b63351c56c53",50954160),
}
ARTIFACT = {
    "parent": (41212542603,"7bc72b798b019a9ec0de6eeea3bc22b783917b27",13046543047,274460316,"32a14901e46302ebeebdc3badc5be40284dbfc5c36f8ee176071b3ddd623d6c1"),
    "child": (41223789368,"1a749d7784498cd5a883d69474813f3ca46f176e",13050858750,21820825,"f54d8da43340a9317ce26a8cbd2279b68702fa33bf406929caca5660258cf600"),
}
CONSTRUCTORS = ["cargo","+ohm","test","-p","ruff_text_size","--test","constructors","--features",
                "get-size,schemars,serde","--no-run","--locked","--offline","-j8","--message-format=json"]
FIXTURE = ["cargo","+ohm","build","--locked","--offline","-j8","--message-format=json"]


def fetch():
    census.install()
    for role,(run,head,aid,size,digest) in ARTIFACT.items():
        url = "repos/astral-experiments/ohm/actions"
        def api(p):
            return json.loads(subprocess.check_output(["gh","api",url+p]))
        a, r = api("/artifacts/"+str(aid)), api("/runs/"+str(run))
        assert (a["id"],a["size_in_bytes"],a["digest"],a["expired"],a["workflow_run"]["id"],a["workflow_run"]["head_sha"]) == (aid,size,"sha256:"+digest,False,run,head)
        job_id,job_name,conclusion,steps = (
            (124570376741,"Native SDK (x86_64-unknown-linux-gnu)","failure",["Reopen every completed SDK member","Publish reusable native SDK"]) if role=="parent" else
            (124603612571,"Cargo 330 native qualification (x86_64-unknown-linux-gnu)","success",["Build the exact Cargo 330 revision","Retain the exact binary, comparison logs and partial results"]))
        job=api("/jobs/"+str(job_id))
        assert r["head_sha"] == head and r["status"]=="completed" and r["conclusion"]==conclusion and r["run_attempt"] == 1
        assert job["name"]==job_name and job["run_id"]==run and job["head_sha"]==head and job["conclusion"]=="success"
        actual={s["name"]:s["conclusion"] for s in job["steps"]}
        assert all(actual.get(k)=="success" for k in steps)
        census.put(E/(role+"-constructor.json"),{"run":run,"run_conclusion":conclusion,"job":job_id,"outcomes":actual})
        pack = W/(role+".zip")
        with pack.open("xb") as f:
            subprocess.run(["gh","api",url+"/artifacts/"+str(aid)+"/zip"],stdout=f,check=True)
        assert pack.stat().st_size == size and census.sha(pack) == digest
        with zipfile.ZipFile(pack) as z:
            if role == "parent":
                assert set(z.namelist()) == {"members.json","receipt.json","kit.tar.zst"}
                for n,expected in [("members.json","99cfc5bf1d484672b1f50002858696b52914b1e5ef93d17b1cfe94c8b05cf928"),("receipt.json","df39d99e13159b2ca341b79b8fc0f525731e69c911eb8e7dba2de8630fc5214c")]:
                    b=z.read(n)
                    assert hashlib.sha256(b).hexdigest() == expected
                    (E/("parent-"+n)).write_bytes(b)
                member = json.loads(z.read("members.json"))["sdk/bin/cargo"]
                assert (member["sha256"],member["bytes"],member["mode"]) == (SOURCE[role][1],SOURCE[role][2],0o755)
                compressed = W/"earlier-kit.tar.zst"
                with z.open("kit.tar.zst") as src, compressed.open("xb") as out:
                    shutil.copyfileobj(src,out,1<<20)
                assert census.sha(compressed) == "a282efe9e45b297797ed4ac94ca2987315610e53af7e45d6d8493c3282b5c966"
                with (W/"cargo-parent").open("xb") as out:
                    subprocess.run(["tar","--zstd","-xOf",compressed,"sdk/bin/cargo"],stdout=out,check=True)
            else:
                proof = json.loads(z.read("rc22-cargo330/reports/candidate330.json"))
                assert (proof["commit"],proof["parent"],proof["sha256"]) == (SOURCE[role][0],SOURCE["parent"][0],SOURCE[role][1])
                assert "ohm-defaults" in proof["features"]
                census.put(E/"child-cargo-source.json",proof)
                with z.open("rc22-cargo330/cargo") as src,(W/"cargo-child").open("xb") as out:
                    shutil.copyfileobj(src,out,1<<20)
        binfile=W/("cargo-"+role)
        assert binfile.stat().st_size == SOURCE[role][2] and census.sha(binfile) == SOURCE[role][1]
        binfile.chmod(0o755)
        census.put(E/(role+"-artifact.json"),{"run":run,"source":head,"artifact":aid,"sha256":digest,"bytes":size,"cargo":SOURCE[role]})


def visit(folder, argv, cwd, env, target):
    folder.mkdir()
    traced=["strace","-ff","-qq","-v","-s","1048576","-e","trace=%process","-o",str(folder/"exec"),"--",*argv]
    with (folder/"stdout.jsonl").open("xb") as out,(folder/"stderr").open("xb") as err:
        ret=subprocess.run(traced,cwd=cwd,env=env,stdout=out,stderr=err,timeout=900)
    census.put(folder/"command.json",{"argv":argv,"exit":ret.returncode,"cwd":str(cwd)})
    assert ret.returncode in (0,101)
    rows=[json.loads(x) for x in (folder/"stdout.jsonl").read_bytes().splitlines()]
    artifacts=[r for r in rows if r["reason"]=="compiler-artifact"]
    assert rows[-1]=={"reason":"build-finished","success":ret.returncode==0}
    out={"exit":ret.returncode,"typed":len(artifacts),"dirty":[r["target"]["name"] for r in artifacts if not r["fresh"]]}
    if ret.returncode==0:
        a,=[r for r in artifacts if r["target"]["name"]==target]
        exe=Path(a["executable"])
        assert exe.read_bytes()[:4]==b"\x7fELF" and exe.resolve().is_relative_to(W)
        extra=["--exact","main","--nocapture"] if target=="constructors" else []
        run=subprocess.run([exe,*extra],cwd=cwd,env=env,capture_output=True,timeout=30,check=True)
        (folder/"native.stdout").write_bytes(run.stdout)
        (folder/"native.stderr").write_bytes(run.stderr)
        out.update(elf=census.sha(exe),native=run.stdout.decode(),features=a["features"])
        if target=="constructors":
            assert b"test main ... ok" in run.stdout and b"1 passed" in run.stdout
            assert set(a["features"])=={"get-size","schemars","serde"}
    gen=census.genealogy(folder)
    out["rustc"]=[(p["owner"],p["link_only"]) for p in gen["processes"] if p["owner"]]
    out["wild"]=len(gen["linkers"])
    census.put(folder/"native-processes.json",gen)
    census.put(folder/"result.json",out)
    print(folder.name,out["exit"],out["typed"],len(out["rustc"]),out["wild"],flush=True)
    return out


def archive(path, val):
    path.parent.mkdir(exist_ok=True)
    src=path.parent/"provider.c"
    src.write_text(f"int qa_rc22_value(void) {{ return {val}; }}\n")
    obj=path.parent/"provider.o"
    subprocess.run(["/usr/bin/cc","-c",src,"-o",obj],check=True)
    temp=path.with_suffix(".new")
    subprocess.run(["/usr/bin/ar","crsD",temp,obj],check=True)
    os.replace(temp,path)


def provider(label,folder,env):
    base=W/"provider-case";base.mkdir()
    project=base/"fixture";(project/"src").mkdir(parents=True)
    (project/"Cargo.toml").write_text('[package]\nname="probe"\nversion="0.1.0"\nedition="2024"\n[dependencies]\nzmij="=1.0.10"\n')
    (project/"Cargo.lock").write_text('version = 4\n[[package]]\nname="probe"\nversion="0.1.0"\ndependencies=["zmij"]\n[[package]]\nname="zmij"\nversion="1.0.10"\nsource="registry+https://github.com/rust-lang/crates.io-index"\nchecksum="30e0d8dffbae3d840f64bda38e28391faef673a7b5a6017840f2a106c8145868"\n')
    (project/"build.rs").write_text('fn main() { let root=std::path::Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap(); for d in ["early","late"] {println!("cargo:rustc-link-search=native={}",root.join(d).display());} println!("cargo:rerun-if-changed=build.rs"); }\n')
    (project/"src/main.rs").write_text('#[link(name="qa_rc22",kind="static",modifiers="-bundle")]\nunsafe extern "C" { fn qa_rc22_value()->i32; }\nfn main(){assert_eq!(zmij::Buffer::new().format(1.25_f64),"1.25");println!("{}",unsafe{qa_rc22_value()});}\n')
    early,late=(base/x/"libqa_rc22.a" for x in ("early","late"))
    early.parent.mkdir();archive(late,17)
    local=dict(env,CARGO_TARGET_DIR=str(base/"target"),CARGO_BUILD_BUILD_DIR=str(base/"build"))
    outcomes={}
    for name,expected in [("train",17),("repeat",17),("shadow",29),("malformed",None),("repair",41),("remove-early",17),("missing",None)]:
        if name=="shadow":archive(early,29)
        if name=="malformed":
            raw=early.read_bytes();s=early.stat();early.write_bytes(b"!bad"+bytes(len(raw)-4));os.utime(early,ns=(s.st_atime_ns,s.st_mtime_ns))
        if name=="repair":archive(early,41)
        if name=="remove-early":early.unlink()
        if name=="missing":late.unlink()
        observed=visit(folder/("provider-"+name),FIXTURE,project,local,"probe")
        if name in ("shadow","malformed","repair","remove-early","missing"):
            # Move the real warm state aside, preserving exact logical paths for the independent empty.
            for out in ("target","build"):
                if (base/out).exists():os.rename(base/out,base/(name+"-parked-"+out))
            clean=visit(folder/("provider-"+name+"-empty"),FIXTURE,project,local,"probe")
            for out in ("target","build"):
                if (base/out).exists():os.rename(base/out,base/(name+"-empty-"+out))
                parked=base/(name+"-parked-"+out)
                if parked.exists():os.rename(parked,base/out)
            assert (clean["exit"],clean.get("native")) == ((101,None) if expected is None else (0,f"{expected}\n"))
        else:clean=observed
        val=(observed["exit"],observed.get("native"))
        outcomes[name]={"warm":val,"empty":(clean["exit"],clean.get("native")),"warm_elf":observed.get("elf"),"empty_elf":clean.get("elf")}
    shutil.copytree(project,folder/"provider-source")
    census.put(folder/"provider-comparison.json",outcomes)
    os.rename(base,W/("provider-"+label))


def run(ruff):
    assert census.git(ruff,"rev-parse","HEAD")==census.RUFF and census.sha(ruff/"Cargo.lock")==census.LOCK
    assert not (W/"home").exists() and shutil.disk_usage(W).free>=40*1024**3
    assert not any(k in os.environ for k in ("GITHUB_TOKEN","GH_TOKEN","RUSTFLAGS","RUSTC_WRAPPER","LD_PRELOAD"))
    env=census.environment(W,SDK)
    kit=json.loads((E/"identity.json").read_bytes())["sdk"]
    assert census.acquire.verify_sdk(SDK)==kit
    os.rename(SDK/"bin/cargo",W/"cargo-signed22")
    expected={x["name"]+"-"+x["version"]+".crate":x["checksum"] for x in tomllib.loads((ruff/"Cargo.lock").read_text())["package"] if "source" in x}
    assert len(expected)==498
    rc=[]
    for role in SOURCE:
        f=E/role;f.mkdir();(W/"home").mkdir()
        os.link(W/("cargo-"+role),SDK/"bin/cargo")
        assert census.sha(SDK/"bin/cargo")==SOURCE[role][1]
        vv=subprocess.check_output(["cargo","+ohm","-vV"],env=env,text=True)
        assert SOURCE[role][0] in vv
        (f/"cargo.version").write_text(vv)
        for k,v in kit.items():
            if k!="bin/cargo":
                s=(SDK/k).stat()
                assert [census.sha(SDK/k),s.st_dev,s.st_ino,s.st_mode&0o7777,s.st_size,s.st_mtime_ns,s.st_ctime_ns]==v
        with (f/"fetch.log").open("xb") as log:
            subprocess.run(["cargo","+ohm","fetch","--locked"],env=env,cwd=ruff,stdout=log,stderr=log,check=True)
        got={p.name:census.sha(p) for p in (W/"cargo/registry/cache").glob("*/*.crate")}
        assert got==expected
        census.put(f/"registry.json",got)
        phases={}
        for phase in ("cold","repeat1","repeat2"):
            diagnostic=dict(env,CARGO_LOG="cargo::compiler::fingerprint=trace") if phase=="repeat2" else env
            phases[phase]=visit(f/phase,CONSTRUCTORS,ruff,diagnostic,"constructors")
        assert all(r["native"].split("test main ... ok")[0]==phases["cold"]["native"].split("test main ... ok")[0] for r in phases.values())
        assert phases["repeat1"]["dirty"]==phases["repeat2"]["dirty"]
        inventory={}
        for p in (W/"target").rglob("*.d"):
            b=p.read_bytes()
            mark=sorted(k for k in ("ohm-recheck-dependent-links","ohm-foreign-span-bytes","ohm-untracked-relink-inputs") if k.encode() in b)
            if mark:inventory[str(p.relative_to(W))]={"sha256":hashlib.sha256(b).hexdigest(),"markers":mark}
        census.put(f/"marked-deps.json",inventory)
        provider(role,f,env)
        rc.append([role,{k:[r["typed"],len(r["dirty"]),r["rustc"],r["wild"],r["elf"]] for k,r in phases.items()}])
        (SDK/"bin/cargo").unlink()
        for n in ("home","cargo","target","build"):
            if (W/n).exists():os.rename(W/n,W/(role+"-"+n))
    os.rename(W/"cargo-signed22",SDK/"bin/cargo")
    # Restoring the name can update that inode's ctime; the complete original member content is reverified.
    again=census.acquire.verify_sdk(SDK)
    assert all(again[k][:6]==kit[k][:6] for k in kit)
    assert not census.git(ruff,"status","--porcelain=v1")
    census.put(E/"bisect-complete.json",{"roles":rc,"source":census.RUFF,"lock":census.LOCK})
    print("source pair, original signed driver, native witness and independent empty controls captured",flush=True)

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase",choices=("fetch","run"))
    parser.add_argument("source",type=Path,nargs="?")
    args=parser.parse_args()
    if args.phase=="fetch":fetch()
    else:run(args.source.resolve(strict=True))
