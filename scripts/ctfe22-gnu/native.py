"""Seal GNU production components, run original regressions, then run the same recipe on this SDK."""
import hashlib,json,os,re,shutil,subprocess,sys
from pathlib import Path
H=Path(__file__).resolve().parent;sys.path.insert(0,str(H));import sdk as s
S=s.read(H/"arms.json");S["arms"]["callables_ctfe318"]=s.read(H/"callable-source.json")["source"];S["arms"]["callables_ctfe318_incoherent_domain"]=s.read(H/"domain-source.json")["source"];HOST=s.TARGET;UNIT="only_the_original_ctfe_literal_id_is_restored";PGO="verified executed PGO profile coverage for rustc, rustdoc, Cargo, Clippy, rustfmt, and cargo-fmt"
def out(*a,env=None):return subprocess.check_output(a,text=True,env=env).strip()
def obj(data):return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
def fixture(role,where):
 fixture=S["fixture_directory"]+"/";expected={p[len(fixture):]:v for p,v in S["arms"][role]["ctfe_blob_ids"].items() if p.startswith(fixture)}
 assert set(expected)=={"rmake.rs","main.rs","lib.rs","right.rs"}
 for n,oid in expected.items():assert obj((where/n).read_bytes())==obj((H/"fixture"/n).read_bytes())==oid
 return expected
def suites(role):
 names=[S["fixture_directory"],"tests/run-make/rdr-public-hash-native-exports"]
 assert role=="callables_ctfe318_incoherent_domain"
 names.extend(['tests/run-make/trait-impl-bucket-projection', 'tests/run-make/trait-impl-bucket-coroutine', 'tests/run-make/trait-impl-bucket-callables', 'tests/run-make/trait-impl-bucket-sparse-foreign'])
 names.append("tests/run-make/crate-incoherent-impl-domain")
 return names
def gate_suites(log,role):
 for test in suites(role):assert log.splitlines().count("test [run-make] "+test+" ... ok")==1
def gate_log(log,kind):
 if kind=="unit":key="test mir::interpret::tests::"+UNIT+" ... ok"
 else:key="test [run-make] "+S["fixture_directory"]+" ... ok"
 assert log.splitlines().count(key)==1 and re.search(r"(?m)^test result: ok\. [1-9]\d* passed; 0 failed; 0 ignored;",log) and "test result: FAILED" not in log
def native(role):
 W=Path(os.environ["GITHUB_WORKSPACE"]).resolve();R=W/"source/rust";qa=W/"trait-evidence";dest=W/"trait-sdk";dest.mkdir();tmp=W/"ctfe22-native";tmp.mkdir()
 source=s.read(qa/"source.json");arm=S["arms"][role];assert source["role"]==role and source["source"]==arm and source["reviewed_head"]==os.environ["GITHUB_SHA"]
 assert s.sha(R/"src/tools/opt-dist/component-pgo-v1") and source["training_objects"]["src/tools/rustc-perf"]=="0a054b0ead56e41a4584bfab6fdc1a5fad2aedc3"
 logs=(qa/"build.log").read_text(errors="replace").splitlines();assert logs.count(PGO)==1
 assert any("Section `Stage 3 (BOLT) > Instrument & gather profiles` ended: OK" in t for t in logs) and any("BOLT-INFO: basic block reordering modified layout" in t for t in logs)
 raw=R/"build/dist"/(s.TARBASE+".tar.gz");archive=dest/"ohm.tar.gz";assert raw.is_file() and not raw.is_symlink()
 os.link(raw,archive);sha=s.sha(archive);sdk,inv=s.extract(archive,tmp);db=s.read(inv);m=s.read(tmp/"component-inventory.json")["distribution_metadata"]
 assert m["git-commit-hash"].strip()==arm["commit"] and m["rust-installer-version"].strip()=="3" and "ohm-1.99.0-22" in m["version"]
 driver,=[p for p in db if re.fullmatch(r"lib/librustc_driver-[0-9a-f]+\.so",p)]
 llvm,=[p for p in db if re.fullmatch(r"lib/libLLVM\.so\.[0-9].+",p)]
 clean={"PATH":"/usr/bin:/bin","HOME":str(tmp),"LC_ALL":"C"}
 rc=out(sdk/"bin/rustc","-vV",env=clean);cg=out(sdk/"bin/cargo","-Vv",env=clean);ld=out("ldd",sdk/"bin/rustc",env=clean)
 assert "commit-hash: "+arm["commit"] in rc and "host: "+HOST in rc and S["source_components"]["cargo"] in cg
 for p in (driver,llvm):
  match=re.search(r"(?m)^\s*"+re.escape(Path(p).name)+r"\s+=>\s+(\S+)",ld);assert match and Path(match.group(1)).resolve()==(sdk/p).resolve(),(p,ld)
 notes=out("readelf","-SW",sdk/driver,env=clean);assert ".note.bolt_info" in notes
 for n in ("source.json",):shutil.copyfile(qa/n,dest/n)
 for n in ("sdk-inventory.json","component-inventory.json"):shutil.copyfile(tmp/n,dest/n)
 fixture(role,R/S["fixture_directory"])
 testdir=W/"ctfe22-test-build";assert not testdir.exists()
 cfg=tmp/"bootstrap.toml";cfg.write_text('[build]\nbuild-dir = '+json.dumps(str(testdir))+'\nsubmodules = false\ncompiler-docs = false\n[llvm]\ndownload-ci-llvm = true\n[rust]\nchannel = "dev"\ndownload-rustc = false\nlto = "off"\noptimize = true\ndebug-assertions = false\nverbose-tests = true\n')
 assert shutil.disk_usage(W).free >= 50*(1<<30),"need 50 GiB free after production archive for isolated native checks"
 base=[sys.executable,str(R/"x.py"),"--ci","false","--config",str(cfg),"test","--stage","1","--host",HOST,"--target",HOST]
 test_info={}
 for kind,extra in [("unit",["compiler/rustc_middle","--test-args",UNIT]),("run-make",suites(role))]:
  argv=base+extra;log=qa/(kind+".log")
  with log.open("xb") as f:subprocess.run(argv,cwd=R,stdout=f,stderr=subprocess.STDOUT,check=True)
  passed=log.read_text(errors="replace");gate_log(passed,kind)
  if kind=="run-make":gate_suites(passed,role)
  test_info[kind]={"argv":argv,"log_sha256":s.sha(log)}
 # Compiletest built this executable from the unchanged, source-verified rmake.rs. Reuse that very binary.
 recipes=[p for p in testdir.rglob("rmake") if p.is_file() and p.parent.name.split(".",1)[0]==Path(S["fixture_directory"]).name]
 assert len(recipes)==1,recipes
 native_fixture=tmp/"optimized-fixture";shutil.copytree(H/"fixture",native_fixture)
 stage0=testdir/HOST/"stage0";assert (stage0/"bin/rustc").is_file()
 env=clean|{"TARGET":HOST,"HOST":HOST,"RUSTC":str(sdk/"bin/rustc"),"RUSTC_BOOTSTRAP":"1","LD_LIB_PATH_ENVVAR":"LD_LIBRARY_PATH","LD_LIBRARY_PATH":str(stage0/"lib/rustlib"/HOST/"lib"),"HOST_RUSTC_DYLIB_PATH":str(sdk/"lib"),"TARGET_EXE_DYLIB_PATH":str(sdk/"lib/rustlib"/HOST/"lib")}
 actual=qa/"optimized-run-make.log"
 with actual.open("xb") as f:subprocess.run([recipes[0]],cwd=native_fixture,env=env,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=180)
 assert (native_fixture/"libdep.rlib").is_file() and (native_fixture/"main").is_file()
 expected=(H/"fixture/right.rs").read_text().replace("FloorDiv,","FloorDiv, LShift,").replace("Operator::Or","Operator::LShift")
 assert (native_fixture/"left.rs").read_text()==expected
 linked=subprocess.check_output([native_fixture/"main"],cwd=native_fixture,env=env);assert linked==b"LShift Or false 17\n"
 h=out(sdk/"bin/rustc","-Zls=public_hash",native_fixture/"libdep.rlib",env=env);assert re.search(r"[0-9a-f]{32}",h),h
 product={"role":role,"source_commit":arm["commit"],"source_tree":arm["tree"],"epoch":arm["epoch"],"archive_sha256":sha,"archive_bytes":archive.stat().st_size,"source_sha256":s.sha(dest/"source.json"),"sdk_inventory_sha256":s.sha(inv),"component_inventory_sha256":s.sha(tmp/"component-inventory.json"),"launcher":db["bin/rustc"]|{"path":"bin/rustc"},"driver":db[driver]|{"path":driver},"llvm":db[llvm]|{"path":llvm},"bundled_cargo":db["bin/cargo"]|{"path":"bin/cargo"},"effective_benchmark_cargo_sha256":S["signed_cargo_binary_sha256"],"unit_and_original_runmake":test_info,"installed_original_runmake":{"original_files":fixture(role,H/"fixture"),"binary_sha256":s.sha(recipes[0]),"compiler_sha256":s.sha(sdk/"bin/rustc"),"driver_sha256":s.sha(sdk/driver),"log_sha256":s.sha(actual),"exit":0,"final_linked_output":linked.decode(),"final_crate_public_hash":h},"execution_pgo":PGO,"bolt_note":True,"release_recipe":source["recipe"],"training_objects":source["training_objects"],"rustc_banner":rc,"cargo_banner":cg,"resolved_libraries":ld}
 installed_callable={}
 for name in ['trait-impl-bucket-coroutine', 'trait-impl-bucket-callables', 'trait-impl-bucket-sparse-foreign', 'crate-incoherent-impl-domain']:
  path="tests/run-make/"+name
  recipe,=[p for p in testdir.rglob("rmake") if p.is_file() and p.parent.name.split(".",1)[0]==name]
  case=tmp/("optimized-"+name);shutil.copytree(R/path,case)
  proof=qa/("optimized-"+name+".log")
  with proof.open("xb") as stream:
   subprocess.run([recipe],cwd=case,env=env,stdout=stream,stderr=subprocess.STDOUT,check=True)
  installed_callable[name]={"exit":0,"log_sha256":s.sha(proof),"recipe_sha256":s.sha(recipe),"driver_sha256":s.sha(sdk/driver)}
 domain=installed_callable.pop("crate-incoherent-impl-domain")
 case=tmp/"optimized-crate-incoherent-impl-domain"
 finals={n:subprocess.check_output([case/n],cwd=case,env=env).decode().strip() for n in ("reader","local")}
 assert finals=={"reader":"11 0 0","local":"0"}
 conf=s.read(H/"domain-source.json");fixture_paths={p:oid for p,oid in conf["files"].items() if p.startswith("tests/run-make/crate-incoherent-impl-domain/")}
 assert len(fixture_paths)==5 and all(obj((R/p).read_bytes())==oid for p,oid in fixture_paths.items())
 product["installed_crate_domain_test"]=domain|{"fixture_blobs":fixture_paths,"final_outputs":finals,"foreign_states":10,"foreign_transitions":9,"both_solvers":True,"local_states":3,"local_transitions":2,"diagnostic":"E0061"}
 product["installed_callable_tests"]=installed_callable
 s.save(dest/"role.json",product)
 members=("ohm.tar.gz","source.json","role.json","sdk-inventory.json","component-inventory.json")
 (dest/"SHA256SUMS").write_text("".join(s.sha(dest/n)+"  "+n+"\n" for n in members));shutil.copyfile(dest/"role.json",qa/"role.json")
if __name__=="__main__":native(*sys.argv[1:])
