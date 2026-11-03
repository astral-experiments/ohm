from pathlib import Path
import hashlib, json, os, shutil, signal, subprocess, time

src = Path(__file__).resolve().parent
spec = json.loads((src/'plan.json').read_bytes())
def run(sdk, env, label, cmd, cwd):
    low=sdk.avail(); assert low>=9*2**30
    a,b=[sdk.proof/(label+x) for x in ('.stdout','.stderr')];start=time.monotonic()
    with a.open('wb') as so,b.open('wb') as se:
        p=subprocess.Popen(cmd,cwd=cwd,env=env,stdout=so,stderr=se,start_new_session=True)
        while p.poll() is None:
            low=min(low,sdk.avail())
            if low<8*2**30 or shutil.disk_usage(cwd).free<15*2**30 or time.monotonic()-start>2400:
                os.killpg(p.pid,signal.SIGKILL);p.wait();raise RuntimeError('resource or duration floor: '+label)
            time.sleep(.3)
    sdk.put(sdk.proof/(label+'.json'),{'argv':cmd,'rc':p.returncode,'low_memory':low})
    if p.returncode: print(b.read_text(errors='replace')[-4800:],flush=True);raise RuntimeError(label+' failed')
    return a
def setup(sdk,e):
    root=Path(os.environ['GITHUB_WORKSPACE'])/'cargo'; bundle=src/'candidate.bundle'
    git=lambda *args:subprocess.check_output(['git','-C',str(root),*args],text=True).strip()
    assert sdk.hf(bundle)==spec['bundle_sha256'] and git('rev-parse','HEAD')==spec['parent']
    git('fetch',str(bundle),'HEAD:refs/qa/input-recheck-candidate');git('switch','--detach',spec['candidate'])
    assert git('rev-parse','HEAD^')==spec['parent']and git('rev-parse','HEAD^{tree}')==spec['tree']and not git('status','--porcelain')
    target=sdk.root/'factory-target';shared=sdk.root/'factory-shared'
    env={**e,'RUSTUP_TOOLCHAIN':'ohm','CARGO_TARGET_DIR':str(target),'CARGO_BUILD_BUILD_DIR':str(shared),'CARGO_PROFILE_DEV_DEBUG':'0','CARGO_INCREMENTAL':'0'}
    a=run(sdk,env,'factory',['cargo','+ohm','-Zohm-defaults=no','build','--locked','-p','cargo','--bin','cargo','-j8','--message-format=json-render-diagnostics'],root)
    rows=[json.loads(l)for l in a.read_text().splitlines()if l.startswith('{')];exe,=[Path(r['executable'])for r in rows if r['reason']=='compiler-artifact' and r['target']['name']=='cargo'and r.get('executable') and 'bin'in r['target']['kind']]
    assert exe.is_file()and any(exe.resolve().is_relative_to(d)for d in (target,shared))
    version=subprocess.check_output([exe,'-Vv'],env=e,text=True)
    assert spec['candidate']in version,(version,spec)
    portable=sdk.proof/'candidate-cargo';shutil.copy2(exe,portable)
    sdk.put(sdk.proof/'factory-identity.json',{'source':spec['candidate'],'parent':spec['parent'],'tree':spec['tree'],'bin_sha256':sdk.hf(portable),'bin_bytes':portable.stat().st_size,'version':version,'rustc':subprocess.check_output(['rustc','+ohm','-vV'],env=e,text=True)})
    return portable,env,root
def suite(sdk,env,root):
    for n,s in enumerate(spec['regression_tests']):
        a=run(sdk,env,'cargo-tests-'+str(n),['cargo','+ohm','-Zohm-defaults=no','test','--locked','-p','cargo','-j8','--test','testsuite',s,'--','--test-threads=3'],root)
        data=a.read_text()
        assert 'test result: ok.'in data and '0 passed; 0 failed'not in data,(s,data[-1500:])
        if n==0:assert 'freshness::early_cutoff_rechecks_included_dependency_metadata ... ok'in data,data[-2500:]
