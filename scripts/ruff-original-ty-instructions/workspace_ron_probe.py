"""Intervene at exactly one signed Cargo recorder entry in disposable current-Ruff histories."""
from collections import Counter
from pathlib import Path
import gzip
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess as sp
import sys
import threading
import time
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import workspace29697 as b
from ron_causality import without_observation,replace

w=b.w
P=b.PROOF
SPEC=b.SPEC


def read_json(path):
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_bytes())


def live_ron(stop, owners):
    wanted=(w.sdk/'bin/rustc').resolve()
    while not stop.is_set() and not owners:
        for p in Path('/proc').glob('[0-9]*'):
            try:
                if not (p/'exe').samefile(wanted): continue
                argv=[os.fsdecode(x)for x in (p/'cmdline').read_bytes().split(b'\0')[:-1]]
                if '--crate-name' not in argv or argv[argv.index('--crate-name')+1]!='ron':continue
                cwd=(p/'cwd').resolve(strict=True)
                env=dict(os.fsdecode(x).split('=',1)for x in (p/'environ').read_bytes().split(b'\0')[:-1])
                assert not any(any(x in k for x in ('TOKEN','PASSWORD','SECRET'))for k in env)
                owners.append((int(p.name),argv,env,cwd))
                return
            except (PermissionError,FileNotFoundError,ProcessLookupError):pass
        stop.wait(.035)


def ron_paths(inv):
    files=[w.root/p for p in inv['workspace_artifacts_and_ron'] if Path(p).name.startswith('libron-')]
    rlibs=[p for p in files if p.suffix=='.rlib']
    rlib,=rlibs
    meta=rlib.with_suffix('.rmeta')
    dep=rlib.with_name(rlib.name[3:]).with_suffix('.d')
    records=list(rlib.parent.parent.glob('fingerprint/dep-lib-ron'))
    assert len(records)==1 and all(p.is_file() for p in (rlib,meta,dep)) and b'ohm-foreign-span-bytes' in dep.read_bytes()
    return records[0],dep,meta,rlib


def state(tag, inv):
    dest=P/tag/'producer'
    dest.mkdir()
    fp,dep,meta,lib=ron_paths(inv)
    for k,p in [('dep-record',fp),('rustc-d',dep),('metadata.rmeta',meta),('archive.rlib',lib)]:
        shutil.copyfile(p,dest/k)
    return fp


def native(tag, inv, graph):
    c=read_json(P/tag/'owner-census.json.gz')
    out=[]
    operand_cache={}
    tree=graph['units']
    records={r['epoch']:r for r in c['roles']}
    jobs=[r for r in c['roles'] if r['trigger']=='exec'and (r['mode']=='Wild'or r['mode'].startswith('native-linker/'))]
    for row in jobs:
        rust=records[row['owning_rustc_epoch']]
        path=Path(row['output'])
        rel=str(path.relative_to(w.root))
        u=inv['executables'].get(rel,{}).get('unit')
        reach=[]
        if u:
            roots=[i for i,t in enumerate(tree) if t['pkg_id']==u[0] and t['target']['name']==u[1] and t['target']['kind']==u[2] and t['mode']==('test' if u[-1] else 'build')]
            for i in roots:
                pending=[i];seen=set()
                while pending:
                    n=pending.pop()
                    if n in seen:continue
                    seen.add(n);pending.extend(d['index'] for d in tree[n]['dependencies'])
                reach.append([i,sorted(n for n in seen if tree[n]['target']['name']=='ron')])
        args=(P/tag/'tasks'/row['argv']).read_bytes().split(b'\0')[4:-1]
        assert args and (P/tag/'tasks'/row['argv']).is_file()
        operands=[]
        leaves=[]
        for raw in args:
            s=os.fsdecode(raw)
            if s.startswith('-L')or (s.startswith('-l')and len(s)>2):leaves.append(s)
            if not s.startswith('/'):continue
            f=Path(s)
            if f==path or f.suffix not in {'.rlib','.o','.a','.so','.rmeta'}:continue
            if s not in operand_cache:operand_cache[s]=[f.stat().st_size,w.hf(f)] if f.is_file() else None
            operands.append(s)
        ron=[v for v in operands if Path(v).name.startswith('libron-')]
        out.append({'destination':rel,'unit':u,'mode':rust['mode'],'owner':rust['crate'],'epoch':row['epoch'],'absolute_file_operands':operands,'argv_sha256':row['argv_sha256'],'literal_ron':ron,'declared_search':leaves,'graph_path_to_ron':reach})
    b.write(P/tag/'link-inputs.json.gz',{'links':out,'literal_files_after_command':operand_cache,'scope':'Only literal file operands surviving the command are hashed. Raw argv is complete, including unresolved -L/-l and disappeared rustc temps.'})
    return {'rustc':dict(Counter(r['mode'] for r in c['roles'] if r['trigger']=='exec'and r['mode'] in ('full','test','metadata','link-only','config'))),'native':len(jobs),'destinations':sorted(x['destination']for x in out),'has_ron_archive':sum(bool(x['literal_ron']) for x in out),'graph_all_selected_ron':sum(bool(x['graph_path_to_ron']) and all(a[1] for a in x['graph_path_to_ron']) for x in out)}


def run_check(tag,env,graph,ug,watch=False):
    owners=[];stop=threading.Event()
    th=threading.Thread(target=live_ron,args=(stop,owners),daemon=True) if watch else None
    if th:th.start()
    try:
        inv=b.inventory(tag,env,graph,'census')
    finally:
        stop.set()
        if th:th.join(timeout=5)
    roster=native(tag,inv,ug)
    fp=state(tag,inv)
    err=P/tag/'stderr'
    with err.open('rb') as f,gzip.open(P/tag/'all-fingerprint.stderr.gz','wb')as out:shutil.copyfileobj(f,out)
    reasons=[]
    for ln in err.read_text().splitlines():
        if 'dirty' in ln.lower() and ('reason:' in ln or 'fingerprint dirty for' in ln):reasons.append(ln)
    b.write(P/tag/'dirty-fingerprint-reasons.json.gz',reasons)
    err.unlink()
    if watch:
        assert len(owners)==1
        pid,args,env0,cwd=owners[0]
        tasks=read_json(P/tag/'owner-census.json.gz')['roles']
        rr,=[r for r in tasks if r['pid']==pid and r['trigger']=='exec' and r['crate']=='ron' and r['mode']=='full']
        assert args==[os.fsdecode(s)for s in (P/tag/'tasks'/rr['argv']).read_bytes().split(b'\0')[4:-1]]
        b.write(P/tag/'ron-execution.json',{'argv':args,'cwd':str(cwd),'env_names':sorted(env0),'physical':rr})
    return inv,fp,roster,owners


def fingerprints(inv):
    return {p:row['elf']['sha256'] for p,row in inv['executables'].items()}


def causal(side,env,graph,ug,results):
    tag=side+'-untouched'
    orig,fp,rr,captured=run_check(tag,env,graph,ug,watch=side=='new')
    original=fp.read_bytes();ablate,proof=without_observation(original)
    stamp=fp.stat()
    b.write(P/tag/'single-record-transition.json',dict(proof,path=str(fp),mtime=stamp.st_mtime_ns,ino=stamp.st_ino))
    replace(fp,ablate,original)
    try:
        changed,fp2,ra,_=run_check(side+'-ablated',env,graph,ug)
        after=fp.read_bytes()
    finally:
        if fp.read_bytes()!=original:replace(fp,original,fp.read_bytes())
        os.utime(fp,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
    restored,_,rb,_=run_check(side+'-restored',env,graph,ug)
    a,bh,c=map(fingerprints,(orig,changed,restored))
    assert set(a)==set(bh)==set(c) and len(a)==102
    if any(trace['native'] for trace in (rr,rb)):assert rr['destinations']==rb['destinations']
    results[side]={'before':rr,'diagnostic':ra,'restored':rb,'after_record_stayed_ablated':after==ablate,'original_equals_diagnostic':[p for p in a if a[p]!=bh[p]],'original_equals_restored':[p for p in a if a[p]!=c[p]],'counts':[sum(not fresh for _,fresh in i['units'])for i in(orig,changed,restored)]}
    b.write(P/'causality.json',results)
    return restored,captured


def main():
    assert os.environ['GITHUB_SHA']==os.environ['REVIEWED_HEAD'] and os.environ['GITHUB_RUN_ATTEMPT']=='1'
    assert w.hf(w.src/'sdk.json')==SPEC['sdk_manifest'] and w.git('rev-parse','HEAD')==b.NEW and w.git('rev-parse','HEAD^')==b.OLD
    assert shutil.disk_usage(w.root).free>45*2**30
    b.write(P/'registration.json',{'original':41617756983,'side':'separate causal diagnostic','study':SPEC,'source':os.environ['GITHUB_SHA'],'run':os.environ['GITHUB_RUN_ID'],'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'branch':os.environ['GITHUB_REF_NAME'],'intervention':'Only the original Ron translated foreign marker, authenticated OBS1 and one file-count entry; preserve all other rows and mtime and restore exact original before next edit. No scored timing or product optimization.'})
    env=w.install()
    assert 'CARGO_LOG' not in env
    env['CARGO_LOG']='cargo::core::compiler::fingerprint=trace,cargo::compiler::fingerprint=trace'
    b.write(P/'environment.json',env)
    for tool in ('whole_count','exec_count'):
        sp.run(['cc','-Wall','-Wextra','-Werror','-O2',HERE/(tool+'.c'),'-o',w.root/tool],check=True)
    b.select(b.OLD);b.write(P/'locked-registry.json.gz',b.inputs(env))
    g=json.loads(sp.check_output(['cargo','+ohm','metadata','--format-version=1','--locked','--offline','--no-deps'],cwd=w.work,env=env))
    ug=json.loads(sp.check_output([*b.CMD[:2],'-Zunstable-options',*b.CMD[2:-1],'--unit-graph'],cwd=w.work,env=env))
    assert sorted(g['workspace_members'])==sorted(g['workspace_default_members']) and len(g['workspace_members'])==55 and len(ug['units'])==693
    b.write(P/'unit-graph.json.gz',ug)
    for p in (w.target,w.shared):
        if p.exists():
            assert p.parent==w.root and p.is_dir() and not p.is_symlink()
            shutil.rmtree(p)
    old=b.inventory('old-cold',env,g)
    matching=b.verdict(w.root/old['binary'],'old-verdict',env,0)
    results={};old,_=causal('old',env,g,ug,results)
    held=w.root/'held-old-debug-command';shutil.copy2(w.root/old['binary'],held)
    b.select(b.NEW)
    assert b.verdict(held,'old-on-new',env,101)==matching
    new=b.inventory('real-edit',env,g)
    assert b.verdict(w.root/new['binary'],'new-verdict',env,0)==matching
    restored,captured=causal('new',env,g,ug,results)
    assert b.verdict(w.root/restored['binary'],'restored-verdict',env,0)==matching
    assert not w.git('status','--porcelain')
    from ron_observe import run
    run(captured[0],w.root, w.sdk,w.src,P,ron_paths(restored))
    assert sum(p.stat().st_size for p in P.rglob('*')if p.is_file())<480*2**20

if __name__=='__main__':main()
