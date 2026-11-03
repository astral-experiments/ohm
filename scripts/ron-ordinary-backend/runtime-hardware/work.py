"""Measure full signed Ron processes under Cargo and a separate whole Cargo tree per treatment."""
from pathlib import Path
import collections
import gzip
import hashlib
import json
import os
import shutil
import subprocess as sp
import sys
import threading
import time

HERE=Path(__file__).resolve().parent
inside=len(sys.argv)==3 and sys.argv[1]=='--inside'
if inside:
    ctx=json.loads(Path(sys.argv[2]).read_bytes());os.environ.update(ctx['process'])
sys.path.insert(0,str(HERE.parent));sys.path.insert(0,str(HERE))
import construct
import ordinary as o
import prepare
b=o.b;w=o.w;P=o.P
read=lambda f:json.loads(f.read_bytes())
plan=read(HERE/'registration.json')
def put(name,record):b.write(P/name,record)

def environment(env,label,mode,counter=False):
    e=dict(env,LD_PRELOAD=str(w.root/'cargo-dispatch.so'),OHM_CAPTURE_DISPATCH=str(w.root/'cargo-dispatch.so'),
           OHM_CAPTURE_RECEIVER=str(HERE/'receiver.py'),OHM_CAPTURE_CARGO=str(w.sdk/'bin/cargo'),OHM_CAPTURE_ACTION=mode,
           OHM_CAPTURE_ACTOR=str(w.root/'all-native'),OHM_CAPTURE_VISIT=str(P/label/'ron-visit'))
    if counter:e['OHM_RON_NATIVE_PMU']=str(w.root/'whole_count')
    return e

def reference(env,graph):
    # Untreated, separate from both PMU arms. The outer counter records the true physical argv.
    stop=threading.Event();files={};observed=[]
    def watch():
        while not stop.is_set():
            for proc in Path('/proc').glob('[0-9]*'):
                try:
                    if not (proc/'exe').samefile(w.sdk/'bin/rustc'):continue
                    argv=(proc/'cmdline').read_bytes().split(b'\0')
                    if b'--crate-name'not in argv or argv[argv.index(b'--crate-name')+1]!=b'ron':continue
                    image=[]
                    for line in (proc/'maps').read_text().splitlines():
                        fields=line.split(None,5)
                        if len(fields)!=6 or 'x'not in fields[1] or not fields[5].startswith('/'):continue
                        path=Path(fields[5]);st=path.stat()
                        assert st.st_ino==int(fields[4])
                        assert [os.major(st.st_dev),os.minor(st.st_dev)]==[int(v,16)for v in fields[3].split(':')]
                        image.append([str(path),fields[3],st.st_ino])
                        files[str(path)]=[str(path),fields[3],st.st_ino,st.st_size,st.st_uid,st.st_nlink,st.st_mtime_ns,st.st_ctime_ns]
                    observed.append([time.monotonic_ns(),proc.name,image])
                except (FileNotFoundError,ProcessLookupError,PermissionError):continue
            stop.wait(0.015)
    th=threading.Thread(target=watch);th.start()
    try:inv=b.inventory('untouched-real-census',environment(env,'untouched-real-census','observe'),graph,'census')
    finally:stop.set();th.join()
    for name,row in files.items():row.append(prepare.sha(Path(name)))
    rows=list(files.values());put('kernel-maps.json.gz',dict(files=rows,samples=observed))
    assert len(rows)==13 and len(observed)>0
    true,_,counts=o.census('untouched-real-census')
    assert len(true)==1 and counts['Wild']==50 and counts['link-only']==50
    cap=P/'untouched-real-census/ron-visit';role=prepare.cargo_role(cap,w.sdk)
    assert role['argv_sha256']==true[0]['parameters']
    return cap,rows,inv

def census_body(label,graph):
    out=P/label
    rows=[json.loads(l)for l in (out/'stdout.jsonl').read_bytes().splitlines()]
    assert rows[-1]=={'reason':'build-finished','success':True}
    units=[r for r in rows if r['reason']=='compiler-artifact']
    assert len(units)==plan['unit_count']
    ron,=[r for r in units if r['target']['name']=='ron' and 'ron@0.12.0' in r['package_id']]
    e2e,=[Path(r['executable'])for r in units if r.get('executable')and r['target']['name']=='e2e'and 'ty_server'in r['package_id']]
    return [Path(f)for f in ron['filenames']],e2e

def hw(f):
    row=read(f);assert row['instructions']>0 and row['enabled']==row['running']>0 and row['status']==0,row
    return row

def seal_files(out,label,archive):
    store=P/'ron-native-objects';store.mkdir(exist_ok=True);ret={}
    for f in out:
        assert f.is_file()and f.suffix in ('.rmeta','.rlib')
        h=w.hf(f);file=store/(h+'.zst')
        if not file.exists():
            with file.open('xb')as target:sp.run(['zstd','-q','-3','-c',f],stdout=target,check=True)
        ret[f.suffix]=[f.stat().st_size,h]
    assert set(ret)=={'.rlib','.rmeta'} and ret['.rlib'][1]==archive,(label,ret,archive)
    return ret

def direct(label,mode,env,graph,archive,oracle,kind,hits=None):
    assert kind in ('cold','warm','whole','outside','seed','unregistered-RX')
    td=P/label;before=environment(env,label,mode,kind in ('cold','warm'))
    if kind=='whole':
        if mode=='stock':before=env
        b.inventory(label,before,graph)
        price=hw(td/'hardware.json')
    else:
        td.mkdir();b.run(b.CMD,before,td)
        price=hw(td/'ron-visit/complete-hardware.json')if kind in ('cold','warm')else None
    products,bin=census_body(label,graph);result=dict(body=seal_files(products,label,archive),price=price,
                                                      executable=w.hf(bin),mode=mode,cost_domain=kind)
    assert b.verdict(bin,label+'-verdict',env,0)==oracle
    vis=td/'ron-visit';is_c=mode=='reuse'
    if vis.is_dir():
        cap=P/'untouched-real-census/ron-visit'
        assert (vis/'cargo-argv.nul').read_bytes()==(cap/'cargo-argv.nul').read_bytes()
        assert (vis/'loader-environment.json').read_bytes()==(cap/'loader-environment.json').read_bytes()
    if is_c:
        gate=(vis/'gate.tsv').read_text().strip();native=vis/'native.tsv'
        counts=collections.Counter(l.split()[0]for l in native.read_text().splitlines())if native.exists()else {}
        result.update(gate=gate,native=counts)
        if kind=='outside':
            assert gate.split()[0]=='outside-private-eligible-install' and not native.exists(),(gate,counts)
        elif kind=='unregistered-RX':
            assert gate.split()[0]=='codegen-map-invalidated' and gate.split()[2]!=gate.split()[3],gate
            assert 'unregistered executable <anonymous>' in (vis/'binding.tsv').read_text()
            assert counts.get('select',0)==0,counts
        else:
            assert gate.split()[:2]==['acquired','66'],gate
            assert counts.get('opt')==counts.get('emit')==10 and counts.get('select',0)==counts.get('replaced',0)==hits,counts
            logs=(vis/'binding.tsv').read_text().splitlines()
            assert len(logs)==21*16 and all(l.split()[1]=='bound'for l in logs[::16]),logs[:17]
            for group in [logs[i:i+16]for i in range(0,len(logs),16)]:
                assert {int(l.split()[0])for l in group[1:]}==set(range(15))
                assert all(int(l.split()[4])==1 for l in group[1:]if int(l.split()[0])!=12 or group[0].split()[0]!='start')
            term=(vis/'children.tsv').read_text().splitlines();assert len(term)==1 and int(term[0].split()[2])==0,term
    put(label+'/phase.json',result)
    return result

def external():
    assert os.environ['GITHUB_SHA']==os.environ['REVIEWED_HEAD'] and os.environ['GITHUB_RUN_ATTEMPT']=='1'
    assert sp.check_output(['git','-C',HERE,'rev-parse','HEAD'],text=True).strip()==os.environ['GITHUB_SHA']
    assert sp.check_output(['git','-C',o.REFERENCE,'rev-parse','HEAD'],text=True).strip()==o.PLAN['reference']
    assert w.git('rev-parse','HEAD')==b.NEW and w.git('rev-parse','HEAD^')==b.OLD and b.CMD==plan['command']
    assert shutil.disk_usage(w.root).free>45*2**30 and os.getuid()!=0
    put('registered.json',dict(plan=plan,boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        run=os.environ['GITHUB_RUN_ID'],head=os.environ['GITHUB_SHA'],order=os.environ['RON_BLOCK']))
    env=o.install()
    for name in ('exec_count','whole_count'):prepare.execute(['cc','-Wall','-Wextra','-Werror','-O2',o.REFERENCE/(name+'.c'),'-o',w.root/name])
    prepare.execute(['cc','-O2','-Wall','-Wextra','-Werror','-fPIC','-shared',o.HERE/'src/cargo-dispatch.c','-ldl','-o',w.root/'cargo-dispatch.so'])
    b.select(b.OLD);put('locked-registry.json.gz',b.inputs(env))
    graph=json.loads(sp.check_output(['cargo','+ohm','metadata','--format-version=1','--locked','--offline','--no-deps'],env=env,cwd=w.work))
    assert len(graph['workspace_members'])==len(graph['workspace_default_members'])==55 and sorted(graph['workspace_members'])==sorted(graph['workspace_default_members'])
    put('cargo-graph.json.gz',graph);baseline=b.inventory('ordinary-empty-old',env,graph)
    oracle=b.verdict(w.root/baseline['binary'],'old-verdict',env,0)
    cap,maps,inv=reference(env,graph)
    products,_=census_body('untouched-real-census',graph)
    archive=next(w.hf(f)for f in products if f.suffix=='.rlib')
    seal_files(products,'untouched-real-census',archive)
    rows=construct.scope(w.root,w.sdk,cap,maps)
    shutil.copy(w.root/'all-native/physical.json',P/'controlled-generations.json')
    direct('default-system-fallback','reuse',env,graph,archive,oracle,'outside')
    allowed=('HOME','USER','LANG','PATH','RUNNER_TEMP','GITHUB_WORKSPACE','GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','REVIEWED_HEAD','RON_BLOCK')
    proc={s:os.environ[s] for s in allowed if s in os.environ}
    assert not any('TOKEN'in k or 'SECRET'in k for k in env)
    context=w.root/'user-only.json';prepare.dump(context,dict(process=proc,cargo=env,oracle=oracle,archive=archive,
                      before=os.readlink('/proc/self/ns/mnt'),uid=os.getuid(),out=str(next(f for f in products if f.suffix=='.rlib'))))
    construct.enter_namespace(context,rows)

def in_namespace():
    assert os.getuid()==ctx['uid']!=0 and os.readlink('/proc/self/ns/mnt')!=ctx['before']
    status=Path('/proc/self/status').read_text();assert 'NoNewPrivs:\t1' in status and 'CapEff:\t0000000000000000' in status
    rows=read(P/'controlled-generations.json')['files'];assert len(rows)==15
    for row in rows:
        st=Path(row['name']).stat()
        assert (st.st_dev,st.st_ino,st.st_uid)==(row['dev'],row['ino'],ctx['uid']) and st.st_nlink==1
    put('native-mounts.json',dict(uid=os.getuid(),ns=os.readlink('/proc/self/ns/mnt'),status=status,
                                 mountinfo=Path('/proc/self/mountinfo').read_text()))
    env=ctx['cargo'];graph=json.loads(gzip.decompress((P/'cargo-graph.json.gz').read_bytes()));snap=ctx['archive'];good=ctx['oracle']
    cap=P/'untouched-real-census/ron-visit';role=prepare.cargo_role(cap,w.sdk);argv=role['argv']
    output=Path(argv[argv.index('--out-dir')+1]);suf,=[arg.split('=',1)[1]for arg in argv if arg.startswith('extra-filename=')]
    arc=output/('libron'+suf+'.rlib')
    assert arc.samefile(ctx['out']) and output.resolve().is_relative_to(w.root)
    opt=output/('.ron-native-'+suf+'.receipt');products=[arc,arc.with_suffix('.rmeta'),output/('ron'+suf+'.d'),opt]
    assert all(f.is_file()for f in products[:3]);esc=w.root/'private-donor-escrow';esc.mkdir()
    order=os.environ['RON_BLOCK'];assert order in ('PC','CP');results={}
    for arm in order:
        label='cold-ron-'+arm;stash=esc/label;stash.mkdir()
        for f in products:
            if f.exists():f.rename(stash/f.name)
        results[label]=direct(label,'stock'if arm=='P'else'reuse',env,graph,snap,good,'cold',0)
    if not opt.is_file():direct('independent-candidate-seed','reuse',env,graph,snap,good,'seed',0)
    assert opt.is_file();before=w.hf(opt)
    for kind in ('warm','whole'):
        for arm in order:
            label=kind+'-'+arm
            results[label]=direct(label,'stock'if arm=='P'else'reuse',env,graph,snap,good,kind,10)
    direct('unregistered-RX','reuse',dict(env,OHM_RON_PRIVATE_RX_CONTROL='1'),graph,snap,good,'unregistered-RX')
    assert w.hf(opt)==before
    put('complete.json',dict(results=results,receipt={'size':opt.stat().st_size,'allocated':opt.stat().st_blocks*512,'sha256':before},
                            archive={'size':arc.stat().st_size,'sha256':snap},phase_order=order))
if __name__=='__main__':
    if inside:in_namespace()
    else:external()
