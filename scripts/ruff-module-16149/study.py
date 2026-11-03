"""Observe the ordinary check, full native diagnostics, and independent clean histories."""
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import lens
from setup import BASE_OUT, BUILD, CHECK, EDIT, FILES, FIX, OLD, REG, activate, env, need, save, sha, source, w

ROLE = sys.argv[1] if len(sys.argv)==2 else None
MEMBERS = BASE_OUT/'members'
OLD_SCOPE='rules::pylint'
NEW_SCOPE='{{crate}}'
# All three sources use this exact checker, code, and preview registration.
PROBES={'operator':'__add__', 'unknown':'__ohm_unknown__', 'known':'__init__'}


def records(directory, successful=True):
    rows=[json.loads(line)for line in (directory/'stdout').read_bytes().splitlines()if line]
    need([r['success']for r in rows if r['reason']=='build-finished']==[successful], 'Cargo terminal verdict')
    errors=[r['message']for r in rows if r['reason']=='compiler-message' and r['message']['level']=='error']
    need(not errors if successful else any((r.get('code')or{}).get('code')=='E0308' and FILES[1] in str(r['spans']) and 'OHM_INVALID_CHECK_SENTINEL' in str(r['spans'])for r in errors), 'actual type error or success')
    need(b'internal compiler error' not in (directory/'stderr').read_bytes().lower(),'compiler ICE')
    return [r for r in rows if r['reason']=='compiler-artifact']


def capture(file):
    h=sha(file);MEMBERS.mkdir(exist_ok=True);d=MEMBERS/(h+'.rmeta.zst')
    if not d.exists():
        with d.open('xb')as dst:subprocess.run(['zstd','-q','-3','-c',file],stdout=dst,check=True)
    return dict(sha256=h,bytes=file.stat().st_size,archive=sha(d))


def original(file,owner,edition,binding):
    h=binding['sha256'];report=MEMBERS/(h+'.json')
    if not report.exists():
        raw=file.read_bytes();need(hashlib.sha256(raw).hexdigest()==h,'file changed during capture')
        q=lens.decode(raw,owner,edition)
        need(q['header']['full']==h,'raw metadata digest')
        q.update(bytes=len(raw),archive=binding['archive']);save(report,q)
    q=json.loads(report.read_text())
    need(q['header']['full']==h and q['header']['crate']==owner and q['edition']==edition,'metadata collision or wrong role')
    return q


def traced(dir,expected):
    actual={};raw_count=0
    for f in sorted(dir.glob('trace.*')):
        lines=f.read_bytes().splitlines();tid=int(f.name.rsplit('.',1)[1])
        for line in lines:
            if b'"--crate-name"' not in line:continue
            program=re.search(rb'execve\("([^"\\]+)",',line)
            need(program and line.endswith(b' = 0'), 'unresolved compiler exec: '+str(line[:140]))
            exe=Path(os.fsdecode(program[1]))
            name=re.search(rb'"--crate-name", "([a-zA-Z0-9_]+)"',line);need(name,'truncated compiler argv')
            if exe.is_file() and exe.samefile(w.ROOT/'proxies/rustup'):continue
            need(exe.is_absolute() and exe.is_file() and exe.samefile(w.SDK/'bin/rustc'),'unexpected compiler image: '+str(exe))
            name=name[1].decode();need(tid not in actual,'multiple physical compiler images in same task')
            if name in set(REG['expected_root_roster'])|{'ruff'}:
                need(f'"--edition={REG["edition"]}"'.encode()in line,'physical historical rustc edition')
            stat=exe.stat()
            actual[tid]=dict(crate=name,program=str(exe),dev=stat.st_dev,inode=stat.st_ino,argv=line.decode(errors='strict'))
        raw_count+=len(lines)
        packed=f.with_suffix(f.suffix+'.gz')
        with f.open('rb')as src,gzip.open(packed,'wb',compresslevel=2)as dest:shutil.copyfileobj(src,dest)
        f.unlink()
    if expected is not None:need(Counter(v['crate'] for v in actual.values())==Counter(expected), ('real compiler vs Cargo dirty rows',sorted(v['crate']for v in actual.values()),sorted(expected)))
    save(dir/'native-execs.json',dict(rustc=sha(w.SDK/'bin/rustc'),raw_lines=raw_count,actual=actual))
    return sorted(v['crate']for v in actual.values())


def check(label,rev,environment,trace=False):
    source(rev);out=w.OUT/label
    argv=CHECK
    if trace:
        trace_dir=w.OUT/(label+'-observer');trace_dir.mkdir()
        argv=['/usr/bin/strace','-ff','-qq','-s','260000','-e','trace=execve','-o',str(trace_dir/'trace'),*CHECK]
    w.run(argv,environment,out,timeout=2400)
    arts=records(out);wanted=REG['expected_root_roster']; selected={};inputs={}
    for name in wanted:
        row,=[r for r in arts if r['target']['name']==name and r['target']['kind']==['lib']]
        file,=[Path(f)for f in row['filenames']if f.endswith('.rmeta')]
        need(Path(row['manifest_path']).samefile(w.SRC/'crates'/name/'Cargo.toml') and row['target']['edition']==REG['edition'],'physical target or manifest edition')
        inputs[name]=(file,row,capture(file))
    save(out/'original-metadata.json',{n:dict(**q,edition=row['target']['edition'],file=f.name)for n,(f,row,q)in inputs.items()})
    for name,(file,row,binding) in inputs.items():
        q=original(file,name,row['target']['edition'],binding);selected[name]=dict(sha256=q['header']['full'],public=q['header']['public'],private=q['header']['private'],global_hash=q['header']['global_hash'],stable=q['header']['stable'],fresh=row['fresh'],file=file.name)
    q=json.loads((MEMBERS/(selected['ruff_linter']['sha256']+'.json')).read_bytes())
    need(q['witness']['scope']==(OLD_SCOPE if rev==OLD else NEW_SCOPE),'historical module visibility')
    need(all(not p['ctfe'] and not p['optimised'] for p in q['witness']['functions'].values()),'body export on actual metadata-only check')
    cli,=[r for r in arts if r['target']['name']=='ruff' and r['target']['kind']==['bin']]
    roster=sorted([[r['package_id'],r['target']['name'],r['target']['kind'],sorted(r['features']),r['fresh']]for r in arts])
    dirty=sorted(r['target']['name'].replace('-','_')for r in arts if not r['fresh'])
    native=traced(trace_dir,dirty) if trace else None
    result=dict(source=rev,roster=roster,dirty=dirty,target_fresh=cli['fresh'],selected=selected)
    save(out/'check.json',dict(**result,native_execs=native))
    print(ROLE,label,'dirty',dirty if len(dirty)<22 else len(dirty),'linter',selected['ruff_linter']['public'],flush=True)
    return result


def cli(label,rev,environment):
    w.checkout(rev);out=w.OUT/label
    w.run(BUILD,environment,out,timeout=3000)
    arts=records(out);row,=[r for r in arts if r['target']['name']=='ruff'and r['target']['kind']==['bin']]
    binary=Path(row['executable']); need(binary.is_file() and binary.stat().st_size>100000,'actual native binary')
    with binary.open('rb')as exe:need(exe.read(4)==b'\x7fELF','native binary format')
    argv=[str(binary),'check','--isolated','--no-cache','--preview','--select','PLW3201','--output-format','json','--stdin-filename','probe.py','-']
    values={}
    for key,method in PROBES.items():
        body=f'class Vector:\n    def {method}(self, other):\n        return self\n'.encode()
        p=subprocess.run(argv,cwd=w.ROOT,env=environment,input=body,capture_output=True,timeout=40)
        diagnostics=json.loads(p.stdout)
        wanted=key=='unknown' or key=='operator' and rev==EDIT
        message=f'Dunder method `{method}` has no special meaning in Python 3'
        need(not p.stderr and p.returncode==int(wanted),('native Ruff return',label,key,p.returncode,p.stderr.decode(errors='replace'),diagnostics))
        need([x['code']for x in diagnostics]==(['PLW3201']if wanted else []),'native Ruff code')
        if wanted:
            need(diagnostics[0]['message']==message and diagnostics[0]['location']['row']==2 and diagnostics[0]['location']['column']==9,'native lint owner/message')
        values[key]=dict(input=body.decode(),exit=p.returncode,stdout=p.stdout.decode(),stderr=p.stderr.decode())
    record=dict(source=rev,argv=argv,sha256=sha(binary),bytes=binary.stat().st_size,probes=values);save(out/'cli.json',record)
    print(ROLE,label,'actual PLW3201',values['operator']['exit'],flush=True)
    return record


def rmprivate(path):
    if path.exists():
        need(path.parent==w.ROOT and path.is_dir()and not path.is_symlink(),'private checkpoint');shutil.rmtree(path)


def study(role):
    w.checked_head()
    w.OUT=BASE_OUT/role;w.OUT.mkdir()
    installed=activate(role);save(w.OUT/'toolchain.json',installed)
    state=env();save(w.OUT/'environment.json',state)
    # A source-driven control first. Both SDKs actually link and execute all three historical verdicts.
    w.fresh_state()
    native={}
    for label,rev in [('old',OLD),('edit',EDIT),('upstream-fix',FIX)]:native[label]=cli('cli-'+label,rev,state)
    w.fresh_state();native['empty-edit']=cli('cli-empty-edit',EDIT,state)
    need(native['edit']['probes']==native['empty-edit']['probes'],'incremental vs independently empty native diagnostics')
    save(w.OUT/'native.json',native)

    w.checkout(OLD);w.fresh_state()
    old=check('check-old',OLD,state)
    old_idle=check('check-old-unchanged',OLD,state)
    need(not old_idle['dirty'] and old['selected']['ruff_linter']['public']==old_idle['selected']['ruff_linter']['public'],'warm old state')
    rmprivate(w.ROOT/'before-edit');parts,mtimes=w.make_snapshot()
    w.checkout(EDIT);edit=check('check-edit',EDIT,state)
    idle=check('check-edit-unchanged',EDIT,state)
    w.restore_snapshot(parts,mtimes);w.checkout(EDIT);observed=check('check-edit-trace',EDIT,state,True)
    observer_equal=observed==edit
    save(w.OUT/'observer-agreement.json',dict(complete=observer_equal,roster=observed['roster']==edit['roster'],complete_raw_per_target={k:observed['selected'][k]==v for k,v in edit['selected'].items()}))
    rmprivate(w.ROOT/'before-edit')
    code=w.SRC/FILES[1];true_bytes=code.read_bytes()
    try:
        code.write_bytes(true_bytes+b'\nconst OHM_INVALID_CHECK_SENTINEL: u32 = "incorrect";\n')
        fail=w.OUT/'check-invalid';w.run(CHECK,state,fail,101); records(fail,False)
    finally:code.write_bytes(true_bytes)
    repaired=check('check-repaired',EDIT,state)
    w.checkout(FIX);upstream=check('check-upstream-fix',FIX,state)
    w.checkout(EDIT);w.fresh_state();clean=check('check-empty-edit',EDIT,state)
    evidence=dict(old=old,edit=edit,idle=idle,observed=observed,repaired=repaired,upstream_fix=upstream,clean=clean,observer_equal=observer_equal)
    save(w.OUT/'role.json',evidence)


def compare():
    w.checked_head()
    roles={r:json.loads((BASE_OUT/r/'role.json').read_bytes())for r in ('P','C')}
    native={r:json.loads((BASE_OUT/r/'native.json').read_bytes())for r in roles}
    need(all(native['P'][s]['probes']==native['C'][s]['probes']for s in native['P']),'native cross-compiler disagreement')
    roots=set(REG['expected_root_roster'])|{'ruff'}
    out={}
    for role,h in roles.items():
        o,e,u=h['old']['selected'],h['edit']['selected'],h['clean']['selected']
        sem={k:all(e[k][a]==u[k][a]==h['repaired']['selected'][k][a] for a in ('public','global_hash','stable'))for k in e}
        out[role]=dict(observer_equal=h['observer_equal'],producer_private_changed=o['ruff_linter']['private']!=e['ruff_linter']['private'],producer_public_changed=o['ruff_linter']['public']!=e['ruff_linter']['public'],unchanged_dirty=h['idle']['dirty'],ordinary_dirty=h['edit']['dirty'],observed_dirty=h['observed']['dirty'],semantic_clean=sem,full_clean={k:e[k]['sha256']==u[k]['sha256']for k in e},native=sorted(roots&set(h['edit']['dirty'])))
    diff=sorted((set(out['P']['native'])-set(out['C']['native']))-{'ruff_linter'})
    admit=(out['P']['producer_public_changed'] and not out['C']['producer_public_changed'] and bool(diff) and all(r['observer_equal'] and r['producer_private_changed'] and 'ruff_linter' in r['native'] and not r['unchanged_dirty'] and all(r['semantic_clean'].values())for r in out.values()))
    result=dict(endpoint='unscored physical Cargo shape',roles=out,downstream_compilers_skipped=diff,qualifies_causal_separation=admit)
    save(BASE_OUT/'decision.json',result);print(json.dumps(result,sort_keys=True),flush=True)


if __name__=='__main__':
    if ROLE=='compare':compare()
    elif ROLE in ('P','C'):study(ROLE)
    else:raise ValueError('role must be P, C or compare')
