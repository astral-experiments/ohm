"""Migrate real, already-accepted stale diagnostics across an actual, same-path Cargo upgrade."""
import gzip
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'cargo-diagnostic-fix'))
import qualification as q
m=q.m;probe=q.probe
SDK=lambda:m.R/'sdk-U'
names={'signed':'2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c','fixed':q.materialize.BASE}
def init_sdk():
    std=m.R/'sdk-21';sdk=SDK()
    if not sdk.exists():
        sdk.mkdir();(sdk/'bin').mkdir()
        for f in std.iterdir():
            if f.name!='bin':(sdk/f.name).symlink_to(f,target_is_directory=f.is_dir())
        for f in (std/'bin').iterdir():
            if f.name!='cargo':(sdk/'bin'/f.name).symlink_to(f,target_is_directory=f.is_dir())
def install(role,env):
    std=m.R/'sdk-21';sdk=SDK()
    src=std/'bin/cargo' if role=='signed' else m.R/'sdk-C/bin/cargo'
    dst=sdk/'bin/cargo';temp=sdk/'bin/new-cargo'
    assert not temp.exists();shutil.copyfile(src,temp);temp.chmod(0o755);os.replace(temp,dst)
    ver=m.get(['cargo','+ohm','-Vv'],env=env).decode()
    head=(q.materialize.BASE if role=='signed' else json.loads((q.HERE/'spec.json').read_bytes())['head'])
    assert 'commit-hash: '+head in ver and m.sha(dst)==m.sha(src)
    st=lambda p:(p.stat().st_dev,p.stat().st_ino,p.stat().st_ctime_ns)
    rust=sdk/'bin/rustc';driver,=(sdk/'lib').glob('librustc_driver*.so')
    return {'cargo':q.item_stat(dst),'version':ver,'rustc':st(rust),'driver':st(driver),'driver_sha':m.sha(driver),
            'alias':str((Path(env['RUSTUP_HOME'])/'toolchains/ohm').resolve(strict=True))}
def usage(stage):
    e=m.w.environment(m.R,'U',m.R/stage)
    e['CARGO_HOME']=m.read(m.O/'subjects.json')['environment']['CARGO_HOME']
    e['CARGO_LOG']='cargo::compiler=info,cargo::compiler::fingerprint=debug'
    return e
def typed(role,label):
    root=m.O/role/label
    msgs=[json.loads(l) for l in gzip.decompress((root/'stdout.gz').read_bytes()).splitlines()]
    return [r['message'] for r in msgs if r['reason']=='compiler-message']
def valid_notice(msgs):
    return any((m.get('code') or {}).get('code')=='deprecated' and 'OHM_QA_PRESERVED_WARNING' in m['message'] for m in msgs)
def old_error(msgs,variant='OHM_RON_CHECK_BAD_TYPE'):
    errors=[t for t in msgs if t['level']=='error']
    return len(errors)==1 and errors[0]['code']['code']=='E0308' and any(variant in line['text'] for s in errors[0]['spans'] if s['is_primary'] for line in s['text'])
def assert_swap(before,after):
    assert before['cargo']['path']==after['cargo']['path'] and before['cargo']['sha256']!=after['cargo']['sha256']
    for key in ('driver','driver_sha','rustc','alias'):assert before[key]==after[key]
def choose(r,point,name):
    matches=[(k,v) for k,v in r[point]['cache'].items() if Path(k).name==name]
    assert len(matches)==1,(r['label'],name,len(matches))
    return matches[0]
def ruff():
    role='ruff-migration';env=usage('upgrade-ruff');baseline=m.cmd[:-1]
    e_off=usage('upgrade-ruff-defaults-off');off=baseline[:2]+['-Zohm-defaults=no']+baseline[2:]
    valid=m.w.git(m.src,'show','HEAD:'+probe.SOURCE);file=m.src/probe.SOURCE
    assert file.read_bytes()==valid
    m.w.git(m.src,'restore','--source=HEAD','--worktree','--',m.changed)
    old=install('signed',env);m.save(m.O/role/'old-runtime.json',old)
    def visit(n,e=env,cmd=baseline,mode='physical',style='json'):
        return probe.execute(role,n,e,'U',cmd,observer=mode,style=style)
    def has(owner,rec):return owner in [v[1] for v in rec['physical_rustcs']]
    def settled(rec,want):assert [v[1] for v in rec['physical_rustcs']]==want,(rec['label'],rec['physical_rustcs'])
    try:
        assert visit('old-ordinary-train',mode='plain')['exit']==0
        probe.reverse_history()
        assert visit('old-real-edit')['exit']==0
        file.write_bytes(valid+q.WARN)
        assert visit('old-valid-warning')['exit']==0 and valid_notice(typed(role,'old-valid-warning'))
        settled(visit('old-warning-repeat'),['ron'])
        # The failed source deliberately removes the warning. A valid repair must
        # restore a real warning, not just suppress the error in the old file.
        file.write_bytes(valid+probe.BAD)
        assert visit('old-invalid')['exit']==101 and old_error(typed(role,'old-invalid')) and not valid_notice(typed(role,'old-invalid'))
        file.write_bytes(valid+q.WARN)
        poison=visit('old-poisoned-repair');settled(poison,['ron'])
        assert poison['exit']==0 and old_error(typed(role,'old-poisoned-repair')) and not valid_notice(typed(role,'old-poisoned-repair'))
        settled(visit('old-already-poisoned-json'),['ron']);settled(visit('old-already-poisoned-human',style='human'),['ron'])
        json_old=typed(role,'old-already-poisoned-json')
        assert old_error(json_old) and not valid_notice(json_old)
        human=gzip.decompress((m.O/role/'old-already-poisoned-human/stderr.gz').read_bytes())
        assert b'error[E0308]' in human and b'OHM_QA_PRESERVED_WARNING' not in human
        snapshot={k:choose(poison,'after',k) for k in ('test-lib-ty_project','test-lib-ty_project.json','output-test-lib-ty_project')}
        assert snapshot['test-lib-ty_project'][1]['size']==16
        assert visit('off-old-empty',e_off,off,'plain')['exit']==0 and valid_notice(typed(role,'off-old-empty'))
        offbefore=visit('off-old-idle',e_off,off);settled(offbefore,[])
        m.save(m.O/role/'signed-before-swap.json',{'source':probe.source(),'cache':probe.cache(env),'active':snapshot,'off_cache':probe.cache(e_off)})
        new=install('fixed',env);assert_swap(old,new);m.save(m.O/role/'new-runtime.json',new)
        before=m.read(m.O/role/'signed-before-swap.json')
        assert before['source']==probe.source() and before['cache']==probe.cache(env) and before['off_cache']==probe.cache(e_off)
        change=visit('upgraded-first')
        assert change['exit']==0 and has('ty_project',change) and not old_error(typed(role,'upgraded-first')) and valid_notice(typed(role,'upgraded-first'))
        assert not [x for x in typed(role,'upgraded-first') if x['level']=='error'] and change['before']['cache']==before['cache']
        settled(visit('upgraded-settled-json'),['ron'])
        assert valid_notice(typed(role,'upgraded-settled-json')) and not old_error(typed(role,'upgraded-settled-json'))
        settled(visit('upgraded-settled-human',style='human'),['ron'])
        human=gzip.decompress((m.O/role/'upgraded-settled-human/stderr.gz').read_bytes())
        assert b'error[E0308]' not in human and b'OHM_QA_PRESERVED_WARNING' in human
        offafter=visit('off-new-idle',e_off,off);settled(offafter,[])
        assert valid_notice(typed(role,'off-new-idle')) and not old_error(typed(role,'off-new-idle'))
        # Force this one private unit by removing its required physical output,
        # retaining the exact original bytes in the temporary worker.
        name,info=change['ty_artifacts'][0][1][0];out=Path(name);assert out.resolve().is_relative_to(Path(env['CARGO_TARGET_DIR'])) and q.item_stat(out)['sha256']==info['sha']
        held=m.R/'held-ruff-root-metadata';assert not held.exists();out.rename(held)
        forced=visit('fixed-forced-missing-root')
        assert forced['exit']==0 and has('ty_project',forced) and valid_notice(typed(role,'fixed-forced-missing-root'))
        empty=usage('upgrade-ruff-fixed-empty')
        assert visit('fixed-independent-empty',empty,baseline,'plain')['exit']==0 and valid_notice(typed(role,'fixed-independent-empty'))
        real=change['ty_artifacts'][0][1][0][0]
        active=Path(real).parent.parent/'fingerprint'
        after={k:v for k,v in change['after']['cache'].items() if Path(k).parent==active}
        m.save(m.O/role/'terminal.json',{'visits':18,'same_source_target_and_runtime':True,
            'original_complete_markers':snapshot,'new_active_cache':after,'same_fingerprint_directory':active==Path(snapshot['test-lib-ty_project'][0]).parent,
            'one_time_physical_units':[r[1] for r in change['physical_rustcs']],'defaults_off_after':offafter['physical_rustcs'],'forced':forced['physical_rustcs']})
    finally:file.write_bytes(valid)

def tiny():
    lane='fully-fresh-migration';env=usage('upgrade-tiny');place=m.R/'two-local-crates';place.mkdir();(place/'src').mkdir();(place/'dep/src').mkdir(parents=True)
    (place/'Cargo.toml').write_text('[package]\nname="app"\nversion="0.1.0"\nedition="2024"\n[dependencies]\ndep={path="dep"}\n')
    (place/'dep/Cargo.toml').write_text('[package]\nname="dep"\nversion="0.1.0"\nedition="2024"\n')
    app=place/'src/lib.rs';dep=place/'dep/src/lib.rs'
    base=b'pub fn value() -> u32 { dep::value() }\n';valid=base+q.WARN
    app.write_bytes(valid);dep.write_text('pub fn value()->u32 { inner() }\nfn inner()->u32 { 1 }\n')
    old=install('signed',env);m.save(m.O/lane/'old-runtime.json',old)
    m.run(['cargo','+ohm','generate-lockfile','--offline'],cwd=place,env=env)
    cmd=['cargo','+ohm','check','--tests','--locked','--offline','-j1','--message-format=json']
    def visit(label):
        root=m.O/lane/label;sources={str(f.relative_to(place)):probe.details(f) for f in (app,dep)}
        p,_,events=m.observe(lane+'/'+label,SDK()/'bin/rustc','ron',cmd,env,place)
        rows=[json.loads(l) for l in p.stdout.splitlines()]
        assert rows[-1]=={'reason':'build-finished','success':p.returncode==0}
        owners=[]
        for pid,ident,_,exe,args in events:
            if '--crate-name' in args and '--out-dir' in args:
                assert ident==q.item_stat(SDK()/'bin/rustc')['ino'];owners.append(args[args.index('--crate-name')+1])
        fingerprints={}
        for file in Path(env['CARGO_TARGET_DIR']).rglob('*test-lib-app*'):
            if file.is_file() and file.name in ('test-lib-app','output-test-lib-app','test-lib-app.json'):
                b=file.read_bytes();fingerprints[str(file)]=[probe.details(file),b.decode()];assert len(b)<65000
        messages=[r['message'] for r in rows if r['reason']=='compiler-message']
        rec={'workers':owners,'exit':p.returncode,'source':sources,'before_runtime':q.item_stat(SDK()/'bin/cargo'),'cache':fingerprints,
             'warning':valid_notice(messages),'error':old_error(messages),'message_levels':[r['level'] for r in messages]}
        m.save(root/'receipt.json',rec);return rec
    def expect(r,code,workers,warning,error):assert [r[k] for k in ('exit','workers','warning','error')]==[code,workers,warning,error],(r['exit'],r['workers'],r['warning'],r['error'])
    expect(visit('old-valid'),0,['dep','app'],True,False)
    expect(visit('old-fresh'),0,[],True,False)
    app.write_bytes(base+probe.BAD);expect(visit('old-invalid'),101,['app'],False,True)
    app.write_bytes(valid);dep.write_text('pub fn value()->u32 { inner() }\nfn inner()->u32 { 2 }\n')
    expect(visit('old-poisoned-repair'),0,['dep'],False,True)
    prior=visit('old-fully-fresh-poison');expect(prior,0,[],False,True)
    sigs=[v for k,v in prior['cache'].items() if Path(k).name=='test-lib-app'];assert len(sigs)==1 and sigs[0][0]['size']==16
    new=install('fixed',env);assert_swap(old,new);m.save(m.O/lane/'new-runtime.json',new)
    r=visit('new-first');assert r['source']==prior['source'] and r['exit']==0 and 'app' in r['workers'] and r['warning'] and r['message_levels']==['warning']
    r2=visit('new-fully-fresh');expect(r2,0,[],True,False)
    m.save(m.O/lane/'terminal.json',{'old_fresh':prior['workers'],'new_first':r['workers'],'new_fresh':r2['workers'],'same_sources':True})

def main():
    assert (m.O/'fix-terminal.json').is_file()
    # Make the one alias exist before deriving environments that link to it.
    assert not SDK().exists()
    init_sdk()
    errors={}
    import traceback
    for label,fn in [('Ruff',ruff),('two_crates',tiny)]:
        try:fn()
        except Exception:
            errors[label]=traceback.format_exc()
            m.save(m.O/('upgrade-error-'+label+'.json'),{'error':errors[label]})
    m.save(m.O/'upgrade-terminal.json',{'errors':errors,'signed_to_final':True})
    if errors:raise RuntimeError(errors)
if __name__=='__main__':main()
