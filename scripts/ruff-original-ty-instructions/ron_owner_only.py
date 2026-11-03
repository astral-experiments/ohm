"""Acquire the genuine workspace Ron role, then independently replay its signed foreign-span stores."""
from pathlib import Path
import gzip
import hashlib
import json
import os
import shutil
import signal
import subprocess as sp
import sys
import tarfile
import threading
import time
import zipfile
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import workspace29697 as b
from workspace_ron_probe import live_ron
from ron_observe import run

w = b.w
P = b.PROOF
ORIGINAL = 41621281440
HEAD = '5bbcf310dc4f1d1717d289cccdf4540df57b0c3f'
ARTIFACT = 13224910006
DIGEST = '3a03693ece5de011544ab69a6e3393a96856ffd9960f9662fb3ef51a507d7ec9'


def prior():
    endpoint = 'repos/astral-experiments/ohm/actions/'
    env = {'PATH':os.environ['PATH'],'HOME':os.environ['HOME'],'GH_TOKEN':os.environ['OHM_SDK_READ_TOKEN']}
    def get(where):
        return json.loads(sp.check_output(['gh','api',endpoint+where],env=env))
    original = get(f'runs/{ORIGINAL}')
    artifact = get(f'artifacts/{ARTIFACT}')
    assert original['head_sha']==HEAD and original['run_attempt']==1 and original['conclusion']=='failure'
    assert artifact['workflow_run']['id']==ORIGINAL and artifact['digest']=='sha256:'+DIGEST and not artifact['expired']
    path = w.root/'prior.zip'
    with path.open('xb') as fp:
        sp.run(['gh','api',endpoint+f'artifacts/{ARTIFACT}/zip'],stdout=fp,env=env,check=True)
    del env
    assert path.stat().st_size==artifact['size_in_bytes']==110549169 and w.hf(path)==DIGEST
    with zipfile.ZipFile(path) as z:
        assert len(z.namelist())==len(set(z.namelist()))
        result = {k:json.loads(z.read(v)) for k,v in {
            'owner':'new-untouched/ron-execution.json','env':'environment.json','previous_replay':'signed-ron-replay/inputs.json',
        }.items()}
        result['products']={k:hashlib.sha256(z.read('new-untouched/producer/'+k)).hexdigest() for k in ('rustc-d','metadata.rmeta','archive.rlib','dep-record')}
        result['graph']=json.loads(gzip.decompress(z.read('unit-graph.json.gz')))
    path.unlink()
    assert result['owner']['argv']==result['previous_replay']['original_argv']
    return result


def closure(graph):
    units=graph['units']
    ix,=[i for i,u in enumerate(units) if u['target']['name']=='ron' and u['target']['kind']==['lib']]
    assert units[ix]['features']==['default','std'] and units[ix]['mode']=='build'
    selected=set()
    def record(i):
        selected.add(i)
        u=dict(units[i])
        u['dependencies']=[{**{k:v for k,v in d.items() if k!='index'},'unit':record(d['index'])}for d in u['dependencies']]
        return u
    root=record(ix)
    return root,{units[i]['pkg_id']for i in selected}


def acquire(env):
    threads=[];errors=[];owners=[];rows=[]
    seen=threading.Event();stop=threading.Event()
    with (P/'partial-cargo.jsonl').open('xb')as so,(P/'partial.stderr').open('xb')as se:
        proc=sp.Popen(b.CMD,env=env,cwd=w.work,stdout=sp.PIPE,stderr=se,start_new_session=True)
        def drain():
            try:
                for ln in proc.stdout:
                    so.write(ln)
                    if ln.startswith(b'{'):
                        row=json.loads(ln)
                        if row.get('reason')=='compiler-artifact':
                            rows.append(row)
                            if row['package_id'].endswith('#ron@0.12.0') and row['target']['kind']==['lib']:
                                seen.set()
            except Exception as exc:
                errors.append(repr(exc));seen.set()
        for target,args in [(live_ron,(stop,owners)),(drain,())]:
            th=threading.Thread(target=target,args=args,daemon=True);th.start();threads.append(th)
        try:
            start=time.monotonic()
            while not seen.wait(.2):
                w.guard()
                assert proc.poll()is None and time.monotonic()-start<1800,('no published Ron',proc.returncode)
            assert not errors and len(owners)==1,errors
            pid,argv,childenv,cwd=owners[0]
            assert str(cwd).startswith(str(w.home)+'/registry/src/') and cwd.name=='ron-0.12.0'
            out=Path(argv[argv.index('--out-dir')+1])
            extra,=[v.split('=',1)[1]for v in argv if v.startswith('extra-filename=')]
            rlib=out/f'libron{extra}.rlib'
            meta=rlib.with_suffix('.rmeta')
            rustc_d=out/f'ron{extra}.d'
            translated=out.parent/'fingerprint/dep-lib-ron'
            for _ in range(200):
                if not Path(f'/proc/{pid}').exists() and all(p.is_file()for p in (rlib,meta,rustc_d,translated)):break
                time.sleep(.05)
            else:raise AssertionError((pid,list(out.glob('*')),translated))
            assert b'ohm-foreign-span-bytes' in rustc_d.read_bytes() and b'OBS1' in translated.read_bytes()
            report,=[r for r in rows if r['package_id'].endswith('#ron@0.12.0')and r['target']['kind']==['lib']]
            assert report['fresh']is False and any(Path(x).samefile(rlib)for x in report['filenames']if Path(x).is_file())
        finally:
            stop.set()
            if proc.poll()is None:os.killpg(proc.pid,signal.SIGTERM)
            proc.wait(timeout=30)
            for th in threads:th.join(timeout=10)
    assert not any(t.is_alive()for t in threads) and not errors
    b.write(P/'producer-acquisition.json',{'deliberately_stopped_at':report,'top_level_return':proc.returncode,'owner_pid':pid,'owner_argv':argv,'owner_cwd':str(cwd),'owner_env':childenv})
    return owners[0],(translated,rustc_d,meta,rlib),rows


def capsule(owner,products,rows,ids):
    # Keep the expansion's actual direct/transitive binary inputs for offline diagnostic replay.
    root = P/'role-inputs'
    root.mkdir()
    files = {}
    def keep(p):
        p=Path(p)
        assert p.is_file()and p.is_relative_to(w.root)
        if str(p) in files:return
        h=w.hf(p)
        files[str(p)]=h
        dest=root/h
        if not dest.exists():shutil.copyfile(p,dest)
    for p in products:keep(p)
    _,argv,_,_=owner
    for i,arg in enumerate(argv):
        if arg=='--extern':keep(argv[i+1].split('=',1)[1])
    for r in rows:
        if r['package_id']not in ids:continue
        for path in map(Path,r['filenames']):
            if path.is_file() and path.suffix in ('.rlib','.rmeta','.so'):keep(path)
    cache,=(w.home/'registry/cache').iterdir()
    for ron in ids:
        package,version=ron.rsplit('#',1)[1].split('@')
        keep(cache/(package+'-'+version+'.crate'))
    assert len(files)<200 and sum(p.stat().st_size for p in root.iterdir())<220*2**20
    b.write(P/'role-files.json',files)
    target=P/'role-files.tar.zst'
    with target.open('xb')as out:
        sp.run(['tar','--zstd','-cf','-','-C',root,'.'],check=True,stdout=out)
    shutil.rmtree(root)


def source_witness():
    d=json.loads(gzip.decompress((P/'signed-ron-replay/native-hits.json.gz').read_bytes()))
    refs={}
    for row in d['identities'].values():
        for _,_,name in row['object']['names']:
            p=Path(name)
            if not p.is_absolute() or not p.is_relative_to(w.home/'registry/src') or not p.is_file():continue
            index,crate,*rel=p.relative_to(w.home/'registry/src').parts
            archive=w.home/'registry/cache'/index/(crate+'.crate')
            assert archive.is_file()
            with tarfile.open(archive,'r:gz')as tar:
                data=tar.extractfile('/'.join([crate,*rel])).read()
            assert data==p.read_bytes()
            refs[name]={'physical_sha':w.hf(p),'crate_sha':w.hf(archive),'bytes':len(data),'source_file_id':row['object']['stable_id']}
    b.write(P/'source-witness.json',refs)


def main():
    assert os.environ['GITHUB_SHA']==os.environ['REVIEWED_HEAD'] and os.environ['GITHUB_RUN_ATTEMPT']=='1'
    assert w.hf(w.src/'sdk.json')==b.SPEC['sdk_manifest']and w.git('rev-parse','HEAD')==b.NEW and w.git('rev-parse','HEAD^')==b.OLD
    w.guard()
    b.write(P/'registration.json',{'original':ORIGINAL,'archive':DIGEST,'original_job':125867338745,'head':os.environ['GITHUB_SHA'],'run':os.environ['GITHUB_RUN_ID'],'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'registration':b.SPEC,'scope':'Unscored, full original Cargo role until the genuine Ron library completes, followed by one direct signed rustc with only the output directory changed. Fresh three-token jobserver pipe. No full workspace outcome or optimization.'})
    orig=prior()
    env=w.install()
    env['CARGO_LOG']='cargo::core::compiler::fingerprint=trace,cargo::compiler::fingerprint=trace'
    b.select(b.NEW)
    b.write(P/'locked-registry.json.gz',b.inputs(env))
    # Original workspace_ron_probe saved environment.json immediately before b.inputs,
    # which sets this variable after authenticating and fetching the complete lock.
    assert 'CARGO_NET_OFFLINE' not in orig['env'] and env['CARGO_NET_OFFLINE']=='true'
    orig['env']['CARGO_NET_OFFLINE']='true'
    diff={k:[env.get(k),orig['env'].get(k)] for k in set(env)|set(orig['env']) if env.get(k)!=orig['env'].get(k)}
    b.write(P/'environment.json',{'observed':env,'prior_diff':diff})
    assert not diff or set(diff)=={'PATH'},diff
    if diff:env['PATH']=orig['env']['PATH']
    graph=json.loads(sp.check_output([*b.CMD[:2],'-Zunstable-options',*b.CMD[2:-1],'--unit-graph'],cwd=w.work,env=env))
    assert len(graph['units'])==693
    root,ids=closure(graph)
    assert (root,ids)==closure(orig['graph'])
    b.write(P/'role-graph.json.gz',root)
    owner,products,rows=acquire(env)
    _,argv,_,_=owner
    differences=[(i,a,v)for i,(a,v) in enumerate(zip(orig['owner']['argv'],argv)) if a!=v]
    prior_products=orig['products']
    current={k:w.hf(f)for k,f in zip(['dep-record','rustc-d','metadata.rmeta','archive.rlib'],products)}
    b.write(P/'original-comparison.json',{'prior_source':HEAD,'prior_full_argv':orig['owner']['argv'],'current_full_argv':argv,'argv_differences':differences,'same_argv':argv==orig['owner']['argv'],'graph_equal':True,'previous_products':prior_products,'new_products':current,'same_cwd':str(owner[3])==orig['owner']['cwd']})
    capsule(owner,products,rows,ids)
    assert not w.git('status','--porcelain') and len(argv)==len(orig['owner']['argv'])
    run(owner,w.root,w.sdk,w.src,P,products)
    source_witness()
    assert sum(f.stat().st_size for f in P.rglob('*')if f.is_file())<300*2**20


if __name__=='__main__':main()
