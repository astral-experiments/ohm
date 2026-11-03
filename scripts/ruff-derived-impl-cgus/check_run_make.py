"""Build the unchanged run-make-support driver and exercise the actual source fixture."""
import hashlib,json,os,shutil,subprocess as sp,sys
from pathlib import Path
q=Path(__file__).resolve().parent;root=Path(os.environ['GITHUB_WORKSPACE']);out=Path(os.environ['RUNNER_TEMP'])/'derived-runmake-results';out.mkdir();tmp=out.parent/'derived-runmake-private';tmp.mkdir();source=root/'support/scripts/placed-object-run-make';factory=root/'factory/scripts/ruff-derived-impl-cgus'
sys.path.insert(0,str(source));from support_tree import materialize
sys.path.insert(0,str(factory));import transport
def H(p):
 with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(n,x):(out/n).write_text(json.dumps(x,indent=1,sort_keys=True)+'\n')
def head(p):return sp.check_output(['git','-C',p,'rev-parse','HEAD'],text=True).strip()
assert head(root/'support')=='b531208c36579c95ab63e60d8882d14be9634c9b' and head(root/'factory')=='2672756eb5b9d4e890b678d439dc6c40a29a4008' and head(root/'qa')==os.environ['REVIEWED_HEAD'];assert shutil.disk_usage(tmp).free>16*2**30
spec=json.loads((source/'source.json').read_bytes());assert spec['support_trees']=={'src/build_helper':'485308429b4182080dc2a305b592ed9643074517','src/rustdoc-json-types':'7b40a0b2a03d205e3eb16473b05b411ec77627de','src/tools/run-make-support':'cf379f9a163ed46a216b90df6df742aeca9a840d'}and spec['support_files']=={'src/stage0':'2b3c07d4d457c516754477d36a21529d0cabbfdd'};rust=materialize(tmp/'rust',(source/'support.pack').read_bytes(),spec);sdks={};sources={};proofs={}
for k in ('P','C'):
 tar,proof=transport.fetch(k,tmp/'inputs',out/(k+'-factory'));sdk=tmp/('sdk-'+k);alias=tmp/('rustup-'+k)/'toolchains/ohm';alias.parent.mkdir(parents=True);transport.install(tar,proof,sdk,alias);sdks[k]=sdk;sources[k]=json.loads((out/(k+'-factory')/'source.json').read_bytes())['source'];proofs[k]=proof['driver']
host=tmp/'host';(host/'src').mkdir(parents=True);shutil.copyfile(q/'run-make-fixture/rmake.rs',host/'src/main.rs');(host/'Cargo.toml').write_text('[package]\nname="placed-object-rmake"\nversion="0.0.0"\nedition="2024"\n[workspace]\n[dependencies]\nrun_make_support={path='+json.dumps(str(rust/'src/tools/run-make-support'))+'}\n');assert H(source/'driver.Cargo.lock')==spec['qualified_driver_lock'];shutil.copyfile(source/'driver.Cargo.lock',host/'Cargo.lock')
env=dict(os.environ,RUSTC=str(sdks['C']/'bin/rustc'),RUSTC_BOOTSTRAP='1',LD_LIBRARY_PATH=str(sdks['C']/'lib'),CARGO_TARGET_DIR=str(tmp/'host-target'),CARGO_INCREMENTAL='0',CARGO_PROFILE_DEV_DEBUG='0')
for k in ('RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','RUSTFLAGS','RUNNER','CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST','CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST'):env.pop(k,None)
sp.run(['cargo','+stable','build','--locked','-j4'],cwd=host,env=env,check=True,timeout=500);exe=tmp/'host-target/debug/placed-object-rmake';t='x86_64-unknown-linux-gnu';res={}
save('binding.json',{'drivers':proofs,'sources':sources,'driver_program':H(exe),'fixture':{p.name:H(p)for p in sorted((q/'run-make-fixture').iterdir())},'support_trees':spec['support_trees'],'lock':H(host/'Cargo.lock')})
for k in ('P','C'):
 case=tmp/('case-'+k);case.mkdir();[shutil.copyfile(q/'run-make-fixture'/n,case/n)for n in ('derived.rs','methods.rs')];sdk=sdks[k];e=dict(env,RUSTC=str(sdk/'bin/rustc'),LD_LIBRARY_PATH=str(sdk/'lib'),HOST_RUSTC_DYLIB_PATH=str(sdk/'lib'),TARGET_EXE_DYLIB_PATH=str(sdk/'lib/rustlib'/t/'lib'),LD_LIB_PATH_ENVVAR='LD_LIBRARY_PATH',TARGET=t,HOST=t,LC_ALL='C')
 p=sp.run([exe],env=e,cwd=case,capture_output=True,timeout=340);assert len(p.stdout)+len(p.stderr)<2<<20;(out/(k+'.out')).write_bytes(p.stdout);(out/(k+'.err')).write_bytes(p.stderr);res[k]={'rc':p.returncode,'activation_expectation':b'left: 0\n right: 3'in p.stderr,'stdout':H(out/(k+'.out')),'stderr':H(out/(k+'.err'))};save('verdicts.json',res);print(k,res[k],p.stderr[-1200:].decode(errors='replace'),flush=True)
 assert int(next(x.split()[1]for x in Path('/proc/meminfo').read_text().splitlines()if x.startswith('MemAvailable:')))>8*2**20
assert res['P']['rc']==101 and res['P']['activation_expectation']and res['C']['rc']==0,res;save('terminal.json',{'qualified':True,'actual_genuine_run_make_support':True,'complete_original_run_make':True})
