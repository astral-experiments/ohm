"""Build two complete, source-bound SDKs and test their exact emitted native products."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import registration as reg
import native_guard
import restore
from registration import need, sha, write

NATIVE_TESTS = ["incremental-directory-copy","incremental-session-fail","ohm-branch-cache-opt-out","ohm-packed-branch-cache",
                "ohm-checked-dep-info","ohm-relink-assembler-inputs","ohm-relink-incremental-objects"]
PACKED_NAMES = ["packs_only_private_and_superseded_objects_and_restores_exact_bytes","rejects_swapped_object_contents_with_the_same_session_and_filename"]


def toolchain(trusted):
    sys.path.insert(0,str(trusted/"scripts/gnu-renderer-cgu-source"))
    import build as helper
    return helper


def product_tests(b,repo,role,log):
    tests=[]
    for source,prefix in [("compiler/rustc_fs_util/src/tests.rs","tests::"),("compiler/rustc_incremental/src/persist/fs/tests.rs","persist::fs::tests::"),
                         ("compiler/rustc_incremental/src/persist/fs/packed/tests.rs","persist::fs::packed::tests::")]:
        names=re.findall(r"(?m)^#\[test\]\nfn ([a-z0-9_]+)\(",(repo/source).read_text())
        need(len(names)==(3 if prefix=="tests::" else 5 if prefix=="persist::fs::tests::" or role=="K" else 3),"unexpected original native tests")
        tests.extend(prefix+n for n in names)
    need(all(any(t.endswith("::"+n) for t in tests)==(role=="K") for n in PACKED_NAMES),"wrong packed controls")
    args=["./x",*b.OPTIONS,"--set","rust.verbose-tests=true","test",*b.HOST_FLAGS]
    loc=log/"rustc-units.log"
    b.succeeded([*args,"compiler/rustc_fs_util","compiler/rustc_incremental"],repo,loc)
    text=re.sub(r"\x1b\[[0-9;]*m","",loc.read_text())
    for name in tests:
        need(text.splitlines().count("test "+name+" ... ok")==1,"missing checked-in unit "+name)
    need("test result: FAILED" not in text,"native unit error")
    for test in NATIVE_TESTS:
        loc=log/(test+".log")
        b.succeeded([*args,"tests/run-make/"+test],repo,loc)
        b.verdict(loc.read_text(errors="replace"),test,True,0)
    write(log/"checked-in-tests.json",dict(unit=tests,run_make=NATIVE_TESTS,
          original_sources={p:sha(repo/"tests/run-make"/p/"rmake.rs") for p in NATIVE_TESTS}))


def selected(b,stage,root):
    vals=b.collect(stage,root)
    vals[Path("bin/cargo")]=root/"cargo/cargo-761"
    need(sha(vals[Path("bin/cargo")])==reg.ELF and sha(vals[Path(reg.WILD)])==reg.WILD_SHA,"wrong strict Cargo or Wild")
    return vals


def env_for(root):
    drop=("RUSTFLAGS","RUSTDOCFLAGS","RUSTC","RUSTDOC","RUSTC_WRAPPER","RUSTC_WORKSPACE_WRAPPER","RUSTUP_TOOLCHAIN","LD_PRELOAD","LD_LIBRARY_PATH","GH_TOKEN","GITHUB_TOKEN")
    return {k:v for k,v in os.environ.items() if k not in drop and not k.startswith("CARGO_")}|{
        "RUSTUP_HOME":str(root/"rustup"),"CARGO_HOME":str(root/"cargo-home"),"RUSTUP_AUTO_INSTALL":"0",
        "CARGO_NET_OFFLINE":"true","CARGO_TERM_COLOR":"never","CARGO_ENCODED_RUSTFLAGS":"-Zohm-branch-cache=yes",
        "GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":os.devnull,"LANG":"C.UTF-8"}


def native(b,root,sdk,log,role):
    alias=root/"rustup/toolchains/ohm"
    need(alias.is_symlink() and alias.resolve()==sdk,"wrong normal rustup path")
    env=env_for(root)
    native_state=log/"native-runtime";native_state.mkdir()
    # Archive the exact host executable resolution and shared libraries used on the official worker.
    libs={}
    driver,=(sdk/"lib").glob("librustc_driver*.so")
    for key,path in [("cargo",sdk/"bin/cargo"),("rustc",sdk/"bin/rustc"),("rustdoc",sdk/"bin/rustdoc"),("driver",driver),("wild",sdk/reg.WILD)]:
        p=subprocess.run(["ldd",path],capture_output=True,text=True)
        text=p.stdout+p.stderr
        need("not found" not in text and (p.returncode==0 or "not a dynamic executable" in text or "statically linked" in text),"unresolved native libraries: "+key)
        (native_state/(key+"-ldd.txt")).write_text(text)
        for name in re.findall(r"(?m)(?:=>\s+|^\s*)(/[^\s]+)\s+\(0x",text):
            fp=Path(name).resolve(strict=True);libs[str(fp)]=[sha(fp),fp.stat().st_size]
        if key in ("cargo","rustc","rustdoc"):
            paths=subprocess.check_output(["rustup","which","--toolchain","ohm",key],env=env,text=True).strip()
            need(Path(paths).samefile(path),"wrong normal rustup proxy: "+key)
    write(native_state/"native-object-identities.json",libs)
    testdir=root/"qualification-state";testdir.mkdir()
    (testdir/"api.rs").write_text("/// Source-qualified branch cache witness.\npub fn packed_branch_value() -> u32 { 17 }\n")
    b.succeeded(["rustdoc","+ohm","--edition=2024","--crate-name","guarded",testdir/"api.rs","-o",testdir/"doc"],testdir,log/"rustdoc-content.log",env)
    doc=testdir/"doc/guarded/fn.packed_branch_value.html"
    need(doc.is_file() and "Source-qualified branch cache witness." in doc.read_text(),"wrong matching rustdoc output")
    (testdir/"bad.rs").write_text("pub fn broken(_: UnavailableBranchQaType) {}\n")
    rc=b.log_run(["rustdoc","+ohm",testdir/"bad.rs","-o",testdir/"bad-doc"],testdir,log/"rustdoc-invalid.log",env)
    txt=(log/"rustdoc-invalid.log").read_text()
    need(rc==1 and "error[E0412]" in txt and "UnavailableBranchQaType" in txt and "internal compiler error" not in txt,"wrong native doc diagnostic")
    sys.path.insert(0,str(HERE.parent/"ohm-packed-ruff/full-cli"))
    from provider import native_controls
    native_controls(role,env,testdir,log)
    out=log/"native-shadow";out.mkdir()
    native_guard.guard(testdir,sdk,env,out)
    write(native_state/"qualified.json",dict(role=role,cargo=reg.ELF,wild=reg.WILD_SHA,doc=sha(doc),normal_native=6,shadow_native=16))
    shutil.rmtree(testdir)


def main(trusted):
    b=toolchain(trusted);root=b.ROOT;repo=root/"rust";rec=root/"receipts";transfer=root/"transfer"
    need(platform.system()=="Linux" and platform.machine()=="x86_64" and not root.is_symlink() and
         shutil.disk_usage(root).free>32*2**30 and os.environ["GITHUB_RUN_ATTEMPT"]=="1","wrong native enrollment")
    transfer.mkdir()
    reg.cargo(root/"cargo",rec)
    # Unmodified checked-in live source materializer is the same as the known successful 3-SDK job.
    from source import live_base
    live_base(repo,b.HERE/"packet")
    src=reg.source(repo,True,rec);write(rec/"source-transplant.json",src)
    roles={k:src["roles"][k] for k in ("F","K")};members={};versions=[];changes={}
    bound={"qa":os.environ["GITHUB_SHA"],"run":os.environ["GITHUB_RUN_ID"],"attempt":os.environ["GITHUB_RUN_ATTEMPT"]}
    for role in ("F","K"):
        log=rec/role;log.mkdir()
        srcid=roles[role]["commit"];b.git(repo,"checkout","--detach",srcid);b.check_source(repo,srcid)
        need(not (repo/"build").exists(),"old bootstrap products present")
        write(log/"source.json",dict(**roles[role],**bound,launcher=b.launcher(repo),llvm=b.LLVM))
        sdk_build=["./x",*b.OPTIONS,"build",*b.HOST_FLAGS,*b.SDK_COMPONENTS]
        b.succeeded(sdk_build,repo,log/"bootstrap.log")
        stage=repo/"build"/b.HOST/"stage1"
        actual0={"source":sha(repo/"src/stage0"),**{k:sha(stage.parent/"stage0/bin"/k) for k in ("rustc","cargo")}}
        need(actual0==b.STAGE0,"stage0 bytes differ")
        files=selected(b,stage,root);before=b.manifest(files);write(log/"before-tests.json",before)
        product_tests(b,repo,role,log)
        rem=b.manifest({k:p for k,p in files.items() if p.is_file()});need(all(before[n]==row for n,row in rem.items()),"tests rewrote retained SDK members")
        b.succeeded(sdk_build,repo,log/"reassemble.log")
        files=selected(b,stage,root);actual=b.manifest(files);write(log/"inventory.json",actual)
        need(actual==before,"tests changed the complete rebuilt SDK")
        driver,=[n for n in actual if n.startswith("lib/librustc_driver") and n.endswith(".so")]
        members[role]=actual
        if role=="F":
            b.archive(files,transfer/"F-sdk.tar.zst");driver_key=driver
        else:
            need(driver==driver_key and set(actual)==set(members["F"]),"different installed namespace")
            changes={n:[members["F"][n],row] for n,row in actual.items() if members["F"][n]!=row}
            write(log/"all-differences.json",changes)
            b.archive({Path(n):files[Path(n)] for n in changes},transfer/"K-delta.tar.zst")
            need(driver in changes and set(changes)<={driver,"bin/rustdoc"},"non-driver/library/source mismatch")
        b.operational(root,stage,files,{"F":"P","K":"C"}[role],log)
        versions.append((log/"rustc.log").read_bytes())
        need(versions[0]==versions[-1],"rustc version stamp differs")
        # Same physical role as the archived files is used by rustup & the real provider/flag tests.
        sdk=root/"operational";sdk.mkdir()
        for rel,p in files.items():
            target=sdk/rel;target.parent.mkdir(parents=True,exist_ok=True);os.link(p.resolve(),target)
        native(b,root,sdk,log,role)
        need(b.manifest(selected(b,stage,root))==actual,"ordinary use altered source-built SDK")
        shutil.rmtree(sdk);b.check_source(repo,srcid)
        folder=repo/"build";need(folder.resolve()==b.ROOT/"rust/build" and not folder.is_symlink(),"foreign bootstrap folder")
        shutil.rmtree(folder)
    products={p.name:[sha(p),p.stat().st_size] for p in transfer.iterdir()}
    m=dict(**bound,qualified=True,roles=roles,files=members,driver=driver_key,delta=sorted(changes),products=products,
           strict_cargo=reg.CARGO,wild=reg.WILD,host=reg.HOST,stage0=b.STAGE0,llvm=b.LLVM,compiler_verbose=versions[0].decode(),
           tests={r:sha(rec/r/"checked-in-tests.json") for r in roles},origin=sha(rec/"cargo-origin.json"))
    out=transfer/"manifest.json";write(out,m)
    for role in roles:
        dest=root/"operational"
        terminal=restore.restore(transfer,dest,role,bound["qa"],bound["run"],"1",sha(out))
        need(subprocess.check_output(["rustc","+ohm","-vV"],env=env_for(root))==versions[0],"restored rustup mismatch")
        terminal["cargo_version"]=subprocess.check_output(["cargo","+ohm","-Vv"],env=env_for(root),text=True)
        need("commit-hash: "+reg.CARGO in terminal["cargo_version"],"wrong restored Cargo")
        write(rec/role/"restored.json",terminal);shutil.rmtree(dest)
    write(rec/"qualified.json",dict(**bound,manifest=sha(out),roles=roles,products=products,common=len(members["F"])-len(changes),changed=sorted(changes)))
    print((rec/"qualified.json").read_text(),flush=True)


if __name__=="__main__":main(Path(sys.argv[1]).resolve())
