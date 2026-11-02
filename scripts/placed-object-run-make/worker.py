"""Execute the real Rust run-make driver with both complete source-built GNU toolchains. No timer or counter."""
import hashlib,json,os,shutil,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];ROLE={'P':'531eb1980c08c75ccbf3f6b77adbee53cd9b8bd5','C':'4e546b27c311f29d99f9528e64420887f57c7538'};HOST='x86_64-unknown-linux-gnu';B='b1dc1a4f68436a260a4c15e2562aec5f4c550434';H=lambda b:hashlib.sha256(b).hexdigest();read=lambda p:json.loads(p.read_bytes());save=lambda p,v:p.write_text(json.dumps(v,indent=1,sort_keys=True)+'\n');git=lambda p,*a:subprocess.check_output(['git','-C',p,*a],text=True).strip();room=lambda path:shutil.disk_usage(path).free

def execute(src,case,out,driver,sdk):
    case.mkdir();[shutil.copyfile(HERE/'fixture'/n,case/n)for n in ('lib.rs','main.rs')]
    env=dict(os.environ,RUSTC=str(sdk/'bin/rustc'),RUST_BACKTRACE='0',LD_LIBRARY_PATH=str(sdk/'lib'),HOST_RUSTC_DYLIB_PATH=str(sdk/'lib'),TARGET_EXE_DYLIB_PATH=str(sdk/'lib/rustlib'/HOST/'lib'),LD_LIB_PATH_ENVVAR='LD_LIBRARY_PATH',TARGET=HOST,HOST=HOST,LC_ALL='C')
    for key in ('RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','RUSTFLAGS','RUNNER','REMOTE_TEST_CLIENT','CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST','CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST'):env.pop(key,None)
    cmd=[str(driver)];p=subprocess.run(cmd,cwd=case,env=env,capture_output=True,timeout=140);assert len(p.stdout)+len(p.stderr)<2<<20
    (out/'stdout').write_bytes(p.stdout);(out/'stderr').write_bytes(p.stderr)
    # Authentic selection/fallback inputs remain available if the product has to decline this source shape.
    files={}
    for f in sorted(case.rglob('*')):
        if f.is_file()and(f.name in('libplacement.rlib','work-products.bin','lib.rs','main.rs','caller')or f.suffix=='.o'):
            rel=str(f.relative_to(case));b=f.read_bytes();files[rel]={'bytes':len(b),'sha256':H(b)}
            if len(b)<1<<20 and (f.name.endswith('.rlib')or f.name=='work-products.bin' or f.suffix=='.o'):
                o=out/'bodies'/H(b);o.parent.mkdir(exist_ok=True);o.write_bytes(b)
    r={'rc':p.returncode,'stdout_sha256':H(p.stdout),'stderr_sha256':H(p.stderr),'files':files,'qualified_source':src,'driver':H(driver.read_bytes()),'rustc_version':subprocess.check_output([env['RUSTC'],'-vV'],env=env,text=True),'sysroot':subprocess.check_output([env['RUSTC'],'--print=sysroot'],env=env,text=True).strip()};save(out/'result.json',r);return r,p.stderr

def main():
    out=Path(os.environ['OUTPUT']);out.mkdir();tmp=Path(os.environ['RUNNER_TEMP'])/'placed-runmake-original';tmp.mkdir();rust=tmp/'rust-source';enroll=read(HERE/'source.json');assert __debug__ and os.environ['GITHUB_REPOSITORY']=='astral-experiments/ohm' and os.environ['GITHUB_REF']=='refs/heads/charlie/qa-placed-object-runmake-20261102' and os.environ['GITHUB_EVENT_NAME']=='workflow_dispatch'and os.environ['GITHUB_RUN_ATTEMPT']=='1';assert git(ROOT,'rev-parse','HEAD')==os.environ['GITHUB_SHA']==os.environ['REVIEWED_HEAD'];sys.path.insert(0,str(HERE));from support_tree import materialize;materialize(rust,(HERE/'support.pack').read_bytes(),enroll);assert git(rust,'rev-parse','HEAD')==ROLE['P'];assert all(git(rust,'rev-parse','HEAD:'+path)==sha for path,sha in enroll['support_trees'].items());assert {p.name:H(p.read_bytes())for p in (HERE/'fixture').iterdir()}==enroll['fixture'];assert sys.argv[1:]==['--verify-source-only'] or room(tmp)>=22*(1<<30)
    original=HERE.parent/'ruff-source-placement';assert H((original/'receiver.py').read_bytes())=='1cdaa25fd34cecaef8d02af7aee41cfe3bef077b3ce62b9383f617d9cb1e7065';assert all(git(ROOT,'rev-parse','HEAD:'+path)==sha for path,sha in enroll['receiver_trees'].items());sys.path.insert(0,str(original));import common,receiver
    reg=common.source_binding();assert {k:v['revision']for k,v in reg['roles'].items()}==ROLE;common.capsule.HERE,common.capsule.REG=original,reg;
    if sys.argv[1:]==['--verify-source-only']:
        print('verified actual source trees, native receiver and both enumerated roles');return
    assert not sys.argv[1:];inputs=tmp/'sdks';receiver.install(inputs,registration=reg);shutil.copyfile(inputs/'source-qualification.json',out/'source-qualification.json');shutil.copyfile(inputs/'docs-qualification.json',out/'docs-qualification.json');sdks={k:inputs/'parked'/label for k,label in [('P','normal'),('C','defer')]};qualified=read(out/'source-qualification.json');assert qualified['factory_run']==41475100027 and qualified['archive']['id']==13157906963
    for k,sdk in sdks.items():
        dsos=list((sdk/'lib').glob('librustc_driver-*.so'));assert len(dsos)==1 and H(dsos[0].read_bytes())==qualified['physical'][k]['driver'];assert (sdk/'bin/rustc').is_file()
    from native_control import probe
    direct={}
    for k in ('P','C'):
        direct[k]=probe(HERE/'fixture',sdks[k],tmp/('direct-'+k),out/('direct-'+k));save(out/'direct.json',direct);print('ordinary native',k,direct[k],flush=True)
    # Compile one rmake executable with the unmodified pinned real support crate, then pass each actual role through its standard compiletest environment.
    host=tmp/'driver';(host/'src').mkdir(parents=True);shutil.copyfile(HERE/'fixture/rmake.rs',host/'src/main.rs');(host/'Cargo.toml').write_text('[package]\nname = "placed-object-rmake"\nversion = "0.0.0"\nedition = "2024"\n[workspace]\n[dependencies]\nrun_make_support = { path = '+json.dumps(str(rust/'src/tools/run-make-support'))+' }\n');env=dict(os.environ,RUSTC=str(sdks['C']/'bin/rustc'),RUSTC_BOOTSTRAP='1',LD_LIBRARY_PATH=str(sdks['C']/'lib'),CARGO_TARGET_DIR=str(tmp/'driver-target'),CARGO_INCREMENTAL='0',CARGO_PROFILE_DEV_DEBUG='0');
    for key in ('RUSTFLAGS','RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST','CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST'):env.pop(key,None)
    assert H((HERE/'driver.Cargo.lock').read_bytes())==enroll['qualified_driver_lock'];shutil.copyfile(HERE/'driver.Cargo.lock',host/'Cargo.lock');shutil.copyfile(host/'Cargo.lock',out/'Cargo.lock');subprocess.run(['cargo','+stable','build','--locked','--jobs','4'],cwd=host,env=env,check=True,timeout=480);driver=tmp/'driver-target/debug/placed-object-rmake';binding={'factory':qualified['factory_run'],'factory_artifact':qualified['archive'],'cargo_lock':H((out/'Cargo.lock').read_bytes()),'rmake_driver':H(driver.read_bytes()),'roles':ROLE,'source':enroll,'commit':git(ROOT,'rev-parse','HEAD'),'host':HOST,'no_performance_measurements':True};save(out/'registered.json',binding);res={}
    for k in ('P','C'):
        dest=out/k;dest.mkdir();r,stderr=execute(ROLE[k],tmp/('case-'+k),dest,driver,sdks[k]);res[k]=(r['rc'],b'the source shift should rewrite the native object'in stderr);print(k,res[k],stderr[-1200:].decode(errors='replace'),flush=True)
    assert direct['C']['has_positive'] and not direct['P']['has_positive'] and all(x[k]for x in direct.values()for k in('source_changed_object','moved_object_matches_clean','moved_elf_matches_clean','observable_move_declined','invalid_e0308')),direct;assert res['P']==(101,True) and res['C']==(0,False),res;save(out/'terminal.json',{'actual':res,'positive_path':True,'semantic_and_invalid_then_repair':True,'ordinary_parent_only_failed_positive_activation':True,'registered':H((out/'registered.json').read_bytes())})
if __name__=='__main__':main()
