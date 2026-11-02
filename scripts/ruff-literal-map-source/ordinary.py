"""An unmetered OLD→NEW ruff_linter library build and independently empty native references."""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));import scout
import native_payload as native
sys.path.insert(0,str(HERE.parent/"ruff-indexed-check-pmu"))
import worker as w
from acquire import LOG,ROOT,REG,need,sha,json_save
sys.path.insert(0,str(HERE.parent/"ruff-upstream-mono-pilot"));import normal_registry

SRC=scout.SRC;WORK=w.WORK;STATE=w.STATE
OWNERS=("ruff_linter","ruff_python_literal")
CMD=["cargo","+ohm","build","-p","ruff_linter","--lib","--locked","--offline","-j4","--message-format=json"]
ROLES={"S":scout.SDK,"P":ROOT/"reopened/normal","C":ROOT/"reopened/defer"}
SOURCES={"old":scout.OLD,"new":scout.NEW}
CANONICAL={"P":"08b6047c7880f6be14d8e32d4bd8096cd7331ebb5b4907961fbbd12307c600ac",
           "C":"c85792a82bfd85c9448c2a70668e4bc0034f8e1be25671aa3856944673f48153"}
FLOOR=15<<30

def norm(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def guard():
    need(shutil.disk_usage(WORK.parent).free>=FLOOR,"15 GiB free-space reserve")

def switch(version):
    scout.git("checkout","--detach","--quiet",SOURCES[version])
    need(scout.git("rev-parse","HEAD")==SOURCES[version] and not scout.git("status","--porcelain")
         and sha(SRC/"Cargo.lock")==scout.LOCK,"different working source")

def select(role,env):
    target=ROLES[role];alias=w.RUSTUP/"toolchains/ohm"
    if alias.is_symlink():alias.unlink()
    alias.symlink_to(target,target_is_directory=True)
    result=dict(env,LD_LIBRARY_PATH=str(target/"lib"))
    for name in ("cargo","rustc","rustdoc"):
        path=Path(w.run(["rustup","which","--toolchain","ohm",name],env=result).stdout.decode().strip())
        need(path.samefile(target/"bin"/name),("foreign tool",role,name))
    return result

def prepare():
    guard();WORK.mkdir()
    need(os.environ["GITHUB_REF"]=="refs/heads/charlie/qa-ruff-literal-29206-20261102" and
         os.environ["GITHUB_RUN_ATTEMPT"]=="1" and os.environ["GITHUB_SHA"]==os.environ["REVIEWED_HEAD"] and
         w.git(w.WS/"qa","rev-parse","HEAD")==os.environ["GITHUB_SHA"],"wrong QA source or rerun")
    need(scout.git("rev-parse",scout.NEW+"^")==scout.OLD and
         scout.git("diff","--name-only",scout.OLD,scout.NEW).splitlines()==scout.FILES,"different source edit")
    install=json.loads((LOG/"compiler-installations.json").read_bytes())
    for role,label in (("P","normal"),("C","defer")):
        files=install["arms"][label]["files"];need(norm(files)==CANONICAL[role],"different 66-file stage1 map")
        need(all(sha(ROLES[role]/k)==v for k,v in files.items()),"different physical compiler installation")
    driver,=(ROLES["S"]/"lib").glob("librustc_driver-*.so")
    official={"bin/rustc":"7e35096dab1b661924cb3c31982c870dd99c7c00a7fba28aa958f451e7c9474e",
              "bin/cargo":"3ce4e300d4463dfc769b6c18e138d1c951b02dfb15416a39cb5301303d168871",
              str(driver.relative_to(ROLES["S"])):"4c8ccf0072e8f382a3a3756fd60e46936a2bd206996201c55caffe58d29725db",
              "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd":"0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"}
    need(all(sha(ROLES["S"]/p)==h for p,h in official.items()) and (ROLES["S"]/"bin/rustdoc").is_file(),"different signed SDK")
    (w.RUSTUP/"toolchains").mkdir(parents=True);w.PROXIES.mkdir()
    (w.RUSTUP/"settings.toml").write_text('version = "12"\nprofile = "minimal"\n')
    for name in ("cargo","rustc","rustdoc","rustup"):
        (w.PROXIES/name).symlink_to(Path(shutil.which("rustup")).resolve(strict=True))
    for name in ("cargo-home","temp"):(WORK/name).mkdir()
    (LOG/"native-bodies").mkdir();(LOG/"archive-layouts").mkdir()
    env=dict(HOME=str(WORK/"home"),RUSTUP_HOME=str(w.RUSTUP),RUSTUP_AUTO_INSTALL="0",PATH=str(w.PROXIES)+":/usr/bin:/bin",
             CARGO_HOME=str(WORK/"cargo-home"),CARGO_TARGET_DIR=str(STATE/"target"),CARGO_BUILD_BUILD_DIR=str(STATE/"build"),
             CARGO_CACHE_AUTO_CLEAN_FREQUENCY="never",CARGO_NET_OFFLINE="true",CARGO_TERM_COLOR="never",LC_ALL="C",TMPDIR=str(WORK/"temp"),
             GIT_CONFIG_NOSYSTEM="1",GIT_CONFIG_GLOBAL="/dev/null",SSL_CERT_FILE="/etc/ssl/certs/ca-certificates.crt")
    switch("new"); fetched=select("S",env);fetched.pop("CARGO_NET_OFFLINE")
    w.run(["cargo","+ohm","fetch","--locked"],env=fetched,cwd=SRC,timeout=600)
    locks={(x["name"],x["version"]):x["checksum"] for x in tomllib.loads((SRC/"Cargo.lock").read_text())["package"] if "checksum" in x}
    checked={}
    for (name,version),expected in locks.items():
        path,=(WORK/"cargo-home/registry/cache").glob(f"*/{name}-{version}.crate")
        actual=sha(path);need(actual==expected,"different locked package: "+name);checked[name+"@"+version]=actual
    manifest=tomllib.loads((SRC/"crates/ruff_linter/Cargo.toml").read_text())
    need("ruff_python_literal" in manifest["dependencies"],"consumer no longer depends on changed library")
    json_save(LOG/"qualified-inputs.json",dict(command=CMD,sources=SOURCES,source_lock=scout.LOCK,source_edit=scout.FILES,
              locked_archives=checked,head=os.environ["GITHUB_SHA"],factory=REG["factory_run"],compiler_maps=CANONICAL,signed=official,
              boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),env=env))
    return env

def reset_state():
    guard();need(STATE==WORK/"state" and not STATE.is_symlink(),"unexpected compiler state")
    if STATE.exists():shutil.rmtree(STATE)

def run(folder,name,argv,env):
    guard();p=w.run(argv,env=env,cwd=SRC,timeout=1200,check=False)
    w.dump_gz(folder,name+".stdout.gz",p.stdout);w.dump_gz(folder,name+".stderr.gz",p.stderr)
    need(p.returncode==0,(name,p.returncode,p.stderr.decode(errors="replace")[-1200:]))
    return p.stdout

def preserve(path):
    key=sha(path);dst=LOG/"native-bodies"/(key+".zst")
    if not dst.exists():
        guard();subprocess.run(["zstd","-q","-T2","-3",str(path),"-o",str(dst)],check=True,timeout=120)
    return {"sha256":key,"size":path.stat().st_size}

def visit(role,version,label,env,pinned=None):
    print("Ordinary native visit",label,flush=True)
    switch(version); folder=LOG/label;folder.mkdir()
    rows=[json.loads(x) for x in run(folder,"cargo",CMD,env).splitlines()]
    need(rows[-1]=={"reason":"build-finished","success":True},"wrong Cargo terminal result")
    products=[r for r in rows if r["reason"]=="compiler-artifact"]
    dirty=sorted(r["target"]["name"] for r in products if not r["fresh"])
    need(all(not r["fresh"] for r in products) if pinned is None else
         "ruff_python_literal" in dirty and len(dirty)<len(products),"invalid clean/edit transition")
    registry=normal_registry.capture(rows,STATE,True)
    need(registry["products"]>100 and registry["shared"]>0 and registry["products"]>registry["shared"],"implausible actual registry placement")
    json_save(folder/"registry.json",registry)
    libs={}; dirs=set()
    for r in products:
        for s in r["filenames"]:
            path=Path(s);n=r["target"]["name"]
            if path.suffix in (".rlib",".rmeta",".so"):dirs.add(str(path.parent))
            if path.suffix==".rlib" and n in (*OWNERS,"ruff_python_ast"):
                need(n not in libs,"ambiguous "+n);libs[n]=path
    need(set(libs)=={*OWNERS,"ruff_python_ast"},"missing client archive")
    archives={};ledgers={}
    for owner in OWNERS:
        archive,recipe=native.manifest(libs[owner],LOG/"native-bodies")
        old=pinned.get(owner) if pinned else None
        session=native.current_session(STATE,owner,old[0] if old else None)
        ledger=native.observe_objects(session,old[1] if old else {},archive)
        key=sha(libs[owner]);json_save(LOG/"archive-layouts"/(key+".json"),recipe)
        archives[owner]={"sha256":key,"size":libs[owner].stat().st_size,"payload":archive}
        ledgers[owner]={"session":str(session),"objects":ledger}
    json_save(folder/"native-archives.json",archives);json_save(folder/"incremental-objects.json",ledgers)
    argv=["rustc","+ohm","--edition=2024","--crate-name","literal_consumer",HERE/"consumer.rs"]
    for name,path in sorted(libs.items()):argv+=["--extern",name+"="+str(path)]
    for d in sorted(dirs):argv+=["-L","dependency="+d]
    for d in sorted({d for r in rows if r["reason"]=="build-script-executed" for d in r["linked_paths"]}):argv+=["-L",d]
    exe=WORK/"reader";argv+=["-o",exe];json_save(folder/"link-client-argv.json",list(map(str,argv)));run(folder,"link-client",argv,env)
    verdicts={}
    for name,(value,old,new) in scout.CASES.items():
        verdicts[name]=run(folder,name,[exe,value],env).decode()
        need(verdicts[name]=="F401=1 used=0 invalid=1\n"+(old if version=="old" else new),"wrong native Unicode or linter verdict")
    roster=sorted([r["package_id"],r["target"]["name"],r["target"]["kind"],r["features"],r["profile"]["test"]] for r in products)
    record=dict(role=role,source=version,revision=SOURCES[version],registry={k:registry[k] for k in ("products","shared","sha256")},
                roster=norm(roster),units=len(products),dirty=dirty,client=preserve(exe),verdicts=verdicts,
                product_paths={n:str(p) for n,p in libs.items()})
    json_save(folder/"visit.json",record)
    return dict(record=record,archives=archives,ledgers=ledgers)

def opportunity(parent,candidate):
    owners={}
    for owner in OWNERS:
        p=parent["ledgers"][owner]["objects"];c=candidate["ledgers"][owner]["objects"]
        need(set(p)==set(c),"different source native CGU name set")
        gained=[];lost=[];red=0;net=0
        for name in sorted(p):
            a,b=p[name],c[name]
            if not a["after"] or not b["after"]:continue
            size=a["after"][2]
            need(a["after_sha256"]==b["after_sha256"] and a["after"][2]==b["after"][2],"different completed P/C native payload")
            if not a["retained"]:red+=size
            if b["retained"] and not a["retained"]:gained.append(name);net+=size
            if a["retained"] and not b["retained"]:lost.append(name);net-=size
        owners[owner]=dict(total=len(c),parent=sum(r["retained"] for r in p.values()),candidate=sum(r["retained"] for r in c.values()),
                           gained=gained,lost=lost,parent_regenerated_bytes=red,net_extra_donor_bytes=net)
    x=owners["ruff_linter"]
    return dict(owners=owners,meaningful=bool(x["parent_regenerated_bytes"] and
           10*x["net_extra_donor_bytes"]>=x["parent_regenerated_bytes"]),hardware_counters_collected=False)

def main():
    env=prepare();refs={};hist={}
    for role in "SPC":
        selected=select(role,env)
        for rev in ("old","new"):
            reset_state();refs[role,rev]=visit(role,rev,f"empty-{role}-{rev}",selected)
    for role in "PC":
        reset_state();selected=select(role,env)
        hist[role,"old"]=visit(role,"old",f"history-{role}-old",selected)
        with ExitStack() as stack:
            pinned={}
            for owner in OWNERS:
                session=native.current_session(STATE,owner);pinned[owner]=(session,native.old_files(stack,session))
            hist[role,"new"]=visit(role,"new",f"history-{role}-new",selected,pinned)
    all_visits=[*refs.values(),*hist.values()]
    first=refs["S","old"]["record"]
    for v in all_visits:
        r=v["record"];need((r["registry"],r["roster"],r["units"])==(first["registry"],first["roster"],first["units"]),
                           "different complete signed registry layout or Cargo roster")
    comparisons={}
    for rev in ("old","new"):
        for role in "PC":
            for owner in OWNERS:
                name=f"history-{role}-{rev}-vs-empty-{owner}"
                comparisons[name]=native.compare_objects(refs[role,rev]["archives"][owner]["payload"],hist[role,rev]["archives"][owner]["payload"])
        for owner in OWNERS:
            comparisons[f"empty-P-vs-C-{rev}-{owner}"]=native.compare_objects(refs["P",rev]["archives"][owner]["payload"],
                                                                              refs["C",rev]["archives"][owner]["payload"])
    json_save(LOG/"clean-comparisons.json",comparisons)
    need(all(not v for row in comparisons.values() for v in row.values()),"complete per-CGU native payload differs from independent clean")
    out=opportunity(hist["P","new"],hist["C","new"])
    out.update(head=os.environ["GITHUB_SHA"],source=SOURCES,factory=REG["factory_run"],units=first["units"],signed_registry=first["registry"])
    json_save(LOG/"accepted.json",out)
    print(json.dumps(out))

if __name__=="__main__":main()
