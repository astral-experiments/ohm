"""Admit two same-run native-qualified production SDKs; only this hosted step needs Actions read."""
import os, re, shutil, subprocess, sys, tarfile
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parent))
import material as m, capacity

REPO=m.P["coordinator_repo"];BRANCH="charlie/codex-ctfe22-standard-20988";WF=".github/workflows/ci.yml"
TARGET="x86_64-unknown-linux-gnu"
PREFIX={"stock_ctfe318":"STOCK","fa7a_stack_ctfe318":"TRAITS"}
REQUIRED={"ohm.tar.gz","SHA256SUMS","source.json","role.json","sdk-inventory.json","component-inventory.json"}
def lock(run,jobs,artifacts):
    ident=run["id"];head=run["head_sha"]
    m.guard((ident,head)==(capacity.RID,capacity.HEAD),"unregistered capacity-successor build run/head")
    m.guard(type(ident) is int and ident>0 and re.fullmatch("[a-f0-9]{40}",head) and
            run["repository"]["full_name"]==REPO and run["repository"]["private"] is True and run["head_repository"]["full_name"]==REPO and
            run["head_branch"]==BRANCH and run["path"]==WF and run["event"]=="workflow_dispatch" and run["run_attempt"]==1 and
            run["status"]=="completed" and run["conclusion"]=="success","unqualified build-run origin")
    jr=jobs["jobs"];m.guard(len(jr)==jobs["total_count"]==3,"missing/extra build job")
    expect={f"Production GNU SDK ({r})" for r in PREFIX}|{"Qualify both cache migration directions"}
    m.guard({j["name"] for j in jr}==expect and all(j["status"]=="completed" and j["conclusion"]=="success" and
            j["run_id"]==ident and j["run_attempt"]==1 and j["head_sha"]==head for j in jr),"wrong/missing/unsuccessful producer")
    capacity.jobs(jr)
    ar=artifacts["artifacts"];names=set(m.P["sdk_artifacts"])
    m.guard(len(ar)==artifacts["total_count"]==len(names) and {a["name"] for a in ar}==names,"unrecognized artifact set")
    members={}
    for a in ar:
        m.guard(not a["expired"] and a["workflow_run"]["id"]==ident and a["workflow_run"]["head_sha"]==head and
                a["workflow_run"]["head_branch"]==BRANCH and type(a["id"]) is int and a["id"]>0 and
                re.fullmatch("sha256:[a-f0-9]{64}",a["digest"]) and type(a["size_in_bytes"]) is int and 0<a["size_in_bytes"]<800<<20,"expired/forged Actions artifact")
        members[a["name"]]={"id":a["id"],"sha256":a["digest"][7:],"bytes":a["size_in_bytes"]}
    m.guard(len({v["id"] for v in members.values()})==len(names) and len({v["sha256"] for v in members.values()})==len(names),"duplicated artifact identity")
    return {"format":1,"repository":REPO,"build_run":ident,"head":head,"branch":BRANCH,"workflow":WF,"attempt":1,
            "jobs":{j["name"]:j["id"] for j in jr},"artifacts":members}
def unpack(source,dest,kind):
    dest.mkdir()
    with ZipFile(source) as z:
        files=[i for i in z.infolist() if not i.is_dir()];names=[i.filename for i in files]
        m.guard(len(names)==len(set(names)) and len(names)<=100 and sum(i.file_size for i in files)<800<<20,"bad total ZIP inventory")
        if kind=="sdk":m.guard(set(names)==REQUIRED,"SDK ZIP members")
        for i in files:
            parts=PurePosixPath(i.filename)
            m.guard(not parts.is_absolute() and ".." not in parts.parts and parts.as_posix()==i.filename and "\\" not in i.filename and
                    (i.external_attr>>16)&0o170000 in (0,0o100000) and not (i.flag_bits&1) and
                    (i.file_size<=700<<20 if i.filename=="ohm.tar.gz" else i.file_size<=100<<20),"unsafe or oversized artifact member")
            p=dest/parts;p.parent.mkdir(parents=True,exist_ok=True)
            with z.open(i) as a,p.open("xb") as b:shutil.copyfileobj(a,b,1<<20)
            m.guard(p.stat().st_size==i.file_size,"truncated member")
def runtime_files(role,installed,inventory,rv):
    runtime={rv[k]["path"]:rv[k]["sha256"] for k in ("launcher","driver","llvm")}
    inventory=m.read(inventory)
    for key in ("launcher","driver","llvm","bundled_cargo"):
        rel=rv[key]["path"];row=inventory[rel];m.guard(rel==PurePosixPath(rel).as_posix() and ".." not in Path(rel).parts and
            row["sha256"]==rv[key]["sha256"] and m.filesha(installed/rel)==row["sha256"],("component binding",role,key))
    m.guard(rv["launcher"]["path"]=="bin/rustc" and rv["bundled_cargo"]["path"]=="bin/cargo" and rv["bolt_note"] is True and
            rv["source_commit"]==m.P["roles"][role]["commit"] and rv["source_tree"]==m.P["roles"][role]["tree"] and
            rv["epoch"]==m.P["roles"][role]["epoch"] and rv["effective_benchmark_cargo_sha256"]==m.P["signed_cargo_sha256"],"compiler role mismatch")
    return runtime
def official_cargo(archive,out):
    name="rust-1.99.0-dev-"+TARGET+"/cargo/bin/cargo";path=out/"signed-cargo"
    with tarfile.open(archive,"r|gz") as t:
        for item in t:
            if item.name!=name:continue
            m.guard(item.isfile() and 0<item.size<100<<20 and item.mode&0o111 and not path.exists(),"expected one regular signed native Cargo")
            with t.extractfile(item) as a,path.open("xb") as b:shutil.copyfileobj(a,b,1<<20)
            m.guard(path.stat().st_size==item.size,"truncated Cargo")
    m.guard(m.filesha(path)==m.P["signed_cargo_sha256"],"signed Cargo checksum");path.chmod(0o755);return path
def main():
    if len(sys.argv)==5 and sys.argv[1]=="lock":
        v=lock(*(m.read(Path(x)) for x in sys.argv[2:]));sys.stdout.buffer.write(m.canon(v)+b"\n");return
    w,tmp=m.host();m.guard(sys.argv[1:]==["admit"],"usage: enroll.py lock RUN JOBS ARTIFACTS | admit")
    head=os.environ["BUILD_HEAD"];rid=os.environ["BUILD_RUN_ID"];pin=os.environ["SDK_LOCK_SHA256"]
    m.guard(re.fullmatch("[a-f0-9]{40}",head) and re.fullmatch("[1-9][0-9]*",rid) and re.fullmatch("[a-f0-9]{64}",pin),"immutable post-build SDK lock required")
    out=w/"trait-results";out.mkdir(exist_ok=True);proof=out/"intake";proof.mkdir();temp=tmp/"ctfe22-root-media";temp.mkdir()
    _,previous=m.check_sources(w);old=m.load("signed_release_intake",previous/"intake.py");root=f"repos/{REPO}/actions/runs/{rid}"
    meta=[old.gh_json("api",ep) for ep in (root,root+"/attempts/1/jobs?per_page=100",root+"/artifacts?per_page=100")]
    for n,v in zip(("run","jobs","artifacts"),meta,strict=True):m.save(proof/(n+".json"),v)
    pinned=lock(*meta);m.guard(pinned["head"]==head and pinned["build_run"]==int(rid) and m.digest(m.canon(pinned)+b"\n")==pin,"unreviewed SDK receipts or new run")
    m.save(proof/"sdk-lock.json",pinned)
    builder=w/"builder";contract=m.read(m.HERE/"builder-files.json")
    m.guard(m.sha_git(builder,"rev-parse","HEAD").decode().strip()==head and not m.sha_git(builder,"status","--porcelain","--untracked-files=no"),"builder checkout")
    for rel,sha in contract.items():m.guard(m.filesha(builder/rel)==sha,("unrecognized builder source",rel))
    mod=m.load("production_qualified_pair",builder/"scripts/ctfe22-gnu/pair.py")
    m.guard(mod.native.S["signed_cargo_binary_sha256"]==m.P["signed_cargo_sha256"] and all(
        mod.native.S["arms"][r][k]==v for r,rr in m.P["roles"].items() for k,v in rr.items()),"source/toolchain contract")
    context={"evidence_repository":REPO,"reviewed_head":head,"workflow_ref":f"{REPO}/{WF}@refs/heads/{BRANCH}","run_id":int(rid),"run_attempt":1}
    unpacked={};meta_folder=proof/"role-material";meta_folder.mkdir()
    for name,art in pinned["artifacts"].items():
        source=temp/(name+".zip");old.gh_bytes(f"repos/{REPO}/actions/artifacts/{art['id']}/zip",source,art["bytes"],art["sha256"])
        dest=temp/name;kind="sdk" if name.startswith("ctfe22-gnu-sdk-") else "qa";unpack(source,dest,kind);unpacked[name]=dest
    pair_dir=unpacked["ctfe22-gnu-pair-qa-attempt-1"];pair=m.read(pair_dir/"passed.json");transition=pair_dir/"cache-transition/passed.json"
    m.guard(pair["github"]==context and pair["required_benchmark_cargo_sha256"]==m.P["signed_cargo_sha256"] and
            m.filesha(transition)==pair["cross_sdk_cache_rejection_sha256"] and m.read(transition)["native_processes"]==16 and
            set(m.read(transition)["modes"])=={"ordinary","shared-rustc-perf-version"},"incoming migration/correction QA")
    for d in m.read(transition)["modes"].values():
        m.guard(set(d)=={"stock_ctfe318-to-fa7a_stack_ctfe318","fa7a_stack_ctfe318-to-stock_ctfe318"} and all(len(rs)==4 for rs in d.values()),"incomplete cross-epoch check")
    shutil.copyfile(pair_dir/"passed.json",proof/"pair-passed.json");shutil.copyfile(transition,proof/"cache-transition.json")
    old.released(temp,proof);archive,=(temp/"signed").glob("*.tar.gz")
    signed_cargo=official_cargo(archive,temp)
    m.guard(m.filesha(signed_cargo)==m.P["signed_cargo_sha256"] and "commit-hash: "+m.P["signed_cargo_commit"]+"\n" in
            subprocess.check_output([signed_cargo,"-Vv"],text=True),"incorrect signed release Cargo")
    result={};pool=tmp/"ctfe22-root-sdks";pool.mkdir()
    for role in PREFIX:
        sdk="ctfe22-gnu-sdk-"+role;qa=f"ctfe22-gnu-build-{role}-attempt-1"
        for k,name in (("sdk",sdk),("qa",qa)):
            service=pinned["artifacts"][name];m.guard(pair["artifacts"][role][k]=={"id":service["id"],"sha256":service["sha256"]},"builder pair QA did not see exact artifact")
        work=temp/("unpack-"+role);work.mkdir();rv,src,actual=mod.validate(role,unpacked[sdk],unpacked[qa],work,context)
        m.guard(pair["roles"][role]=={"role":rv,"source":src},"unqualified variant")
        runtime=runtime_files(role,actual,work/"sdk-inventory.json",rv)
        evidence=meta_folder/role;evidence.mkdir()
        for f in ("SHA256SUMS","source.json","role.json","sdk-inventory.json","component-inventory.json"):shutil.copyfile(unpacked[sdk]/f,evidence/f)
        (actual/"bin/cargo").unlink();shutil.copy2(signed_cargo,actual/"bin/cargo");runtime["bin/cargo"]=m.filesha(actual/"bin/cargo")
        m.guard(runtime["bin/cargo"]==m.P["signed_cargo_sha256"],"missing signed Cargo overlay")
        subprocess.run([actual/"bin/rustc","-Vv"],env={"PATH":"/usr/bin:/bin"},stdout=(evidence/"rustc-vV.txt").open("xb"),check=True)
        m.guard(rv["source_commit"] in (evidence/"rustc-vV.txt").read_text(),"compiler commit/version")
        for tool in ("rustc","rustdoc","cargo"):m.guard((actual/"bin"/tool).is_file(),("missing SDK tool",tool))
        actual.rename(pool/role)
        result[role]={"runtime":runtime,"production_archive":rv["archive_sha256"],"source":m.P["roles"][role],
                      "original_bundled_cargo":rv["bundled_cargo"]["sha256"],"unmodified_component_inventory":m.filesha(work/"sdk-inventory.json")}
    m.guard(len({v["production_archive"] for v in result.values()})==2,"duplicated SDK")
    capacity.capture(proof,builder,unpacked)
    m.save(out/"intake.json",{"installed":result,"sdk_lock_sha256":pin,"signed_cargo_sha256":m.P["signed_cargo_sha256"],"build_head":head,"build_run":int(rid)})
if __name__=="__main__":main()
