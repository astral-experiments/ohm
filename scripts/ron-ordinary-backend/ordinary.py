"""Two fresh hosted histories of a normal Ruff test build on the published Linux -24 SDK."""
from pathlib import Path
from collections import Counter
import gzip
import hashlib
import json
import os
import shutil
import subprocess as sp
import sys
import tarfile
import threading
import time

HERE=Path(__file__).resolve().parent
REFERENCE=Path(os.environ['GITHUB_WORKSPACE'])/'reference/scripts/ruff-original-ty-instructions'
sys.path.insert(0,str(REFERENCE))
sys.path.insert(0,str(HERE))
import prepare
import workspace29697 as b
w=b.w
P=w.proof
M=json.loads((HERE/'release-compiler.json').read_bytes())
PUB=json.loads((HERE/'release-published.json').read_bytes())
PLAN=json.loads((HERE/'registration.json').read_bytes())

def install():
    name='ohm-1.99.0-24-x86_64-unknown-linux-gnu.tar.gz'
    spec=PUB['assets'][name]
    assert spec['id']==707031606 and spec['sha256']=='sha256:'+M['tar_sha256'] and len(M['members'])==79
    env={'PATH':os.environ['PATH'],'HOME':os.environ['HOME'],'GH_TOKEN':os.environ.pop('OHM_SDK_READ_TOKEN')}
    api='repos/astral-experiments/ohm/releases/assets/'+str(spec['id'])
    row=json.loads(sp.check_output(['gh','api',api],env=env))
    assert row['digest']==spec['sha256'] and row['size']==spec['bytes'] and row['name']==name
    archive=w.root/name
    with archive.open('xb')as out:sp.run(['gh','api',api,'-H','Accept: application/octet-stream'],env=env,stdout=out,check=True)
    del env
    assert w.hf(archive)==M['tar_sha256'] and archive.stat().st_size==spec['bytes']
    w.sdk.mkdir()
    lookup={r['source']:(k,r) for k,r in M['members'].items()}
    found={}
    with tarfile.open(archive,'r|gz')as tar:
        for member in tar:
            if member.name not in lookup:continue
            k,r=lookup[member.name];dst=w.sdk/k
            assert k not in found and not Path(k).is_absolute() and '..' not in Path(k).parts and member.isfile()
            dst.parent.mkdir(parents=True,exist_ok=True)
            with tar.extractfile(member) as src,dst.open('xb')as out:shutil.copyfileobj(src,out)
            dst.chmod(member.mode&0o777)
            assert dst.stat().st_size==r['bytes'] and w.hf(dst)==r['sha256'] and dst.stat().st_nlink==1
            found[k]=[r['sha256'],member.mode&0o777,dst.stat().st_dev,dst.stat().st_ino]
    assert set(found)==set(M['members'])
    e={k:os.environ[k] for k in ('HOME','USER','PATH','LANG')if k in os.environ}
    e.update(RUSTUP_HOME=str(w.ru),CARGO_HOME=str(w.home),CARGO_TARGET_DIR=str(w.target),CARGO_BUILD_BUILD_DIR=str(w.shared),CARGO_NET_GIT_FETCH_WITH_CLI='true')
    sp.run(['rustup','toolchain','link','ohm',w.sdk],env=e,check=True)
    versions={}
    for program,revision in [('rustc','f5a51d8cc3e76236c2d0f17d495d59ebb03306e4'),('cargo','abc70d60a6fd89c10d5f65cf85820d9b78d5affe')]:
        vv=sp.check_output([program,'+ohm','-vV'],text=True,env=e);assert revision in vv
        versions[program]=vv
    b.write(P/'sdk-24.json',{'archive':spec,'files':found,'versions':versions})
    return e

def census(label):
    td=P/label
    proof=json.loads(gzip.decompress((td/'owner-census.json.gz').read_bytes()))
    roles=[r for r in proof['roles']if r['trigger']=='exec']
    compiler=[r for r in roles if r['mode']in ('full','metadata','test','link-only')]
    ron=[r for r in compiler if r['crate']=='ron' and r['mode']=='full']
    for x in compiler:
        f=td/'tasks'/x['argv'];assert w.hf(f)==x['argv_sha256']
        a=f.read_bytes().split(b'\0')[4:]
        assert not a[-1]
        x['parameters']=hashlib.sha256(b'\0'.join(a[1:])).hexdigest()
    return ron,sorted((r['mode'],r['crate'],r['parameters']) for r in compiler),dict(Counter(r['mode']for r in roles))

def main():
    assert os.environ['GITHUB_SHA']==os.environ['REVIEWED_HEAD'] and os.environ['GITHUB_RUN_ATTEMPT']=='1'
    assert sp.check_output(['git','-C',HERE,'rev-parse','HEAD'],text=True).strip()==os.environ['GITHUB_SHA']
    assert sp.check_output(['git','-C',REFERENCE,'rev-parse','HEAD'],text=True).strip()==PLAN['reference']
    order=os.environ['RON_BLOCK'];assert order in ('PC','CP')
    assert w.git('rev-parse','HEAD')==b.NEW and w.git('rev-parse','HEAD^')==b.OLD
    assert b.CMD==PLAN['command'] and shutil.disk_usage(w.root).free>45*2**30
    b.write(P/'registered.json',{'plan':PLAN,'head':os.environ['GITHUB_SHA'],'block':order,'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'run':os.environ['GITHUB_RUN_ID'],'cpus':sorted(os.sched_getaffinity(0))})
    env=install()
    for name in ['exec_count','whole_count']:sp.run(['cc','-Wall','-Wextra','-Werror','-O2',REFERENCE/(name+'.c'),'-o',w.root/name],check=True)
    shim=w.root/'cargo-dispatch.so';sp.run(['cc','-O2','-Wall','-Wextra','-Werror','-fPIC','-shared',HERE/'src/cargo-dispatch.c','-ldl','-o',shim],check=True)
    b.select(b.OLD);b.write(P/'locked-registry.json.gz',b.inputs(env))
    graph=json.loads(sp.check_output(['cargo','+ohm','metadata','--format-version=1','--locked','--offline','--no-deps'],env=env,cwd=w.work))
    assert sorted(graph['workspace_default_members'])==sorted(graph['workspace_members'])
    assert sorted(x['name'] for x in graph['packages']if x['id']in graph['workspace_default_members'])==b.SPEC['default_members']
    b.write(P/'cargo-metadata.json.gz',graph)
    actor=w.root/'native-actor';saved=w.root/'ron-snapshots';saved.mkdir()
    snapshots={}
    bodies=P/'ron-native-objects';bodies.mkdir()
    def env_for(label,mode):
        visit=P/label/'ron-visit'
        return dict(env,LD_PRELOAD=str(shim),OHM_CAPTURE_DISPATCH=str(shim),OHM_CAPTURE_RECEIVER=str(HERE/'receiver.py'),OHM_CAPTURE_CARGO=str(w.sdk/'bin/cargo'),OHM_CAPTURE_ACTION=mode,OHM_CAPTURE_ACTOR=str(actor),OHM_CAPTURE_VISIT=str(visit))
    def note(label,inventory):
        dest=saved/label;dest.mkdir()
        logical=[k for k in inventory['workspace_artifacts_and_ron']if Path(k).name.startswith('libron-') and Path(k).suffix in ('.rlib','.rmeta')]
        assert sorted(Path(k).suffix for k in logical)==['.rlib','.rmeta'],logical
        for rel in logical:
            f=w.root/rel;shutil.copyfile(f,dest/f.name);assert w.hf(dest/f.name)==inventory['workspace_artifacts_and_ron'][rel][1]
        for item in dest.iterdir():
            seal=bodies/(w.hf(item)+'.zst')
            if not seal.exists():
                with seal.open('xb')as output:sp.run(['zstd','-q','-3','-c',item],stdout=output,check=True)
        snapshots[label]=dest
    old=b.inventory('ordinary-empty-old',env,graph);note('ordinary-empty-old',old)
    good=b.verdict(w.root/old['binary'],'old-verdict',env,0);oldelf=w.root/'old-before-edit';shutil.copy2(w.root/old['binary'],oldelf)
    # This off-clock kernel census is the one phase where the external sampler also reads live maps.
    stop=threading.Event();maps={};sampling=[]
    def watch():
        while not stop.is_set():
            for proc in Path('/proc').glob('[0-9]*'):
                try:
                    if not (proc/'exe').samefile(w.sdk/'bin/rustc'):continue
                    av=(proc/'cmdline').read_bytes().split(b'\0')
                    if b'--crate-name' not in av or av[av.index(b'--crate-name')+1]!=b'ron':continue
                    ts=time.monotonic_ns();rows=(proc/'maps').read_text().splitlines();image=[]
                    for line in rows:
                        v=line.split(None,5)
                        if len(v)==6 and 'x'in v[1] and v[5].startswith('/'):
                            path=Path(v[5]);st=path.stat()
                            if not path.is_file():continue
                            k=(v[5],v[3],int(v[4]));image.append(k)
                            maps.setdefault(k,[st.st_size,st.st_uid,st.st_nlink,st.st_mtime_ns,st.st_ctime_ns])
                    sampling.append([ts,proc.name,image])
                except (OSError,IndexError):continue
            stop.wait(0.03)
    thread=threading.Thread(target=watch);thread.start()
    try:
        normal=b.inventory('ordinary-repeat',env,graph,'census');note('ordinary-repeat',normal)
    finally:stop.set();thread.join()
    for key,attr in maps.items():
        f=Path(key[0]);a=f.stat();assert a.st_ino==key[2] and a.st_size==attr[0]
        attr.append(w.hf(f))
    b.write(P/'ordinary-live-maps.json.gz',{'files':[[*k,*v]for k,v in maps.items()],'samples':sampling})
    ron,roster,tally=census('ordinary-repeat')
    initial={'ordinary_full_ron':len(ron),'actual':tally,'typed':len(normal['units'])}
    b.write(P/'ordinary-eligibility.json',initial)
    if not ron:
        b.write(P/'decision.json',{'ordinary':initial,'outcome':'published compiler already avoids this role; stop','qualified':False})
        return
    assert len(ron)==1 and tally.get('Wild',0)>0 and sampling
    sham=b.inventory('kernel-sham',env_for('kernel-sham','observe'),graph,'census');note('kernel-sham',sham)
    sh_ron,sh_roster,sh_tally=census('kernel-sham');assert len(sh_ron)==1 and [r for r in sh_roster if r[0]!='link-only']==[r for r in roster if r[0]!='link-only']
    assert Counter((r[0],r[1])for r in sh_roster)==Counter((r[0],r[1])for r in roster) and sh_tally['Wild']==tally['Wild']
    cap=P/'kernel-sham/ron-visit'; bound=prepare.build(actor,w.sdk,cap);b.write(P/'bound-actor.json',bound)
    # Kernel argv begins at argv[0], dispatcher also recorded its separately supplied executable.
    rx=(P/'ordinary-repeat/tasks'/ron[0]['argv']).read_bytes().split(b'\0')
    dispatch=(cap/'cargo-argv.nul').read_bytes().split(b'\0')[1:]
    assert rx[5:]==dispatch[1:] and Path(os.fsdecode(rx[4])).samefile(w.sdk/'bin/rustc')
    seen={}
    def candidate(label,mode,kind='whole'):
        out=b.inventory(label,env_for(label,mode),graph,kind);note(label,out)
        v=P/label/'ron-visit';data=(v/'cargo-argv.nul').read_bytes();assert data==(cap/'cargo-argv.nul').read_bytes()
        terms=(v/'children.tsv').read_text().strip().splitlines()
        native=(v/'native.tsv').read_text().splitlines() if (v/'native.tsv').exists()else []
        counts=dict(Counter(row.split('\t')[0]for row in native))
        if mode=='reuse':
            assert (v/'gate.tsv').read_text().split()[:2]==['acquired','66']
            assert len((v/'binding.tsv').read_text().splitlines())==4
            assert counts.get('opt')==counts.get('emit')==10
            hits=0 if label=='seed-empty-receipt' else 10
            assert counts.get('select',0)==counts.get('replaced',0)==hits,counts
        hw=json.loads((P/label/'hardware.json').read_bytes()) if kind=='whole' else None
        seen[label]={'mode':mode,'hardware':hw,'native':counts,'child_status':terms}
        b.write(P/label/'ron-result.json',seen[label]);return out
    seed=candidate('seed-empty-receipt','reuse')
    assert seen['seed-empty-receipt']['native'].get('select',0)==0
    for role in order:
        name='warm-'+role
        if role=='P':
            res=b.inventory(name,env,graph);note(name,res)
            seen[name]={'mode':'unmodified Cargo and rustc','hardware':json.loads((P/name/'hardware.json').read_bytes())}
        else:res=candidate(name,'reuse')
        assert b.verdict(w.root/res['binary'],name+'-verdict',env,0)==good
    cp=candidate('candidate-physical','reuse','census')
    c_ron,c_roster,c_tally=census('candidate-physical')
    assert len(c_ron)==1 and c_ron[0]['parameters']==ron[0]['parameters'] and Counter((r[0],r[1])for r in c_roster)==Counter((r[0],r[1])for r in roster) and c_tally['Wild']==tally['Wild']
    b.select(b.NEW);assert b.verdict(oldelf,'old-on-new',env,101)==good
    edit=candidate('actual-edit','reuse');assert b.verdict(w.root/edit['binary'],'actual-edit-verdict',env,0)==good
    ed_warm=candidate('edited-warm','reuse');assert b.verdict(w.root/ed_warm['binary'],'edited-warm-verdict',env,0)==good
    source=w.work/'crates/ty_server/src/session.rs';original=source.read_bytes()
    invalid=P/'native-invalid-workspace';invalid.mkdir()
    try:
        source.write_bytes(original+b'\nconst _: u8 = "invalid workspace build";\n')
        b.run(b.CMD,env_for('native-invalid-workspace','reuse'),invalid,101)
        messages=[json.loads(l)for l in (invalid/'stdout.jsonl').read_bytes().splitlines()]
        assert messages[-1]=={'reason':'build-finished','success':False}
        assert any(m['reason']=='compiler-message' and (m['message'].get('code') or {}).get('code')=='E0308' for m in messages)
        assert not any(m['reason']=='compiler-artifact' and 'ty_server' in m['package_id'] and m['target']['kind']==['test'] and m['target']['name']=='e2e' for m in messages)
    finally:source.write_bytes(original)
    repair=candidate('workspace-repair','reuse');assert b.verdict(w.root/repair['binary'],'workspace-repair-verdict',env,0)==good
    # Both complete previous trees remain under custody. The next build begins at the same unpopulated visible paths.
    assert shutil.disk_usage(w.root).free>45*2**30
    for x in (w.target,w.shared):
        assert x.parent==w.root and x.is_dir() and not x.is_symlink();x.rename(w.root/('finished-'+x.name))
    clean=b.inventory('independent-new',env,graph);note('independent-new',clean)
    assert b.verdict(w.root/clean['binary'],'independent-new-verdict',env,0)==good
    old_rlib={w.hf(next(snapshots[k].glob('*.rlib')))for k in ('ordinary-repeat','kernel-sham','seed-empty-receipt','warm-P','warm-C','candidate-physical')}
    assert len(old_rlib)==1,old_rlib
    sys.path.insert(0,str(HERE.parent/'ron-consumed-metadata'));import consumer
    args=dispatch[:-1];search=[x for i,item in enumerate(args[:-1])if item==b'-L' and args[i+1].startswith(b'dependency=')for x in ('-L',os.fsdecode(args[i+1]))]
    assert search
    actual=consumer.run(w.root/'readers',env,search,snapshots)
    b.write(P/'ron-reader-results.json',actual);shutil.copyfile(w.root/'readers/invalid.stderr',P/'ron-reader-invalid.stderr')
    assert len({r['ELF']for r in actual['physical_artifacts'].values()})==1
    oldexe=old['executables'][old['binary']]['elf']['sha256'];newexe=edit['executables'][edit['binary']]['elf']['sha256'];cleanexe=clean['executables'][clean['binary']]['elf']['sha256']
    all_slots={'old':old,'normal-repeat':normal,'sham':sham,'candidate':cp,'edited':edit,'edited-repeat':ed_warm,'clean':clean}
    b.write(P/'native-comparisons.json',{k:{n:r['elf']['sha256']for n,r in s['executables'].items()}for k,s in all_slots.items()})
    assert oldexe!=newexe and newexe==cleanexe and w.hf(next(snapshots['actual-edit'].glob('*.rlib')))==w.hf(next(snapshots['independent-new'].glob('*.rlib')))
    objects=P/'ron-native-objects';assert objects.is_dir()
    for f in [*saved.glob('*/*'),*list((w.root/'readers').glob('*/reader'))]:
        dst=objects/(w.hf(f)+'.zst')
        if not dst.exists():
            with dst.open('xb')as out:sp.run(['zstd','-q','-3','-c',f],stdout=out,check=True)
    assert not w.git('status','--porcelain')
    b.write(P/'decision.json',{'qualified':True,'kind':'diagnostic whole Cargo hardware, no source compiler','ordinary':initial,'prices':seen,'e2e':[oldexe,newexe,cleanexe],'reader':actual,'outside_rustc':True})

if __name__=='__main__':main()
