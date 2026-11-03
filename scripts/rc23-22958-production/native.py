"""Install the GNU archive and run the selected source's original regressions on its real driver."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

H=Path(__file__).resolve().parent
sys.path.insert(0,str(H))
import gate as s
import sdk

def runlog(argv, cwd, env, path, timeout=None):
    with path.open("xb") as stream:
        subprocess.run(list(map(str,argv)),cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=timeout)
    return {"argv":list(map(str,argv)),"log":path.name,"log_sha256":s.h(path),"exit":0}

def out(cmd,env,cwd=None):
    return subprocess.check_output(list(map(str,cmd)),cwd=cwd,env=env,text=True).strip()

def check_training(log):
    lines=log.splitlines()
    assert lines.count(s.PGO)==1
    assert lines.count("patching file collector/src/compile/benchmark/mod.rs")==1
    assert any("Section `Stage 3 (BOLT) > Instrument & gather profiles` ended: OK" in l for l in lines)
    assert any("BOLT-INFO: basic block reordering modified layout"in l for l in lines)

def main():
    w=s.checkout("build");enroll=s.selected();name=os.environ["BENCH_ARM"]
    arm=enroll["roles"][name];r=w/"source/rust";qa=w/"trait-evidence";src=s.read(qa/"source.json")
    assert src["source"]==arm and s.text(r,"rev-parse","HEAD")==arm["commit"] and src["release_files"]==s.POLICY["release_files"]
    check_training((qa/"build.log").read_text(errors="replace"))
    target=s.POLICY["target"];dest=w/"trait-sdk";dest.mkdir();tmp=w/"rc23-native";tmp.mkdir()
    raw=r/"build/dist"/(sdk.TARBASE+".tar.gz");archive=dest/"ohm.tar.gz";assert raw.is_file() and not raw.is_symlink()
    os.link(raw,archive);installed,inv=sdk.extract(archive,tmp);db=s.read(inv);component=tmp/"component-inventory.json"
    meta=s.read(component)["distribution_metadata"]
    assert meta["git-commit-hash"].strip()==arm["commit"] and meta["rust-installer-version"].strip()=="3" and s.POLICY["tag"] in meta["version"]
    driver,=[p for p in db if re.fullmatch(r"lib/librustc_driver-[0-9a-f]+\.so",p)]
    llvm,=[p for p in db if re.fullmatch(r"lib/libLLVM\.so\.[0-9].+",p)]
    env={"PATH":"/usr/bin:/bin","HOME":str(tmp),"LC_ALL":"C"}
    rustc=installed/"bin/rustc"
    rc=out([rustc,"-vV"],env);cargo=out([installed/"bin/cargo","-Vv"],env);ld=out(["ldd",rustc],env)
    assert "commit-hash: "+arm["commit"] in rc and "host: "+target in rc
    assert s.POLICY["sources"]["cargo"]["revision"] in cargo and ".note.bolt_info" in out(["readelf","-SW",installed/driver],env)
    for path in (driver,llvm):
        m=re.search(r"(?m)^\s*"+re.escape(Path(path).name)+r"\s+=>\s+(\S+)",ld)
        assert m and Path(m[1]).resolve()==(installed/path).resolve()
    for f in (inv,component,qa/"source.json"):shutil.copyfile(f,dest/f.name)
    assert shutil.disk_usage(w).free>=50*(1<<30), "need 50 GiB for isolated native QA"
    tests=w/"rc23-test-build";assert not tests.exists();cfg=tmp/"bootstrap.toml"
    cfg.write_text('[build]\nbuild-dir = "'+str(tests)+'"\nsubmodules = false\ncompiler-docs = false\n[llvm]\ndownload-ci-llvm = true\n[rust]\nchannel = "dev"\ndownload-rustc = false\nlto = "off"\noptimize = true\ndebug-assertions = false\nverbose-tests = true\n')
    base=[sys.executable,r/"x.py","--ci","false","--config",cfg,"test","--stage","1","--host",target,"--target",target]
    suites=s.scopes(name);commands={}
    if name!="full_without_ctfe":commands["ctfe-unit"]=(["compiler/rustc_middle","--test-args",s.UNIT],["test mir::interpret::tests::"+s.UNIT+" ... ok"])
    if name!="ctfe_control":commands["derive-unit"]=(["compiler/rustc_hir_id","--test-args","proc_derive_impl_tests"],["test definitions::proc_derive_impl_tests::"+s.DERIVE_UNIT+" ... ok"])
    import candidate
    assert name == "G"
    commands["derive-unit"][1].append("test definitions::proc_derive_impl_tests::"+candidate.UNIT+" ... ok")
    commands["run-make"]=(["tests/run-make/"+x for x in suites],["test [run-make] tests/run-make/"+x+" ... ok" for x in suites])
    native={}
    for key,(args,expected)in commands.items():
        logfile=qa/(key+".log");native[key]=runlog(base+args,r,None,logfile)
        lines=logfile.read_text(errors="replace").splitlines()
        assert all(lines.count(s)==1 for s in expected) and any(re.search(r"^test result: ok\. [1-9]\d* passed; 0 failed; 0 ignored;",line) for line in lines)
        assert not any("test result: FAILED"in line for line in lines)
    stage0=tests/target/"stage0";assert (stage0/"bin/rustc").is_file()
    runenv=env|{"TARGET":target,"HOST":target,"RUSTC":str(rustc),"RUSTC_BOOTSTRAP":"1","LD_LIB_PATH_ENVVAR":"LD_LIBRARY_PATH",
                "LD_LIBRARY_PATH":str(stage0/"lib/rustlib"/target/"lib"),"HOST_RUSTC_DYLIB_PATH":str(installed/"lib"),
                "TARGET_EXE_DYLIB_PATH":str(installed/"lib/rustlib"/target/"lib")}
    results={}
    recipes=list(tests.rglob("rmake"))
    for test in suites:
        exe,=[p for p in recipes if p.is_file() and p.parent.name.split(".",1)[0]==test]
        target_dir=tmp/("installed-"+test);origin=r/"tests/run-make"/test;shutil.copytree(origin,target_dir)
        files={str(p.relative_to(origin)):s.oid(p.read_bytes()) for p in sorted(origin.rglob("*")) if p.is_file()}
        for relative,blob in files.items():assert s.text(r,"rev-parse","HEAD:tests/run-make/"+test+"/"+relative)==blob
        installed_env=runenv
        if test==arm["run_make"]:
            llvm_bin=tests/target/"ci-llvm/bin"
            llvm_nm=llvm_bin/"llvm-nm"
            assert (llvm_bin/"llvm-config").is_file() and llvm_nm.is_file() and os.access(llvm_nm,os.X_OK)
            assert llvm_nm.resolve().is_relative_to((tests/target/"ci-llvm").resolve())
            installed_env=runenv | {"LLVM_BIN_DIR":str(llvm_bin)}
        result=runlog([exe],target_dir,installed_env,qa/("installed-"+test+".log"),600)
        if test==arm["run_make"]:
            result["llvm_nm"]={"path":str(llvm_nm),"sha256":s.h(llvm_nm),"version":out([llvm_nm,"--version"],installed_env)}
        result.update(recipe_sha256=s.h(exe),driver_sha256=db[driver]["sha256"],fixture_blobs=files)
        outputs={}
        if test==s.CTFE:outputs={"main":"LShift Or false 17"}
        if test==s.DOMAIN:outputs={"reader":"11 0 0","local":"0"}
        if test==s.DERIVE:outputs={"consumer":"(5, 11, 7)"}
        if test==arm["run_make"]:outputs=arm["linked_outputs"]
        for fn,expected in outputs.items():assert out([target_dir/fn],runenv,cwd=target_dir)==expected
        result["linked_outputs"]=outputs;results[test]=result
    product={"role":name,"source_commit":arm["commit"],"source_tree":arm["tree"],"epoch":arm["epoch"],"metadata_epoch":arm["metadata_epoch"],
             "archive_bytes":archive.stat().st_size,"archive_sha256":s.h(archive),"source_sha256":s.h(dest/"source.json"),
             "sdk_inventory_sha256":s.h(inv),"component_inventory_sha256":s.h(component),"launcher":db["bin/rustc"]|{"path":"bin/rustc"},
             "driver":db[driver]|{"path":driver},"llvm":db[llvm]|{"path":llvm},"bundled_cargo":db["bin/cargo"]|{"path":"bin/cargo"},
             "effective_benchmark_cargo_sha256":enroll["signed_cargo_sha256"],"execution_pgo":s.PGO,"bolt_note":True,"relocated_dependencies":True,
             "native_unit_and_runmake":native,"installed_runmake":results,"release_recipe":src["release_files"],"training_objects":src["training_objects"],
             "rustc_banner":rc,"cargo_banner":cargo,"resolved_libraries":ld}
    s.write(dest/"role.json",product);shutil.copyfile(dest/"role.json",qa/"role.json")
    names=("ohm.tar.gz","source.json","role.json","sdk-inventory.json","component-inventory.json")
    (dest/"SHA256SUMS").write_text("".join(s.h(dest/n)+"  "+n+"\n"for n in names))

if __name__=="__main__":main()
