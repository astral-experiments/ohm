"""Accept the actual marked and compiled Ruff units with signed and matched release-profile Cargo."""
from pathlib import Path
import collections,hashlib,json,os,re,shutil,signal,subprocess,sys,time,traceback
src=Path(__file__).resolve().parent;sys.path[:0]=[str(src.parent/'fix'),str(src.parent.parent/'ruff-foreign-span-observer')]
import worker as sdk
import build
plan=json.loads((src/'plan.json').read_bytes());w=sdk.work;out=sdk.proof
git=lambda *args:subprocess.check_output(['git','-C',w,*args],text=True).strip()
assert git('rev-parse','HEAD')==plan['ruff_new']and git('rev-parse','HEAD^')==plan['ruff_old'] and sdk.hf(w/'Cargo.lock')==plan['ruff_lock'] and not git('status','--porcelain')
assert sdk.hf(src/'whole_count.c')==plan['counter']
sdk.put(out/'release-registration.json',{'plan':plan,'inputs':{p.name:sdk.hf(p)for p in src.iterdir()if p.is_file()},'kernel':os.uname().release})
e=sdk.install();bodies=build.setup(sdk,e,release=True)
trial=sdk.root/'ruff-comparison';trial.mkdir();tgt=trial/'target';shared=trial/'shared';box=trial/'sdk';(box/'bin').mkdir(parents=True)
for p in sdk.sdk.iterdir():
    if p.name!='bin':(box/p.name).symlink_to(p)
for p in (sdk.sdk/'bin').iterdir():
    if p.name!='cargo':(box/'bin'/p.name).symlink_to(p)
link=box/'bin/cargo';link.symlink_to(bodies['signed'])
ce={**e,'RUSTUP_HOME':str(trial/'rustup'),'CARGO_TARGET_DIR':str(tgt),'CARGO_BUILD_BUILD_DIR':str(shared)}
subprocess.run(['rustup','toolchain','link','ohm',box],check=True,env=ce)
assert not any(ce.get(k)for k in ('RUSTFLAGS','RUSTC','RUSTC_WRAPPER','LD_PRELOAD','CARGO_LOG','CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST','CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST'))
build.run(sdk,ce,'ruff-registry-prefetch',['cargo','+ohm','fetch','--locked','--target','x86_64-unknown-linux-gnu'],w)
counter=trial/'whole-count';subprocess.run(['cc','-O2','-Wall','-Werror',src/'whole_count.c','-o',counter],check=True)
cal=trial/'counter.json';physical=subprocess.run([counter,cal,'true','probe']).returncode==0
if physical:
    check=json.loads(cal.read_bytes());assert 0<check['instructions'] and check['running']>0 and check['enabled']<=check['running']*1.01
sdk.put(out/'counter.json',{'available':physical,'source':sdk.hf(src/'whole_count.c'),'executable':sdk.hf(counter),'control':json.loads(cal.read_bytes())if physical else None})
files=plan['additional_private'];changed=w/files['path'];git('switch','--detach',plan['ruff_old'])
def empty(label):
    for d in (tgt,shared):
        if d.exists():d.rename(trial/(label+'-'+d.name))
def md(label,d):
    ans={}
    for name in ('ruff_linter','ruff_graph','ruff_workspace','ty_python_semantic'):
        pats=['lib'+name+'-*.rmeta']
        found=[q for base in(tgt,shared)if base.exists()for pat in pats for q in base.rglob(pat)if q.is_file()]
        signatures={sdk.hf(q)for q in found};assert len(signatures)==1,(label,name,found,signatures)
        q=found[0];hdr=subprocess.check_output(['rustc','+ohm',q,'-Zls=root'],env=ce,text=True)
        (d/(name+'.root')).write_text(hdr)
        row={'sha256':signatures.pop(),'bytes':q.stat().st_size,'paths':list(map(str,found)),'public':re.search(r'public_hash (\w{32})',hdr)[1],'private':re.search(r'private hash (\w{32}) stable_crate_id',hdr)[1]}
        if name=='ruff_linter'and label not in ('old-unchanged','edit-unchanged','edit-unchanged-json','private-unchanged'):
            data=out/'rmeta';data.mkdir(exist_ok=True);f=data/(row['sha256']+'.zst')
            if not f.exists():subprocess.run(['zstd','-q','-3','-T1',q,'-o',f],check=True)
        ans[name]=row
    return ans
roles={};errors={};active=trial/'role-name'
for role in plan['role_order']:
    rec={};roles[role]=rec;subject=bodies[role];expected=plan['parent']if role in('signed','release-parent')else plan['child']
    def phase(label,wrong=False,json_mode=False):
        d=out/role/label;d.mkdir(parents=True);cmd=plan['primary']+(['--message-format=json']if json_mode else[])
        cost=d/'instructions.json';tr=d/'exec';argv=['strace','-ff','-qq','-s','8192','-e','trace=execve','-o',str(tr),'--']+([str(counter),str(cost)]if physical else[])+cmd
        started=time.monotonic();minimum=sdk.avail();assert minimum>=9*2**30 and shutil.disk_usage(w).free>20*2**30
        with (d/'stdout').open('wb')as so,(d/'stderr').open('wb')as se:
            proc=subprocess.Popen(argv,env=ce,cwd=w,stdout=so,stderr=se,start_new_session=True)
            while proc.poll()is None:
                minimum=min(minimum,sdk.avail())
                if minimum<8*2**30 or shutil.disk_usage(w).free<15*2**30 or time.monotonic()-started>1500:
                    os.killpg(proc.pid,signal.SIGKILL);proc.wait();raise RuntimeError('Ruff resource or duration admission')
                time.sleep(.2)
        raw=(d/'stderr').read_text(errors='replace');owners={}
        for p in d.glob('exec.*'):
            for line in p.read_text(errors='strict').splitlines():
                m=re.search(r'^execve\("([^"]*/rustc)",.*?"--crate-name", "([^"]+)",',line)
                if m and line.endswith(' = 0'):
                    pid=p.name.split('.')[-1];assert pid not in owners or owners[pid]==m[2];owners[pid]=m[2]
        codes=sorted(set(re.findall(r'error\[(E\d{4})\]',raw)))
        data={'argv':cmd,'subject':sdk.hf(subject),'source':sdk.hf(changed),'lock':sdk.hf(w/'Cargo.lock'),'exit':proc.returncode,'rustcs':owners,'error_codes':codes,'minimum_available':minimum}
        if json_mode:
            lines=[json.loads(l)for l in(d/'stdout').read_text().splitlines()if l.startswith('{')];data['nominal_nonfresh']=[r['target']['name']for r in lines if r.get('reason')=='compiler-artifact' and not r['fresh']]
        if physical:
            j=json.loads(cost.read_bytes());assert j['instructions']>0 and j['running']>0 and j['enabled']<=j['running']*1.01
            data['instructions']=j
        rec[label]=data;sdk.put(d/'result.json',data);sdk.put(out/'release-results.json',roles)
        assert proc.returncode==(101 if wrong else 0),(role,label,raw[-3500:]);assert codes==(['E0308']if wrong else[]),(role,label,codes)
        if not wrong:data['metadata']=md(label,d)
        sdk.put(d/'result.json',data);sdk.put(out/'release-results.json',roles);return data
    try:
        git('restore','--worktree','--staged','--',files['path']);git('switch','--detach',plan['ruff_old']);assert sdk.hf(w/'Cargo.lock')==plan['ruff_lock'] and not git('status','--porcelain')
        empty(role+'-prior');link.unlink();link.symlink_to(subject);v=subprocess.check_output(['cargo','+ohm','-Vv'],text=True,env=ce);assert expected in v
        cold=phase('old');assert len(cold['rustcs'])>100
        before=phase('old-unchanged');git('switch','--detach',plan['ruff_new']);assert not git('status','--porcelain')
        edited=phase('edit');unchanged=phase('edit-unchanged');markers=phase('edit-unchanged-json',json_mode=True)
        original=changed.read_bytes();needle=files['old'].encode();replacement=files['new'].encode();assert original.count(needle)==1 and len(needle)==len(replacement)
        changed.write_bytes(original.replace(needle,replacement));priv=phase('private-body');phase('private-unchanged')
        changed.write_bytes(original);back=phase('restore-body')
        changed.write_bytes(original+b'\nfn ohm_selected_bad_width() -> u8 { false }\n');phase('invalid',wrong=True)
        changed.write_bytes(original);repair=phase('repair')
        empty(role+'-warm');clean=phase('independent-clean-edited')
        for name in edited['metadata']:
            assert edited['metadata'][name]['public']==back['metadata'][name]['public']==repair['metadata'][name]['public']==clean['metadata'][name]['public'],(role,name)
        assert len(edited['rustcs'])==7 and sorted(unchanged['rustcs'].values())==sorted(markers['rustcs'].values())==['ty_python_semantic'] and len(markers['nominal_nonfresh'])==6,(role,'historical roster',edited['rustcs'],unchanged['rustcs'],markers['nominal_nonfresh'])
        sdk.put(out/(role+'-accepted.json'),{'cold_count':len(cold['rustcs']),'edit':sorted(edited['rustcs'].values()),'unchanged':sorted(unchanged['rustcs'].values()),'marked':markers['nominal_nonfresh'],'private_body_public_equal':priv['metadata']['ruff_linter']['public']==edited['metadata']['ruff_linter']['public'],'private_body_actual':sorted(priv['rustcs'].values()),'clean_exact_native_metadata':{name:edited['metadata'][name]['sha256']==clean['metadata'][name]['sha256'] for name in edited['metadata']}})
    except Exception:
        errors[role]=traceback.format_exc();sdk.put(out/'release-refusals.json',errors);print(errors[role],flush=True)
    finally:
        git('restore','--worktree','--staged','--',files['path']);sdk.put(out/'release-results.json',roles)
assert not errors,errors
assert not git('status','--porcelain')
