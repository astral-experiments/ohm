"""Ordinary GNU provider behavior using the already-qualified native SDK. No tracer or counter."""
import argparse
import gzip
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import campaign as pre
import fixture as f
import observe as ob
from common import *
from sdk import reopen

def marker(row, work, store):
    """Only accept the active registry artifact Cargo reported inside this visit's isolated roots."""
    name=row['target']['name']; rlib,=[Path(n) for n in row['filenames'] if n.endswith('.rlib')]
    base=rlib.parent; unit=base.parent
    require(base.name=='out' and rlib.is_file() and any(unit.resolve().is_relative_to(work/n) for n in ('target','shared')),'foreign unit')
    raw=rlib.with_name(rlib.name[3:-5]+'.d'); record=unit/'fingerprint'/('dep-lib-'+name)
    require(raw.is_file() and record.is_file() and not raw.is_symlink() and not record.is_symlink(),'missing active producer records')
    a,b=raw.read_bytes(),record.read_bytes()
    return {'package':row['package_id'],'fresh':row['fresh'],'source':ident(Path(row['target']['src_path'])),
            'rlib':ident(rlib),'raw_path':str(raw),'record_path':str(record),'raw':ob.keep(store,a),'translated':ob.keep(store,b),
            'rules':ob.evidence.raw_rule(raw,a),'LNK1':ob.evidence.encoded(b)['LNK1'],'markers':ob.evidence.encoded(b)['markers']}

def visit(out,work,src,env,store,role,kind):
    out.mkdir(parents=True)
    cmd=['cargo','+ohm','build','--locked','--offline','-j4','--message-format=json']
    p=subprocess.run(cmd,env=env,cwd=src,capture_output=True,timeout=360)
    for name,data in [('stdout',p.stdout),('stderr',p.stderr)]:
        (out/(name+'.gz')).write_bytes(gzip.compress(data,mtime=0))
    typed=[json.loads(s) for s in p.stdout.splitlines() if s.strip()]
    require(p.returncode in (0,101) and typed[-1]=={'reason':'build-finished','success':p.returncode==0},'ordinary Cargo verdict')
    units={}; app=None; script=None
    for row in typed:
        if row['reason']=='build-script-executed' and row['package_id'].endswith('#'+f.APP+'@0.1.0'):
            require(script is None,'duplicate build script');script=row
        if row['reason']!='compiler-artifact': continue
        if row['package_id'].startswith('registry+') and row['target']['kind']==['lib']:
            n=row['target']['name'];require(n not in units,'duplicate compiled registry unit');units[n]=marker(row,work,store)
        if row['target']['name']==f.APP and row['target']['kind']==['bin']:
            require(app is None,'multiple terminal apps');app=row
    names={kind} if kind=='zmij' else {kind,'objc2_encode'}
    require(set(units)==names and units[kind]['package'].endswith('#'+kind+'@'+LOCKED[kind][0]),'wrong registry closure')
    require(all(Path(v['source']['path']).is_relative_to(work/'registry/registry/src') for v in units.values()),'foreign registry')
    expected=ob.evidence.V1 if kind=='zmij' else ob.evidence.V2
    enc=None if role=='pinned' and kind=='zmij' else expected
    require(units[kind]['rules']==[expected] and units[kind]['LNK1']==enc and units[kind]['markers']==([enc] if enc else []),'active marker mismatch')
    require(all(v['rules']==[] and v['LNK1'] is None for n,v in units.items() if n!=kind),'competing marker')
    dirs=['native='+str(src.parent/'native'/d) for d in ('early','late')]
    require(script['linked_paths']==dirs and not script['linked_libs'],'native search order')
    directives=(Path(script['out_dir']).parent/'run/stdout').read_bytes()
    require(directives.decode().splitlines()==['cargo:rustc-link-search='+d for d in dirs]+['cargo:rerun-if-changed=build.rs'],'unexpected watched input')
    value=image=None
    if p.returncode==0:
        exe=Path(app['executable']);require(exe.resolve().is_relative_to(work/'target'),'foreign returned executable')
        b=exe.read_bytes();image=ob.keep(store,b)
        require(b[:4]==(b'\x7fELF' if host()==GNU else bytes.fromhex('cffaedfe')),'wrong native file kind')
        result=subprocess.run([exe],capture_output=True,env=env,cwd=src,timeout=8)
        values={n:f'OHM_RC22_SELECTED_NATIVE_IMAGE_{n}'.encode() for n in (17,29,41)}
        value=next((n for n,tag in values.items() if result.stdout==str(n).encode()+b' '+tag+b'\n'),None)
        require(result.returncode==0 and not result.stderr and value is not None and all((tag+b'\0' in b)==(n==value) for n,tag in values.items()),'executable bytes and behavior disagree')
        save(out/'runtime.json',{'code':result.returncode,'stdout':result.stdout.decode(),'elf':image})
    diagnostics=[r['message']['code']['code'] for r in typed if r['reason']=='compiler-message' and r['message'].get('code')]
    errors=(p.stdout+b'\n'+p.stderr).decode(errors='replace')
    row={'code':p.returncode,'value':value,'image':image,'app_fresh':None if app is None else app['fresh'],'units':units,
         'native_error':f.LIB in errors or 'qa_rc22_value' in errors,'diagnostics':diagnostics,
         'watch_stdout':ob.keep(store,directives),'command':cmd,'mode':'ordinary-no-process-instrumentation'}
    save(out/'observed.json',row);return row

def verdict(row,state,value):
    if state=='source-invalid':
        require(row['code']==101 and 'E0308' in row['diagnostics'] and row['image'] is None,'missed Rust error')
    elif value is None:
        require(row['code']==101 and row['native_error'] and row['image'] is None,'missed native failure')
    else:
        require(row['code']==0 and row['value']==value and row['image'],'incorrect native executable')

def case(root,kit,receipt,kind,history,cache=None):
    sdk=kit/'sdk';base=root/'cases'/(kind+'-'+history);base.mkdir(parents=True);work=base/'work';work.mkdir()
    out=root/'receipts'/(kind+'-'+history);out.mkdir();store=root/'receipts/cas'; src=base/'src'
    initial_role='fourfix' if history=='fixed' else 'pinned'
    current=pre.switch(kit,initial_role,sdk,receipt);env=context(work,sdk)
    rust=ident(sdk/'bin/rustc');driver=ident(kit/receipt['rust']['driver_path'])
    require(run(['rustc','+ohm','-vV'],env=env)==receipt['rust']['version_verbose'],'different Rust')
    lock=seed('ruff')/'Cargo.lock';source=f.project(src,kind,lock)
    original=(src/'src/main.rs').read_text(); bodies=f.providers(base/'native',out)
    if cache:
        require((cache/'registry').is_dir(),'registry-only seed missing')
        for part in ('cache','index'):
            shutil.copytree(cache/'registry'/part,work/'registry/registry'/part)
        env['CARGO_NET_OFFLINE']='true'
    registry=pre.source_shape(src,kind,base/'registry-seed',work,env)
    save(out/'source.json',{'ruff_revision':RUFF,'full_lock':sha(lock),'source':source,'registry':registry,'sdk':{'rustc':rust,'driver':driver},'cargo':current})
    for n in ('target','shared'):(work/n).mkdir(exist_ok=True)
    views=pre.Views(work,base,base/'registry-seed');last=None;result={}
    if history=='migration':
        schedule=[('old-lower','low',17),('old-higher','high29',29),('upgrade','high29',29),*f.STEPS[2:]]
    else:schedule=[f.STEPS[0],('repeat-lower','low',17),*f.STEPS[1:]]
    for phase,state,v in schedule:
        proof=f.configure(base/'native',bodies,state);dest=out/phase;dest.mkdir()
        main=original.replace(f.INITIAL,f.BAD) if state=='source-invalid' else original
        if (src/'src/main.rs').read_text()!=main:(src/'src/main.rs').write_text(main)
        require(all(sha(src/n)==source[n] for n in ('Cargo.toml','Cargo.lock','build.rs')),'immutable fixture sources or lock changed')
        role='fourfix' if history=='fixed' or (history=='migration' and not phase.startswith('old-')) else 'pinned'
        if phase=='upgrade':
            paths=[src,base/'native',work/'target',work/'shared'];before=pre.snapshot(paths);old=current
            current=pre.switch(kit,role,sdk,receipt);require(before==pre.snapshot(paths) and old['path']==current['path'] and old['sha256']!=current['sha256'],'upgrade touched warm tree')
            pre.store_snapshot(dest/'pre-existing-tree.json.gz',before)
            save(dest/'same-path.json',{'old':old,'new':current,'previous_unit':last['units'][kind],'old_image':last['image'],'entries':len(before)})
        require(ident(sdk/'bin/rustc')==rust and ident(kit/receipt['rust']['driver_path'])==driver and run(['cargo','+ohm','-Vv'],env=env)==receipt['cargos'][role]['version_verbose'],'wrong physical reader/driver')
        replies={}
        for mode in ('warm','force','empty'):
            with views.use(mode,phase):
                if mode=='force':pre.clean_root(src,env,dest/'force-trigger.json')
                reply=visit(dest/mode,work,src,env,store,role,kind);replies[mode]=reply
                require(reply['units'][kind]['source']['sha256']==registry[kind]['sources']['src/lib.rs'],'different actual registry producer')
                if mode!='warm':
                    verdict(reply,state,v)
                    if v is not None:require(reply['app_fresh'] is False,'forced/empty did not build consumer')
        warm,forced,empty=(replies[n] for n in ('warm','force','empty'))
        def key(r):return (r['code'],r['value'],r['image'],tuple(r['diagnostics']))
        require(key(forced)==key(empty),('complete forced/empty divergence',phase))
        equal=key(warm)==key(empty)
        if role=='fourfix' or kind=='objc2' or phase in ('lower','old-lower','repeat-lower','rust-error','rust-repair'):
            verdict(warm,state,v);require(equal,('warm differs from clean',phase))
        if role=='pinned' and kind=='zmij' and phase in ('appearance','old-higher','same-stat','malformed'):
            require(not equal and warm['value']==17 and warm['code']==0,'original failure not reproduced')
        if phase=='upgrade':
            require(not warm['units'][kind]['fresh'] and warm['units'][kind]['LNK1']==warm['units'][kind]['rules'][0],'no refreshed authenticated producer record')
        record={'phase':phase,'provider':proof,'reader':role,'expected':v,'warm_equals_empty':equal,
                'visits':{l:{k:r[k] for k in ('code','value','image','diagnostics','app_fresh')} for l,r in replies.items()}}
        save(dest/'comparison.json',record);result[phase]=record;last=warm
    save(out/'complete.json',{'scope':'untraced behavior and complete program bytes','visits':3*len(result),'phases':result})
    return 3*len(result)


def execute(root,bundle,expected,cache=None):
    root.mkdir();kit=root/'kit';receipt=reopen(bundle,kit)
    sys.path.insert(0,str(seed('marker-reader')/'scripts/ohm-musl-ast-pair/v2'))
    import evidence
    ob.evidence=evidence
    require(receipt['qa']=={'GITHUB_JOB':'sdk','GITHUB_REPOSITORY':'astral-experiments/ohm','GITHUB_RUN_ATTEMPT':'1','GITHUB_RUN_ID':str(expected['run']),'GITHUB_SHA':expected['head']},'wrong native source build')
    require(sha(bundle/'kit.tar.zst')==expected['kit'] and sha(bundle/'members.json')==expected['members'] and sha(bundle/'receipt.json')==expected['receipt'],'wrong restored official SDK')
    r=root/'receipts';(r/'cas').mkdir(parents=True);save(r/'source-release.json',receipt);save(r/'original.json',expected)
    reports={}
    for kind in (('zmij','objc2') if host()==APPLE else ('zmij',)):
        for history in ('baseline','fixed','migration'):
            try:reports[kind+'-'+history]=case(root,kit,receipt,kind,history,cache)
            except Exception:
                import traceback
                reports[kind+'-'+history]=traceback.format_exc()
                save(r/(kind+'-'+history+'-refused.json'),{'traceback':reports[kind+'-'+history]})
                print(reports[kind+'-'+history],flush=True)
    save(r/'account.json',reports)
    require(all(type(n) is int and n==33 for n in reports.values()),'incomplete, see raw refusal')
    save(r/'complete.json',{'visits':sum(reports.values()),'cases':reports,'host':host(),'literal_command':['cargo','+ohm','build','--locked','--offline','-j4','--message-format=json'],'native_launch_count':None,'kit':expected['kit']})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('bundle',type=Path);p.add_argument('expected',type=Path);p.add_argument('--offline-registry',type=Path)
    a=p.parse_args();execute(a.root.resolve(),a.bundle.resolve(),read(a.expected),a.offline_registry)

