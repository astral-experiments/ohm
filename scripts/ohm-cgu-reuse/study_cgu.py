"""Observe original Cargo commands and separately measure the LLVM units that were compiled."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent/"ohm-aarch64-linux")]
import qualify as bench
import runtime as rt
from collect_guard import execute
from read_units import read_profile, record
from study import CHILD, PARENT, change_source, digest, load, need, save, sha, source_values

def frozen(p):
    s=p.stat()
    return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_mode,sha(p)]

def stable_selector():
    original=rt.select
    different=original('P')
    need(len(different)==1 and different[0].startswith('lib/librustc_driver'),"compiler pair differs beyond the LLVM-backed driver")
    names=sorted(set(load(rt.LOG/'P-sdk.json')['files'])|set(rt.TOOLS))
    parked=rt.ROOT/'parked-libraries'
    parked.mkdir()
    active=rt.SDK/'lib'
    waiting=parked/'C'
    shutil.copytree(active,waiting,symlinks=False,copy_function=os.link)
    driver=different[0]
    dst=waiting/Path(driver).relative_to('lib')
    target=load(rt.LOG/'C-sdk.json')['files'][driver]
    temp=dst.with_name(dst.name+'.admit')
    shutil.copyfile(rt.CAP/'objects'/target[0],temp);temp.chmod(target[2]);os.replace(temp,dst)
    def snapshot(role,active_role):
        def locate(n):
            return rt.SDK/n if role==active_role or not n.startswith('lib/') else parked/role/Path(n).relative_to('lib')
        return {n:frozen(locate(n)) for n in names}
    before={r:snapshot(r,'P') for r in 'PC'}
    need([n for n in names if before['P'][n]!=before['C'][n]]==different,"unstable or unexpected SDK files")
    for role in 'PC':
        expected=load(rt.LOG/(role+'-sdk.json'))['files']
        need(all(before[role][k][-1]==v[0] for k,v in expected.items()) and all(before[role][k][-1]==v for k,v in rt.TOOLS.items()),"unbound SDK digest")
    save(rt.LOG/'sdk-stamps.json',before)
    state='P';calls=[]
    def select(role):
        nonlocal state
        former=state
        if state!=role:
            active.rename(parked/state)
            try:(parked/role).rename(active)
            except OSError:
                (parked/state).rename(active);raise
            state=role
        need(all(snapshot(r,state)==before[r] for r in 'PC'),"SDK file identity changed")
        calls.append([former,state]);save(rt.LOG/'selector-visits.json',calls)
        return different
    rt.select=select
    for r in 'PCCP':select(r)

def guard(role):
    rt.select(role)
    base=rt.ROOT/'guard-work'
    base.mkdir(exist_ok=True)
    fixture=base/'untracked-cgu-fixture'
    if not fixture.exists():shutil.copytree(HERE/'fixture',fixture)
    execute(base,rt.ROOT/'rustup','collection')
    created=base/'collection'
    dest=rt.LOG/'native-guard'/role
    dest.mkdir(parents=True)
    summary={}
    for p in sorted(created.glob('guard-*')):
        if p.name in ('guard-missing','guard-clean-missing'):
            data=load(p/'result.json')
            need(data['result']=='error' and b'payload.bin' in (p/'stdout').read_bytes()+(p/'stderr').read_bytes(),"missing native input accepted")
            shutil.copytree(p,dest/p.name)
            continue
        row=record(p)
        asm,=[unit for unit,items in row['assignments'].items() if 'fn opaque::payload' in items]
        need(asm in row['physical_codegen'],"LLVM skipped the known file-reading unit")
        summary[p.name]={'asm_unit':asm,**row}
        shutil.copytree(p,dest/p.name)
    for name in ('profile','toolchain.json','command.json'):
        src=created/name
        if src.is_dir():shutil.copytree(src,dest/name)
        else:shutil.copyfile(src,dest/name)
    save(dest/'verified.json',summary)
    # Only these role-specific scratch roots are removed. All programs, profiles and verdicts are escrowed.
    need(created==rt.ROOT/'guard-work/collection' and not created.is_symlink(),'foreign guard scratch root')
    shutil.rmtree(created)
    counts={label:len(value['physical_codegen']) for label,value in summary.items()}
    print('host guard',role,counts,flush=True)
    return counts

def profile_ruff(role):
    rt.select(role)
    root=rt.LOG/('ruff-profile-'+role);root.mkdir()
    env=rt.environment()
    values=source_values(rt.RUFF)
    profiles=rt.ROOT/'ruff-self-profile';profiles.mkdir(exist_ok=True)
    cmd=['cargo','+ohm','rustc','-p','ruff_python_ast','--target',rt.TARGET,'--locked','--offline','-j4','--message-format=json','--',
         '-Zquery-dep-graph','-Zprint-mono-items=yes','-Zself-profile='+str(profiles),'-Zself-profile-events=generic-activity,function-args']
    rows={}
    for cycle,visits in [('warm',[('old','old'),('edit','new'),('repeat-1','new'),('repeat-2','new')]),('empty',[('clean','new')])]:
        bench.acquire(root/(cycle+'-initial'),rt.ROOT/'seed')
        for label,state in visits:
            if label in ('old','edit','clean'):change_source(rt.RUFF,values,state)
            out=root/label;out.mkdir()
            before=set(profiles.iterdir())
            proc=rt.record(cmd,out/'cargo',rt.RUFF,env)
            events=[json.loads(line) for line in proc.stdout.splitlines() if line.startswith(b'{')]
            streaming=[line for line in proc.stdout.splitlines() if not line.startswith(b'{')]
            if b'MONO_ITEM ' not in b'\n'.join(streaming):
                # Cargo may relay raw compiler output through JSON diagnostics on some versions.
                streaming+=proc.stderr.splitlines()
            need(events[-1]=={'reason':'build-finished','success':True},'profiled Cargo did not finish')
            unit,=[u for u in events if u['reason']=='compiler-artifact' and u['target']['name']=='ruff_python_ast']
            archive,=[Path(f) for f in unit['filenames'] if f.endswith('.rlib')]
            content=archive.read_bytes();proof=bench.archive(content)
            expected=load(rt.LOG/('ordinary-'+role)/('old-empty' if state=='old' else 'empty-edited')/'verified.json')
            current=[(name,size,h) for name,original,size,h in proof['objects']]
            unscored=[(name,size,h) for name,original,size,h in expected['archive']['objects']]
            setsame=current==unscored
            new=set(profiles.iterdir())-before
            actual,=new
            (out/'native-profile').write_bytes(actual.read_bytes())
            measured=read_profile(actual)
            lines=b'\n'.join(streaming)+b'\n'
            cgus={m.decode():v.decode() for m,v in re.findall(rb'^CGU_REUSE (\S+) (No|PreLto|PostLto)$',lines,re.M)}
            need(any(v=='No' for v in cgus.values()) and set(measured['physical_codegen'])=={n for n,v in cgus.items() if v=='No'},
                 "Rust reuse report disagrees with independent physical LLVM events")
            need(len(cgus)==len(proof['objects']),"module inventory differs from complete object roster")
            rows[label]={'raw_archive':bench.custody(content,'.profile.rlib'),'actual':measured,'cgus':cgus,
                         'native_objects':current,'compared_to_ordinary':setsame,'Cargo':sha(out/'cargo/command.json')}
            save(out/'result.json',rows[label])
            print('profiled',role,label,len(cgus),len(measured['physical_codegen']),'same ordinary native objects',setsame,flush=True)
        bench.park('profile-'+role+'-'+cycle)
    for label in ('edit','repeat-1','repeat-2'):
        need(rows[label]['native_objects']==rows['clean']['native_objects'],"profiled AST objects differ from empty")
    save(root/'terminal.json',rows)
    return {k:{'total':len(v['cgus']),'physical':len(v['actual']['physical_codegen']),'same_ordinary':v['compared_to_ordinary']} for k,v in rows.items()}

def main():
    need(PARENT=='82911b516fb35608fd70ada4deb6f8429277f410' and CHILD=='3de892a47171543b624e0d360d6d532f2da815f7','different Rust subjects')
    stable_selector()
    def retire(name):
        for n in ('target','shared','cargo-home'):
            src=rt.WORK/n
            need(src.is_dir() and not src.is_symlink() and src.parent==rt.WORK, 'foreign retired build root')
            shutil.rmtree(src)
    bench.park=retire
    bench.prepare()
    guard_rows={r:guard(r) for r in 'PC'}
    need(guard_rows['P']['guard-repeat']>guard_rows['C']['guard-repeat']>0,"no partial reuse on the native guard")
    ordinary={}
    for role in 'PC':
        ordinary[role]=bench.trial('ordinary-'+role,role)
        save(rt.LOG/('ordinary-'+role)/'complete.json',ordinary[role])
    for k in ('cold','old'):
        need(ordinary['P'][k]['native']==ordinary['C'][k]['native'] and ordinary['P'][k]['value']==ordinary['C'][k]['value'],
             'the two roles produced different native payloads or values')
    save(rt.LOG/'ordinary-complete.json',{'guard':guard_rows,'roles':ordinary})
    profiles={r:profile_ruff(r) for r in 'CP'}
    save(rt.LOG/'terminal.json',{'guard':guard_rows,'profiles':profiles,'ordinary':sha(rt.LOG/'ordinary-complete.json')})
    print('two native roles completed',profiles,flush=True)

if __name__=='__main__': main()
