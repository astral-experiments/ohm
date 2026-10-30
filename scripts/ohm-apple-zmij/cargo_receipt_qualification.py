"""Native provider and Ruff verdicts with one physical Rust #276 driver and two Cargo CLIs."""
import argparse
import gzip
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dyld import check as dyld
from execs import ExecTrace
from measure import fresh, retire, select
from prepare import prepare_ruff, role_files
import provider_edges as edge
from receipt_cargo import CANDIDATE
from study import CHILD, CARGO_SOURCE, check_host, env_for, load, need, physical, run, save, sdk_id, sha
import verbs

CARGOS={"S":CARGO_SOURCE, "R":CANDIDATE}
CORE=[(r,p,w,d) for w in ("unwatched","declared") for p in ("direct","library") for d in (True,False) for r in "SR"]
BLOCKED_PREFIX=("DYLD_","LD_","LD64_","CCC_","CLANG_","LLVM_","LTO_","TAPI_","SWIFT_","RC_","QA_OVERRIDE",
                "XCRUN_","_XCRUN_","CC_","COMPILER_RT_","CODESIGN_","TOOLCHAIN_","SDK_","XCODE_")
BLOCKED_NAME={"LIBRARY_PATH","COMPILER_PATH","GCC_EXEC_PREFIX","LPATH","TOOLCHAINS","DEVELOPER_DIR","CPATH",
              "CPLUS_INCLUDE_PATH","OBJC_INCLUDE_PATH","C_INCLUDE_PATH","LD_LIBRARY_PATH"}
INPLACE=(("original-higher","higher",7),("repeat-higher","higher",7),("overwrite-same-stamp","overwrite",7),
         ("repeat-replacement","overwrite",7),("restore-same-stamp","restore",7))
RUFF=(("cold","old"),("edit","new"),("repeat-1","new"),("repeat-2","new"),("invalid","invalid"),("repair","new"))


def bind(root, role):
    sdk=select(root,"C")
    candidate=load(root/"receipts/cargo293/product.json")
    want=root/("signed/bin/cargo" if role=="S" else "cargo-293")
    need(sha(want)==(load(root/"receipts/release.json")["cargo"]["sha256"] if role=="S" else candidate["binary"]["sha256"]),
         "Cargo detached from its producer")
    dst=sdk/"bin/cargo"
    if not dst.samefile(want):
        tmp=dst.with_name("cargo.next")
        os.link(want,tmp);os.replace(tmp,dst)
    need(dst.samefile(want),"Cargo alias is not its enrolled physical inode")
    env=env_for(root/"native-identity",sdk)
    identity=sdk_id(sdk,env,CARGOS[role])
    pair=load(root/"receipts/pair.json")
    driver,=(sdk/"lib").glob("librustc_driver*.dylib")
    need(pair["products"]["C"]["source"]==CHILD and identity["driver"]["sha256"]==
         pair["products"]["C"]["runtime"][str(driver.relative_to(sdk))],"foreign Rust compiler")
    return sdk,identity


def environment(root,clean):
    if not clean:return lambda env:env
    proxy=root/"receipt-host-proxies"
    if not proxy.exists():
        proxy.mkdir()
        rustup=Path(shutil.which("rustup")).resolve(strict=True)
        for name in ("rustup","rustc","cargo","rustdoc"):(proxy/name).symlink_to(rustup)
    def minimal(env):
        wanted={k:v for k,v in env.items() if k in {"HOME","USER","LOGNAME","SHELL","TMPDIR","LC_ALL","TZ","RUSTUP_HOME"}
                or k.startswith("CARGO_")}
        wanted["PATH"]=os.pathsep.join((str(proxy),"/usr/bin","/bin","/usr/sbin","/sbin"))
        need(shutil.which("cc",path=wanted["PATH"])=="/usr/bin/cc", "uncertified default cc")
        return wanted
    return minimal


def machine_env(root, sdk, clean):
    env=environment(root,clean)(env_for(root/"native-identity",sdk))
    blocked=sorted(k for k in env if k!="DYLD_FALLBACK_LIBRARY_PATH" and (k.startswith(BLOCKED_PREFIX) or k in BLOCKED_NAME))
    paths={name:shutil.which(name,path=env["PATH"]) for name in ("cargo","rustc","cc","clang","ld")}
    ancestors={}
    for p in (root.resolve(),*(root.resolve().parents)):
        s=p.lstat();ancestors[str(p)]={"uid":s.st_uid,"mode":oct(s.st_mode&0o7777)}
    return {"host_injected_names_rejected_by_293":blocked,"PATH_tools":paths,"paths":ancestors,
            "developer_dir":run(["xcode-select","-p"],env=env).decode().strip(),
            "ld":run(["xcrun","--find","ld"],env=env).decode().strip()}


def evidence(work,dest,row):
    records={}
    for dirname in ("target","shared"):
        for alias in sorted((work/dirname).rglob("ohm-link-cc")):
            if not alias.is_symlink():continue
            objects=alias.parent
            cache=objects/"native-link"
            files={}
            for name in ("lock","seal","product"):
                f=cache/name
                if f.is_file() and not f.is_symlink():
                    st=f.stat()
                    files[name]={"size":st.st_size,"sha256":sha(f),"inode":st.st_ino}
                    if name=="seal":
                        need(st.st_size<=65568,"oversized seal");files[name]["hex"]=f.read_bytes().hex()
            records[str(alias.relative_to(work))]={"target":os.readlink(alias),"records":files}
    events=json.loads(gzip.decompress((dest/"exec.json.gz").read_bytes()))
    driver=row["native"]["cargo_link_driver"]
    dry=[e["pid"] for e in events if "-###" in e["argv"]]
    rec=[x for x in row["native"]["linkers"] if "-dependency_info" in x["argv"]]
    save(dest/"native-link-receipt.json",{"aliases":records,"driver_processes":driver,"clang_dry_run_pids":dry,
         "ld_dependency_info":len(rec),"full":row["native"]["full"],"link_only":row["native"]["link_only"],
         "stock_links":len(row["native"]["linkers"])})


def same_stamp(src,state,bodies):
    if state=="higher":return edge.configure(src,state,bodies)
    path=src/"early/libqa_owned_external.a"
    want=bodies[17 if state=="overwrite" else 29];old=path.read_bytes();st=path.stat()
    need(len(old)==len(want) and state in {"overwrite","restore"},"unexpected archive size or state")
    if old!=want:
        with path.open("r+b") as f:f.write(want);f.flush();os.fsync(f.fileno())
        os.utime(path, ns=(st.st_atime_ns,st.st_mtime_ns))
    now=path.stat()
    need((st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)==(now.st_dev,now.st_ino,now.st_size,now.st_mtime_ns)
         and path.read_bytes()==want,"unstable in-place witness")
    return {"early":sha(path),"late":sha(src/"late/libqa_owned_external.a"),"modification":old!=want,
            "prior_sha256":edge.digest(old),"device":st.st_dev,"inode":st.st_ino,"size":st.st_size,
            "mtime_ns":st.st_mtime_ns,"before_ctime_ns":st.st_ctime_ns,"after_ctime_ns":now.st_ctime_ns}

def registry_bundle(src, placement, watched):
    need(placement=="registrybundle","wrong placement")
    trigger=edge.form(src,"direct",watched)
    manifest=src/"Cargo.toml"
    manifest.write_text(manifest.read_text().replace("[dependencies]",'[dependencies]\nbarrier="=0.0.1"'))
    (src/"src/main.rs").write_text('fn main(){println!("{} {}",barrier::native(),trigger::value());}\n')
    vendor=src/"vendor";crate=vendor/"barrier-0.0.1";(crate/"src").mkdir(parents=True)
    (crate/"Cargo.toml").write_text('[package]\nname="barrier"\nversion="0.0.1"\nedition="2021"\n')
    (crate/"src/lib.rs").write_text(edge.BARRIER+'#[link(name="qa_owned_external",kind="static")]\n'
        +'unsafe extern "C" { fn qa_value()->i32; }\npub fn native()->i32 { barrier(unsafe {qa_value()}) }\n')
    program=(src/"build.rs").read_text().replace('std::env::var_os("CARGO_MANIFEST_DIR").unwrap()', json.dumps(str(src)))
    if watched:program=program.replace('println!("cargo:rerun-if-changed={name}");',
        'println!("cargo:rerun-if-changed={}", root.join(name).display());')
    (crate/"build.rs").write_text(program)
    save(crate/".cargo-checksum.json", {"files":{str(x.relative_to(crate)):sha(x) for x in crate.rglob("*") if x.is_file()},"package":None})
    (src/".cargo").mkdir()
    (src/".cargo/config.toml").write_text('[source.crates-io]\nreplace-with="fixture"\n[source.fixture]\ndirectory='+json.dumps(str(vendor))+'\n')
    return trigger

def bundled_evidence(work,dest,row):
    evidence(work,dest,row)
    stream=gzip.decompress((dest/"stdout.gz").read_bytes())
    matches=[r for r in map(json.loads,stream.splitlines()) if r["reason"]=="compiler-artifact" and r["target"]["name"]=="barrier"]
    selected=[]
    for m in matches:
        need(m["package_id"].startswith("registry+"),"bundled native library was not a genuine registry package ID")
        p,=[Path(n) for n in m["filenames"] if n.endswith(".rlib")]
        members=run(["/usr/bin/ar","t",str(p)]).decode().splitlines()
        objects={n:edge.digest(run(["/usr/bin/ar","p",str(p),n])) for n in members
                 if n.endswith("provider.o") or n.endswith("libqa_owned_external.a")}
        selected.append({"id":m["package_id"],"rlib":sha(p),"members":members,"providers":objects})
    need(row["status"]!=0 or len(selected)==1,"missing bundled native producer")
    save(dest/"bundled-archive.json",selected)

def bundled(root):
    out=root/"receipts/provider-matrix"
    bodies={v:(out/f"provider-{v}.a").read_bytes() for v in (17,29)}
    trace=ExecTrace();trace.ready()
    try:
        for r in "SR":
            bind(root,r)
            for watch in ("declared","unwatched"):
                edge.run_case(root,trace,"C","registrybundle",watch,True,bodies,label=r+"bundle",
                    evidence=bundled_evidence,fixture=registry_bundle)
    finally:trace.close()
    save(root/"receipts/registry-bundle-terminal.json",{"cases":4,"commands":4*2*len(edge.STEPS)})


def provider(root,part):
    out=root/"receipts/provider-matrix"
    first=part=="first"
    if first:
        out.mkdir()
        for n in ("edge-markers","edge-images"):(root/"receipts"/n).mkdir()
        save(out/"registration.json", {"cargo":CARGOS,"rust":CHILD,"ordinary":CORE,"inplace":INPLACE,"ruff":RUFF,
              "extra":"clean-environment/receipt defaults/direct and library/no-watch, ordinary exposed in both arms",
              "steps":edge.STEPS,"worker":sha(Path(__file__)),"fixture":sha(Path(edge.__file__)),
              "plan":sha(Path(__file__).with_name("cargo293-qualification.md"))})
        data=edge.provider_factory(root,out)
        sdk,_=bind(root,"S")
        dyld(root,"C",sdk,out/"actual-276-driver")
        save(out/"ordinary-host.json",machine_env(root,sdk,False));save(out/"minimal-host.json",machine_env(root,sdk,True))
    else:
        data={v:(out/f"provider-{v}.a").read_bytes() for v in (17,29)}
        for v,body in data.items():need(edge.digest(body)==load(out/"providers.json")[str(v)]["archive"],"archive changed")
    trace=ExecTrace();trace.ready()
    try:
        cases=CORE[:2] if first else CORE[2:]
        for r,p,w,d in cases:
            _,identity=bind(root,r)
            label=f"{r}-{p}-{w}-"+("default" if d else "off")
            edge.run_case(root,trace,"C",p,w,d,data,label=r,evidence=evidence)
            save(out/label/"sdk.json",identity)
            print("closed",label,flush=True)
        if not first:
            for role,place in [(r,p) for r in "SR" for p in ("direct","library")]:
                _,identity=bind(root,role)
                edge.run_case(root,trace,"C",place,"unwatched",True,data,label=role+"stamp",
                              visits=INPLACE,change=same_stamp,evidence=evidence)
            for place in ("direct","library"):
                bind(root,"R")
                edge.run_case(root,trace,"C",place,"unwatched",True,data,label="Rclean",
                              environment=environment(root,True),evidence=evidence)
    finally:trace.close()
    counts=[]
    for term in sorted(out.glob("*/terminal.json")):
        counts.append([term.parent.name,len(load(term))])
    save(out/("first.json" if first else "terminal.json"),{"cases":counts,"commands":sum(n*2 for _,n in counts)})
    need(len(counts)==(2 if first else 22),"provider matrix incomplete")


def ruff(root):
    prepare_ruff(root,verbs.A,verbs.B,verbs.source_identity)
    trace=ExecTrace();trace.ready()
    try:
        for role in "SR":
            sdk,identity=bind(root,role)
            product=load(root/"receipts/pair.json")["products"]["C"]
            actual=role_files(sdk)
            need(set(actual)==set(product["runtime"]) and all(actual[k]==v for k,v in product["runtime"].items() if k!="bin/cargo"),
                 "changed compiler, backend, standard library, or other SDK input")
            for clean in ((False,True) if role=="R" else (False,)):
                mode="minimal-shell" if clean else "ordinary"
                out=root/"receipts/ruff-293"/role/mode
                work=root/"receipt-ruff-work";work.mkdir(exist_ok=True)
                env=environment(root,clean)(env_for(work,sdk))
                def installation(label,steps):
                    fresh(work,root/"seed");rows={}
                    for visit,state in steps:
                        check_host(root,7);verbs.restore(root/"ruff",state)
                        dest=out/label/visit
                        row=verbs.phase("test",root,work,sdk,env,"C",state,visit,trace,dest,
                                      require_typed_zmij_match=(role=="S"))
                        evidence(work,dest,row);rows[visit]=row
                    retire(work);return rows
                refs={s:installation("empty-"+s,[("clean",s)])["clean"] for s in ("old","new")}
                data=installation("visit",RUFF)
                checks={}
                for k,item in data.items():
                    if item["product"] is not None:
                        checks[k]={v:item["product"][v]==d for v,d in refs[item["state"]]["product"].items()}
                need(identity==sdk_id(sdk,env,CARGOS[role]),"native SDK switched within a Ruff arm")
                save(out/"terminal.json",{"cargo":CARGOS[role],"identity":identity,"states":[verbs.A,verbs.B],
                    "references":{k:r["product"] for k,r in refs.items()},"equal_to_empty":checks,
                    "native":{k:{n:r["native"][n] for n in ("full","link_only","cargo_link_driver","linkers")} for k,r in data.items()}})
                print("closed Ruff",role,mode,flush=True)
    finally:trace.close()


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("root",type=Path);p.add_argument("part",choices=("first","rest","ruff","bundle"))
    a=p.parse_args();root=a.root.resolve()
    if a.part=="ruff":ruff(root)
    elif a.part=="bundle":bundled(root)
    else:provider(root,a.part)
