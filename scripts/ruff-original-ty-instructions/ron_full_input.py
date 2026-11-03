"""Restore the complete previously collected Ron role, with one diagnostic native and span mutation."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess as sp
import sys
import tarfile
import zipfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import workspace29697 as b
from ron_native_guard import corrupt
from ron_causality import replace
w=b.w
P=b.PROOF
PRIOR=41623657148
A=13225550728
SHA='74933fe90daeb5b2b8d0b4ec48bd9d84356a7991028cf185c0734e744b930acc'
Q='ff195d83bf4875d8a9df6b5098839e9597007769'
DRIVER='53aecb7726b1863849a89c4260c169132f98d0d33ba62e0892a06739b6e32e52'
DSO='406b8448ec89af1429a3a253381c6d9176970deb874c1035e680264ba8df382b'
BITFLAGS='69754195d398d941cd88b96d81bd6a7d'
LOCK=b.SPEC['source'][b.NEW]['Cargo.lock']


def download():
    e={k:os.environ[k]for k in ('HOME','PATH')};e['GH_TOKEN']=os.environ['OHM_SDK_READ_TOKEN']
    prefix='repos/astral-experiments/ohm/actions/'
    def get(path):return json.loads(sp.check_output(['gh','api',prefix+path],env=e))
    r=get('runs/'+str(PRIOR));a=get('artifacts/'+str(A))
    assert r['head_sha']==Q and r['conclusion']=='success'and r['run_attempt']==1 and a['workflow_run']['id']==PRIOR and a['digest']=='sha256:'+SHA and not a['expired']
    f=w.root/'full-role.zip'
    with f.open('xb')as out:sp.run(['gh','api',prefix+'artifacts/'+str(A)+'/zip'],env=e,stdout=out,check=True)
    assert f.stat().st_size==a['size_in_bytes']==9446924 and w.hf(f)==SHA
    return f


def restore(z):
    read=lambda k:json.loads(z.read(k))
    reg=read('registration.json');assert reg['head']==Q and reg['run']==str(PRIOR)
    files=read('role-files.json');acq=read('producer-acquisition.json');rh=read('signed-ron-replay/inputs.json');r=read('signed-ron-replay/actual.json');witness=read('source-witness.json')
    assert len(files)==36 and len(set(files.values()))<=36
    providers={h:[]for h in files.values()}
    for name,h in files.items():
        p=Path(name)
        assert any(p.is_relative_to(d)for d in(w.home/'registry/cache',w.target,w.shared))and '..'not in p.parts
        providers[h].append(p)
    archive=w.root/'role-files.tar.zst'
    with z.open('role-files.tar.zst')as inp,archive.open('xb')as out:shutil.copyfileobj(inp,out)
    tmp=w.root/'blob';tmp.mkdir()
    child=sp.Popen(['zstd','-q','-dc',archive],stdout=sp.PIPE)
    seen=set();total=0
    with tarfile.open(fileobj=child.stdout,mode='r|')as tf:
        for item in tf:
            if item.isdir() and item.name=='.':continue
            h=item.name.removeprefix('./');assert item.isfile()and h in providers and h not in seen
            total+=item.size;assert total<220*2**20
            dest=tmp/h
            with tf.extractfile(item)as inp,dest.open('xb')as out:shutil.copyfileobj(inp,out)
            assert w.hf(dest)==h
            for p in providers[h]:
                assert not p.exists();p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(dest,p)
            seen.add(h)
    assert child.wait()==0 and seen==set(providers)
    locked=__import__('tomllib').loads((w.work/'Cargo.lock').read_text())['package']
    checks={p['name']+'-'+p['version']+'.crate':p['checksum']for p in locked if 'checksum'in p}
    n=0
    for dirs in providers.values():
        for p in dirs:
            if p.suffix!='.crate':continue
            assert w.hf(p)==checks[p.name]and p.parent.parent==w.home/'registry/cache'
            dest=w.home/'registry/src'/p.parent.name;dest.mkdir(parents=True,exist_ok=True)
            with tarfile.open(p,'r:gz')as tf:
                for m in tf.getmembers():
                    npath=Path(m.name)
                    assert npath.parts[0]==p.stem and not npath.is_absolute()and '..'not in npath.parts and (m.isfile()or m.isdir())
                tf.extractall(dest,filter='data')
            n+=1
    assert n==11 and all(w.hf(Path(k))==v['physical_sha']and v['source_file_id']==BITFLAGS for k,v in witness.items())
    assert acq['owner_argv']==rh['original_argv'] and all(not any(w in k for w in('TOKEN','PASSWORD','SECRET'))for k in acq['owner_env'])
    return acq,rh,r


def stage(name,mode,owner,argv,driver,wrapper):
    folder=P/name;folder.mkdir()
    cwd=Path(owner['owner_cwd']);out=Path(argv[argv.index('--out-dir')+1])
    assert out==w.root/'ron-replay/private-out'
    out.mkdir(parents=True,exist_ok=True)
    for p in out.iterdir():assert p.is_file()and not p.is_symlink();p.unlink()
    env=dict(owner['owner_env'],OHM_LICENSED_RUSTC=argv[0],OHM_F_JOBSERVER_PROOF=str(folder/'jobserver.json'),OHM_REAL_RON_PROBE=str(folder))
    b.write(folder/'plan.json',dict(argv=argv,driver=str(driver),signed_driver=DRIVER,source_id=BITFLAGS,mode=mode))
    cmd=[str(wrapper),*argv]
    if mode:
        script=folder/'run.gdb'
        script.write_text(f"""set confirm off
set python print-stack full
set pagination off
set disable-randomization off
set startup-with-shell on
set exec-wrapper {wrapper}
set debuginfod enabled off
set auto-load off
set auto-solib-add off
set print thread-events off
handle SIGUSR1 nostop noprint pass
start
python
exec(compile(open({str(HERE/'ron_return_probe.py')!r}).read(), {str(HERE/'ron_return_probe.py')!r}, 'exec'))
end
continue
python finish()
""")
        cmd=['gdb','-q','-nx','-nh','-batch','-x',str(script),'--args',*argv]
    w.guard()
    with (folder/'stdout').open('xb')as so,(folder/'stderr').open('xb')as se:
        proc=sp.run(cmd,env=env,cwd=cwd,stdout=so,stderr=se,timeout=420)
    raw=(folder/'stderr').read_text()
    assert 'failed to connect to jobserver'not in raw
    diags=[json.loads(l)for l in raw.splitlines()if l.startswith('{')]
    errors=[m for m in diags if m.get('level')=='error'and m.get('code')]
    spans=[{
        'code':m['code']['code'],'msg':m['message'],'file':s['file_name'],'start':s['byte_start'],'end':s['byte_end'],
        'source_range':[s['line_start'],s['column_start'],s['line_end'],s['column_end']],
        'macro':s['expansion']['macro_decl_name']if s.get('expansion') else None,
    } for m in errors for s in m['spans']if s['is_primary']]
    products={p.name:w.hf(p)for p in out.iterdir()if p.is_file()}
    rec={'return':proc.returncode,'stage':name,'argv0':argv[0],'products':products,'errors':spans}
    if mode:
        rec['bridge']=json.loads((folder/'returns.json').read_bytes())
        assert proc.returncode==0 and rec['bridge']['exit_codes']==[1]
    b.write(folder/'result.json',rec)
    return rec


def main():
    assert os.environ['GITHUB_SHA']==os.environ['REVIEWED_HEAD']and os.environ['GITHUB_RUN_ATTEMPT']=='1'
    assert w.hf(w.src/'sdk.json')==b.SPEC['sdk_manifest']and w.git('rev-parse','HEAD')==b.NEW and w.git('rev-parse','HEAD^')==b.OLD and w.hf(w.work/'Cargo.lock')==LOCK
    w.guard();b.write(P/'registration.json',{'head':os.environ['GITHUB_SHA'],'run':os.environ['GITHUB_RUN_ID'],'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'prior_run':PRIOR,'prior_artifact':A,'prior_digest':SHA,'sdk':b.SPEC['sdk_manifest'],'source':b.NEW,'lock':LOCK,'full_role_dso':DSO,'scope':'No Cargo or complete-workspace claim. Rehydrate 36 actual paths from the signed producer. Independently compile a healthy, malformed and repaired Ron. In two diagnostic malformed controls alter at most the returned 8-byte Span at the three preimage-checked sites; preserve Some tag, compiler policy and malformed native DSO.'})
    f=download();w.install()
    with zipfile.ZipFile(f)as z:owner,rh,r=restore(z)
    argv=rh['replay_argv']
    assert Path(argv[0]).samefile(w.sdk/'bin/rustc')and not any(s.startswith('incremental=')for s in argv)
    dso,=[Path(v.split('=',1)[1])for i,v in enumerate(argv)if i and argv[i-1]=='--extern'and v.startswith('serde_derive=')]
    driver,=(w.sdk/'lib').glob('librustc_driver*.so');assert w.hf(driver)==DRIVER and w.hf(dso)==DSO and dso.is_relative_to(w.target)
    wrapper=w.root/'exact-jobserver';shutil.copyfile(HERE/'ron_jobserver.py',wrapper);wrapper.chmod(0o700)
    rows={}
    def go(tag,mode=None):
        q=stage(tag,mode,owner,argv,driver,wrapper)
        rows[tag]=q;b.write(P/'histories.json',rows);return q
    healthy=go('signed-healthy')
    library,=[name for name in healthy['products']if name.endswith('.rlib')]
    assert healthy['return']==0 and not healthy['errors']and healthy['products'][library]==r['rlib_replayed']
    good=dso.read_bytes();bad,desc=corrupt(good)
    assert desc['normal']==DSO
    b.write(P/'full-malformed-so.json',desc)
    stamp=dso.stat()
    replace(dso,bad,good)
    try:
        direct=go('signed-malformed');assert direct['return']==1 and library not in direct['products']and len(direct['errors'])>0
        normal=go('inspect-malformed','unchanged')
        changed=go('clamp-return-malformed','first-operand')
        assert normal['errors']==direct['errors']and library not in normal['products']and library not in changed['products']
    finally:
        assert dso.read_bytes()==bad and dso.stat().st_ino==stamp.st_ino and dso.stat().st_mtime_ns==stamp.st_mtime_ns
        replace(dso,good,bad)
    repair=go('signed-repair')
    assert repair['return']==0 and repair['products'][library]==healthy['products'][library]and not repair['errors']
    key=lambda q:[i for i in q['errors']if i['file'].endswith('/bitflags-2.13.2/src/public.rs')]
    change={'normal':key(normal),'changed':key(changed),'full_native_sha':DSO,'malformed_native_sha':desc['malformed'],'normal_counts':len(normal['bridge']['returns']),'synthetic_mutation_count':sum(x['original']!=x['returned']for x in changed['bridge']['returns']),'same_all_native_bits_on_repair':repair['products'][library]==healthy['products'][library]}
    b.write(P/'diagnostic-scope.json',change)
    assert all(i['code']=='E0782'for i in normal['errors']) and any(i['source_range']==[17,37,17,98] for i in change['normal'])
    assert sorted((i['code'],i['msg'])for i in normal['errors'])==sorted((i['code'],i['msg'])for i in changed['errors'])
    assert not w.git('status','--porcelain')
    assert sum(f.stat().st_size for f in P.rglob('*')if f.is_file())<25*2**20

if __name__=='__main__':main()
