"""Build ordinarily through the pinned and fixed readers, including a poisoned same-path migration."""
import argparse
import contextlib
import gzip
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tomllib

sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import *
import fixture as f
import observe as obs
from sdk import reopen

def switch(kit,role,sdk,receipt):
    donor=kit/'roles'/role/'cargo';dest=sdk/'bin/cargo'
    require(sha(donor)==receipt['cargos'][role]['sha256'],'provenance before install')
    if not dest.samefile(donor):
        pending=dest.with_name('cargo-qa-next');require(not pending.exists(),pending)
        os.link(donor,pending);os.replace(pending,dest)
    require(dest.samefile(donor) and sha(dest)==receipt['cargos'][role]['sha256'],'same-path install')
    return ident(dest)

def snapshot(roots,metadata_only=False):
    result={}
    for root in roots:
        for p in [root,*sorted(root.rglob('*'))]:
            s=p.lstat();key=str(p)
            values=[s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_nlink]
            if p.is_symlink():values.append(os.readlink(p))
            elif p.is_file() and (not metadata_only or p.name.startswith('dep-') or p.suffix=='.d' or p.name==f.APP):values.append(sha(p))
            result[key]=values
    return result

def store_snapshot(path,values):
    with path.open('xb') as out:out.write(gzip.compress(json.dumps(values,sort_keys=True).encode(),compresslevel=2,mtime=0))

def source_shape(src,kind,seed_dir,work,env):
    cmd=['cargo','+ohm','fetch','--locked','--target',host()]
    subprocess.run(cmd,cwd=src,env=env,check=True)
    locked=tomllib.loads((src/'Cargo.lock').read_text())['package'];out={}
    for pkg in locked:
        if not pkg.get('source'):continue
        name=pkg['name'];v=pkg['version'];pkgdir=name+'-'+v
        ar,=list((work/'registry/registry/cache').glob('*/'+pkgdir+'.crate'));require(sha(ar)==pkg['checksum'],('source digest',name))
        chosen=['src/lib.rs']
        if name=='objc2':chosen.append('src/rc/retained.rs')
        with tarfile.open(ar,'r:gz') as tf:
            proof={n:tf.extractfile(pkgdir+'/'+n).read() for n in chosen}
        if name=='zmij':
            require(b'/*{0}*/' in proof['src/lib.rs'] and b'/*{:v}*/' in proof['src/lib.rs'],'wrong locked register barriers')
        if name=='objc2':require(b'asm!("mov fp, fp", options(nomem, preserves_flags, nostack))' in proof['src/rc/retained.rs'],'wrong frame-pointer instruction')
        out[name]={'archive':sha(ar),'version':v,'sources':{k:hashlib.sha256(b).hexdigest() for k,b in proof.items()}}
    # The seed contains only package downloads and index data, never compiled or package-cache state.
    seed_dir.mkdir();registry=seed_dir/'registry';registry.mkdir()
    for part in ('index','cache'):
        source=work/'registry/registry'/part
        require(source.is_dir(),source);shutil.copytree(source,registry/part,symlinks=False)
    require(set(out)==({kind} if kind=='zmij' else {kind,'objc2-encode'}),'foreign crate closure');return out

class Views:
    def __init__(self,work,case,seed):
        self.work=work;self.case=case;self.seed=seed;self.names=('target','shared','registry');self.force=case/'forced-store';self.force.mkdir()
        for n in self.names:
            if n=='registry':shutil.copytree(seed,self.force/n)
            else:(self.force/n).mkdir()
    @contextlib.contextmanager
    def use(self,mode,phase):
        if mode=='warm':yield;return
        root=self.work;hold=self.case/('parked-'+phase+'-'+mode);hold.mkdir()
        for n in self.names:(root/n).rename(hold/n)
        if mode=='force':
            for n in self.names:(self.force/n).rename(root/n)
        else:
            for n in self.names:
                if n=='registry':shutil.copytree(self.seed,root/n)
                else:(root/n).mkdir()
        ok=False
        try:yield;ok=True
        finally:
            for n in self.names:
                if mode=='force':(root/n).rename(self.force/n)
                elif ok:shutil.rmtree(root/n)
                else:(root/n).rename(self.case/('rejected-'+phase+'-'+n))
                (hold/n).rename(root/n)
            hold.rmdir()

def clean_root(src,e,out):
    cmd=['cargo','+ohm','clean','--offline','-p',f.APP]
    result=subprocess.run(cmd,cwd=src,env=e,capture_output=True)
    save(out,{'cmd':cmd,'code':result.returncode,'stdout':result.stdout.decode(),'stderr':result.stderr.decode()})
    require(result.returncode==0,'could not force consumer rebuild')

def equal_image(a,b):
    if a['code'] or b['code']:return a['code']==b['code'] and a['value']==b['value']==None
    if host()==APPLE:return obs.cgu.agrees(a['xcode_cgu'],b['xcode_cgu']) and a['value']==b['value']
    return a['image']==b['image'] and a['value']==b['value']

def control(row,state,val):
    if state=='source-invalid':
        require(row['code']==101 and 'E0308' in row['diagnostic_codes'] and row['final'] is None,'lost real Rust type error')
    elif val is None:
        require(row['code']==101 and row['final'] is not None and row['native_error'],'missing native failure')
    else:require(row['code']==0 and row['value']==val and row['image'],'incorrect executable')

def run_case(root,kit,receipt,kind,history,observer):
    sdk=kit/'sdk';case=root/'cases'/(kind+'-'+history);case.mkdir(parents=True)
    work=case/'work';work.mkdir();src=case/'src';r=root/'receipts'/(kind+'-'+history);r.mkdir()
    before_role='fourfix' if history=='fixed' else 'pinned'
    switch(kit,before_role,sdk,receipt);env=context(work,sdk)
    rust=run(['rustc','+ohm','-vV'],env=env);driver=kit/receipt['rust']['driver_path'];rid=ident(sdk/'bin/rustc');did=ident(driver)
    require(rust==receipt['rust']['version_verbose'],'different rustc')
    manifest=seed('ruff')/'Cargo.lock';source=f.project(src,kind,manifest)
    build_rs=(src/'build.rs').read_bytes();initial=(src/'src/main.rs').read_text()
    decl=f.providers(case/'native',r)
    registry=source_shape(src,kind,case/'registry-seed',work,env)
    save(r/'source.json',{'ruff':RUFF,'full_lock_sha256':sha(manifest),'fixture':source,'registry':registry,'environment':env,'initial_rustc':rid,'initial_driver':did})
    for n in ('target','shared'):(work/n).mkdir(exist_ok=True)
    views=Views(work,case,case/'registry-seed');previous={v:{} for v in ('warm','force','empty')};last=None
    if history=='migration':
        plan=[('old-lower','low',17),('old-higher','high29',29),('upgrade','high29',29),*f.STEPS[2:]]
    else:plan=[f.STEPS[0],('repeat-lower','low',17),*f.STEPS[1:]]
    results={};divergences=[]
    for label,state,val in plan:
        require(shutil.disk_usage(root).free>=4*2**30,'provider evidence volume reserve')
        provider=f.configure(case/'native',decl,state)
        new=initial.replace(f.INITIAL,f.BAD) if state=='source-invalid' else initial
        if (src/'src/main.rs').read_text()!=new:(src/'src/main.rs').write_text(new)
        require((src/'build.rs').read_bytes()==build_rs and sha(src/'Cargo.lock')==source['Cargo.lock'],'fixture/watch changed')
        role=('fourfix' if history=='fixed' or (history=='migration' and not label.startswith('old-')) else 'pinned')
        path=r/label;path.mkdir()
        if label=='upgrade':
            paths=[src,case/'native',work/'target',work/'shared']
            before=snapshot(paths);proof_before=ident(sdk/'bin/cargo');held=last['warm']
            require(held['role']=='pinned' and held['registry'][kind]['record']['LNK1']==(None if kind=='zmij' else obs.evidence.V2),'missing genuine previously translated record')
            new_cargo=switch(kit,role,sdk,receipt);after=snapshot(paths)
            require(before==after and proof_before['path']==new_cargo['path'] and new_cargo['sha256']!=proof_before['sha256'],'install touched warm tree')
            store_snapshot(path/'unmodified-state.json.gz',before)
            save(path/'same-path.json',{'old':proof_before,'new':new_cargo,'entries':len(before),'old_raw':held['registry'][kind]['raw'],'old_translated':held['registry'][kind]['record'],'old_image':held['image']})
        require(run(['cargo','+ohm','-Vv'],env=env)==receipt['cargos'][role]['version_verbose'] and run(['rustc','+ohm','-vV'],env=env)==rust and ident(driver)==did and ident(sdk/'bin/rustc')==rid,'wrong reader/runtime during visit')
        visits={}
        for mode in ('warm','force','empty'):
            with views.use(mode,label):
                if mode=='force':clean_root(src,env,path/'force-trigger.json')
                row=obs.visit(path/mode,root,work,src,sdk,env,role,kind,receipt,observer,previous[mode]);visits[mode]=row
                source_record=row['registry'][kind]
                require(source_record['source']['sha256']==registry[kind]['sources']['src/lib.rs'],'different real registry source')
                if mode!='warm':
                    control(row,state,val)
                    if state!='source-invalid':require(row['final'] is not None,'independent/forced native link absent')
                    require(any(q['crate']==f.APP for q in row['rustc']),'control did not invoke compiler for consumer')
        warm,forced,empty=(visits[k] for k in ('warm','force','empty'))
        require(equal_image(forced,empty),('forced/empty mismatch',label))
        agrees=equal_image(warm,empty)
        if role=='fourfix' or kind=='objc2' or label in ('lower','old-lower','repeat-lower','rust-error','rust-repair'):
            control(warm,state,val);require(agrees,('warm diverges from empty',kind,role,label))
            if label in ('appearance','same-stat','malformed','repair','removal','missing','restore','upgrade'):
                # After repair the last eligible output is different; an actual native invocation must observe each transition.
                require(warm['final'] is not None,('unobserved real provider transition',kind,role,label))
        elif not agrees:divergences.append(label)
        if role=='pinned' and kind=='zmij' and label in ('appearance','old-higher','same-stat','malformed'):
            require(not agrees and warm['value']==17 and warm['code']==0 and warm['final'] is None,('baseline did not reproduce original-marker bug',label))
        if label=='upgrade':
            require(any(i['crate']==kind for i in warm['rustc']),'old translated record reused without producer refresh')
            require(warm['registry'][kind]['record']['LNK1']==warm['raw_mark'],'fixed reader did not record active native marker')
        compared={'label':label,'state':state,'expected':val,'reader':role,'provider':provider,'warm_equals_empty':agrees,
                  'forced_equals_empty':True,'visits':{k:{s:q[s] for s in ('code','value','image','raw_mark','translated_mark','diagnostic_codes','all_physical_linkers')}|{'final_links':int(q['final'] is not None),'rustc':[x['crate'] for x in q['rustc']]} for k,q in visits.items()}}
        save(path/'comparison.json',compared);results[label]=compared;last=visits
    if kind=='zmij' and history=='baseline':require({'appearance','same-stat','malformed'}<=set(divergences),'no causal negative')
    terminal={'history':history,'producer':kind,'case_count':len(plan),'ordinary_commands':3*len(plan),'baseline_divergences':divergences,'phases':results}
    save(r/'complete.json',terminal);print(kind,history,len(plan),divergences,flush=True);return terminal

def execute(root,bundle):
    root.mkdir();kit=root/'kit';receipt=reopen(bundle,kit);obs.import_helpers()
    require(receipt['qa']['GITHUB_SHA']==os.environ['GITHUB_SHA'] and receipt['qa']['GITHUB_RUN_ID']==os.environ['GITHUB_RUN_ID'] and receipt['qa']['GITHUB_RUN_ATTEMPT']==os.environ['GITHUB_RUN_ATTEMPT'] and receipt['qa']['GITHUB_JOB']=='sdk','wrong source build')
    r=root/'receipts';(r/'cas').mkdir(parents=True);save(r/'release.json',receipt)
    observer=obs.Native(root);reports={}
    try:
        for kind in (('zmij','objc2') if host()==APPLE else ('zmij',)):
            for history in ('baseline','fixed','migration'):
                try:
                    s=run_case(root,kit,receipt,kind,history,observer);reports[kind+'-'+history]={k:s[k] for k in ('case_count','ordinary_commands','baseline_divergences')}
                except Exception as error:
                    import traceback
                    reports[kind+'-'+history]={'refused':str(error),'traceback':traceback.format_exc()}
                    save(r/(kind+'-'+history+'-refused.json'),reports[kind+'-'+history]);print(reports[kind+'-'+history]['traceback'],flush=True)
                    if shutil.disk_usage(root).free<4*2**30:raise
    finally:observer.close()
    require(all('refused' not in s for s in reports.values()),('incomplete source validation',reports))
    total=sum(s['ordinary_commands'] for s in reports.values());save(r/'complete.json',{'qa':job(),'host':host(),'cases':reports,'ordinary_commands':total,'source_job':receipt['qa'],'kit':receipt['kit_sha256']})
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('root',type=Path);a.add_argument('bundle',type=Path);x=a.parse_args();execute(x.root.resolve(),x.bundle.resolve())
