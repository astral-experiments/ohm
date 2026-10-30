"""Observe a settled command's dirty reasons and actual GNU linker reads, outside timing."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
import census

def independent_ty(work,root,enrolled):
    src=work/'ruff';env=enrolled['env'];cli=enrolled['cli']
    assert cli==census.CLI
    census.qualify.rt.SDK=(work/'rustup/toolchains/ohm').resolve(strict=True)
    expected=json.loads((root/'edit/census.json').read_text())['product']
    summary=json.loads((root/'terminal.json').read_text())['phases']['edit']['product']
    assert expected['control'] in expected['tests'] and all(expected[k]==v for k,v in summary.items())
    rule=next(name for name in enrolled['changed'] if name.endswith('/exclude.rs'))
    marker='OHM_TY_PROJECT_NATIVE_REPLAY_INVALID'
    with (src/rule).open('a') as f:f.write('\nconst _: usize = '+marker+';\n')
    result={}
    for label in ('invalid','repair','empty-new'):
        if label=='repair':
            census.command(['git','restore','--worktree','--',rule],src,env)
        if label=='empty-new':
            for name in ('target','shared'):(work/name).rename(work/('retained-'+name))
        assert census.command(['git','diff','--name-only'],src,env).splitlines()==([rule] if label=='invalid' else [])
        d,msgs,kernel=census.trace_build('oracle-'+label,work,root,src,env,cli,101 if label=='invalid' else 0)
        if label=='invalid':
            assert any((x.get('message',{}).get('code') or {}).get('code')=='E0425' and marker in x['message']['rendered'] for x in msgs)
            result[label]={'diagnostic':'E0425'}
        else:
            exe,=[Path(m['executable']) for m in msgs if m.get('reason')=='compiler-artifact' and m.get('target',{}).get('name')=='ty_project' and m.get('executable')]
            product=census.native_tests(exe,label,census.B,src,d,env,expected)
            result[label]=product
    verdicts=[result[s]['tests']==expected['tests'] for s in ('repair','empty-new')]
    assert all(verdicts) and len(expected['tests'])==73
    actual=result['empty-new']['sha256']
    result['edit_and_repair_match_empty']=[expected['sha256']==actual,result['repair']['sha256']==actual]
    census.save(root/'ty-independent.json',result)
    return actual

def main():
    work=Path(os.environ['CENSUS_ROOT']).resolve(strict=True)
    root=work/'receipts';out=root/'settled-why';out.mkdir()
    enrolled=json.loads((root/'enrolled.json').read_text());cmd=enrolled['cli']
    if cmd==census.CLI:
        clean=independent_ty(work,root,enrolled)
    else:
        clean=json.loads((root/'terminal.json').read_text())['phases']['empty-new']['product']['sha256']
    saved=json.loads((root/'repeat/kernel.json').read_text())
    paths=set()
    for r in [*saved['rustcs'],*saved['link_tools']]:
        for i,a in enumerate(r['argv']):
            if i and r['argv'][i-1]=='--extern' and '=' in a:
                a=a.split('=',1)[1]
            if a.startswith('/') and Path(a).is_file() and a.endswith(('.rlib','.o','.a','.rmeta','.so')):
                paths.add(a)
    def snap():
        result={}
        for name in sorted(paths):
            f=Path(name)
            if not f.is_file():continue
            st=f.stat()
            result[name]=[census.sha(f),st.st_size,st.st_dev,st.st_ino,st.st_mtime_ns,st.st_ctime_ns]
        return result
    before=snap();trace=work/'settled-why';trace.mkdir()
    env=enrolled['env']|{'CARGO_LOG':'trace'}
    argv=['strace','-ff','-q','-s','262144','-e','trace=execve,execveat,open,openat,openat2','-o',str(trace/'proc'),*cmd]
    cargo=subprocess.run(argv,cwd=work/'ruff',env=env,capture_output=True,timeout=3700)
    census.blob(out/'cargo-stdout.gz',cargo.stdout);census.blob(out/'cargo-trace.gz',cargo.stderr)
    assert cargo.returncode==0,cargo.stderr[-1200:]
    messages=list(map(json.loads,cargo.stdout.splitlines()))
    assert messages[-1]=={'reason':'build-finished','success':True}
    returned=[Path(m['executable']) for m in messages if m.get('reason')=='compiler-artifact' and m.get('executable') and m['target']['name'] in ('ty_project','ruff')]
    assert len(returned)==1,returned
    assert census.sha(returned[0])==clean
    selected={}
    for f in sorted(trace.glob('proc.*')):
        data=f.read_bytes()
        paths_exec=re.findall(rb'^execve\("([^"]+)"[^\n]*\) += 0$',data,re.M)
        if not paths_exec:continue
        pid=int(f.name.split('.')[-1]);names=[Path(os.fsdecode(p)).name for p in paths_exec]
        link=any(n in ('ld','ld.bfd','ld.lld','rust-lld','wild') for n in names)
        calls=re.findall(rb'^(?:open|openat|openat2)\([^\n]*\) += (?:-?\d+).*$',data,re.M)
        if link or 'rustc' in names or 'cargo' in names:
            cens=calls if link else []
            lines=[l for l in data.splitlines() if l.startswith((b'execve(',b'execveat('))]
            if link:lines+=cens
            census.blob(out/('raw-'+str(pid)+'.gz'),b'\n'.join(lines)+b'\n')
            selected[str(pid)]={'exec':names,'link':link,'retained_ld_opens':len(cens)}
    assert any('cargo' in p['exec'] for p in selected.values())
    after=snap()
    assert set(after)==set(before)
    # stat changes can invalidate a consumer even when the bytes are identical.
    delta={'same_bytes_new_stat':[],'different_bytes':[]}
    for n in before:
        if before[n]!=after[n]:
            delta['different_bytes' if before[n][0]!=after[n][0] else 'same_bytes_new_stat'].append(n)
    census.save(out/'original-inputs.json',before);census.save(out/'resulting-inputs.json',after)
    census.save(out/'verdict.json',{'untimed':True,'physical':selected,'changes':delta,'command':cmd,'declared_sdk':enrolled['compiler'],'root_elf':clean,'compared_files':len(before),'log_sha256':hashlib.sha256(cargo.stderr).hexdigest()})
    print('Settled attribution',len(returned),'products checked',len(before),'physical files',len(delta['different_bytes']),'changed bytes',flush=True)

if __name__=='__main__': main()
