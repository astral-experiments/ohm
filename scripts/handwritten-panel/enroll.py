"""Authenticate the two successful same-run stage1 archives and complete each SDK with fixed signed tools."""
import json,os,re,shutil,subprocess,sys,tarfile
from pathlib import Path,PurePosixPath
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parent))
import material as m
REPO='astral-experiments/ohm';BR='charlie/codex-20988-handwritten-stage1';HOST='x86_64-unknown-linux-gnu'
ROLES=('fa7a_stack_ctfe318','fa7a_stack_ctfe318_handwritten')
def lock(run,jobs,art):
    rid=run['id'];head=run['head_sha'];pins=m.read(m.HERE/'builder-files.json');m.guard((rid,head)==(pins['reviewed_run'],pins['reviewed_head']),'unregistered producing run/head')
    m.guard(type(rid)is int and rid>0 and re.fullmatch('[0-9a-f]{40}',head) and run['repository']['full_name']==run['head_repository']['full_name']==REPO and run['repository']['private'] is True and
            run['head_branch']==BR and run['path']=='.github/workflows/ci.yml' and run['event']=='workflow_dispatch' and run['run_attempt']==1 and run['status']=='completed' and run['conclusion']=='success','unqualified producer')
    js=jobs['jobs'];arts=art['artifacts'];m.guard(len(js)==jobs['total_count']==len(arts)==art['total_count']==2,'missing/extra producer/role')
    labels={f'Handwritten stage1 SDK ({r})'for r in ROLES};m.guard({j['name']for j in js}==labels and all(j['status']=='completed' and j['conclusion']=='success' and j['run_attempt']==1 and j['head_sha']==head and j['run_id']==rid for j in js),'foreign/failed stage1 job')
    items={}
    for role in ROLES:
        name='handwritten-stage1-'+role;a,=[v for v in arts if v['name']==name]
        m.guard(not a['expired'] and a['workflow_run']['id']==rid and a['workflow_run']['head_sha']==head and a['workflow_run']['head_branch']==BR and isinstance(a['id'],int) and a['id']>0 and re.fullmatch('sha256:[0-9a-f]{64}',a['digest']) and 30<<20<a['size_in_bytes']<1060<<20,'foreign/unsigned SDK')
        items[role]={'id':a['id'],'bytes':a['size_in_bytes'],'sha256':a['digest'][7:]}
    m.guard(len({z['id']for z in items.values()})==len({z['sha256']for z in items.values()})==2,'duplicate role input')
    return {'repo':REPO,'rid':rid,'attempt':1,'head':head,'branch':BR,'jobs':{j['name']:j['id']for j in js},'roles':items}
def safe_name(name):
    p=PurePosixPath(name);return not p.is_absolute() and name==p.as_posix() and len(name)<240 and '..' not in p.parts and '\\' not in name and not any(ord(c)<32 for c in name)
def unpack(archive,dest,role):
    dest.mkdir();extras={'allocator.log'} if role==ROLES[1] else set()
    must={'commands.json','unit.log','run-make.log','build.log','rustc-vV.txt','bootstrap.toml','source.json','original-signed-source-verifier.log','capacity-initial.txt','sdk-inventory.json','role.json','identity.json','sdk.tar.zst'}|extras
    with ZipFile(archive) as z:
        members=z.infolist();m.guard(len(members)==len(must) and {i.filename for i in members}==must,'unexpected stage1 package')
        for i in members:
            n=i.filename;m.guard(safe_name(n) and not i.is_dir() and (i.external_attr>>16)&0o170000 in (0,0o100000) and not i.flag_bits&1 and 0<i.file_size<(1000<<20 if n=='sdk.tar.zst' else 32<<20),'bad archive member')
            with z.open(i) as a,(dest/n).open('xb') as b:shutil.copyfileobj(a,b,1<<20)
def extract(artifact,sdk):
    inventory=m.read(artifact/'sdk-inventory.json');m.guard(30<=len(inventory)<=250 and sum(x['bytes']for x in inventory.values())<4<<30,'unbounded result');seen=set();sdk.mkdir()
    decoder=subprocess.Popen(['zstd','-q','-dc','--',str(artifact/'sdk.tar.zst')],stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=decoder.stdout,mode='r|') as tar:
            for item in tar:
                n=item.name;m.guard(safe_name(n) and n in inventory and n not in seen and item.isfile() and not item.linkname and item.size==inventory[n]['bytes'] and item.mode==inventory[n]['mode'] in (0o644,0o755) and 0<item.size<1<<30,'file unregistered or unsafe')
                f=sdk/n;f.parent.mkdir(parents=True,exist_ok=True)
                with tar.extractfile(item) as a,f.open('xb') as b:shutil.copyfileobj(a,b,1<<20)
                m.guard(f.stat().st_size==item.size and m.filesha(f)==inventory[n]['sha256'],'extracted bytes');f.chmod(item.mode);seen.add(n)
        # Drain the harmless tar trailer before waiting, including a truncated frame check.
        while decoder.stdout.read(65536):pass
        m.guard(decoder.wait(timeout=60)==0 and seen==set(inventory),'incomplete source SDK')
    finally:
        if decoder.poll() is None:decoder.kill();decoder.wait()
    return inventory
def signed(pool,archive):
    wanted=m.read(m.HERE/'helpers.json');seen={};assert len(wanted)==8
    with tarfile.open(archive,'r|gz') as tar:
        for it in tar:
            p=PurePosixPath(it.name)
            if len(p.parts)<3 or p.parts[0]!='rust-1.99.0-dev-'+HOST:continue
            rel='/'.join(p.parts[2:]);comp=p.parts[1]
            if rel not in wanted or comp!=('cargo'if rel=='bin/cargo' else 'rustc'):continue
            row=wanted[rel];assert rel not in seen and it.isfile() and it.size==row['bytes'] and it.mode&0o111
            f=pool/rel;f.parent.mkdir(parents=True,exist_ok=True)
            with tar.extractfile(it) as a,f.open('xb') as b:shutil.copyfileobj(a,b,1<<20)
            f.chmod(0o755);assert m.filesha(f)==row['sha256'];seen[rel]=f
    m.guard(seen.keys()==wanted.keys(),'missing signed Cargo/Wild/helper');return seen
def check_archive(role,origin,stage,ctx,buildpin):
    rr=m.read(origin/'role.json');arm=stage.S['arms'][role];meta=m.read(origin/'source.json');ident=m.read(origin/'identity.json')
    stage.match_source(meta,role,ctx);m.guard(rr['source']==arm and rr['github']==ctx and rr['role']==role and rr['carrier_sha256']==buildpin and rr['archive_sha256']==m.filesha(origin/'sdk.tar.zst') and rr['archive_bytes']==(origin/'sdk.tar.zst').stat().st_size,'builder material')
    m.guard(rr['qa']=={v.name:m.filesha(v)for v in origin.iterdir() if v.name not in ('role.json','sdk.tar.zst')},'native QA receipt')
    for label in (('unit','run-make','allocator') if role==ROLES[1] else ('unit','run-make')):stage.passed((origin/(label+'.log')).read_bytes(),label,role)
    stage.verified_version(ident['rustc_vV'],arm['commit'])
    opts=m.read(origin/'commands.json');m.guard(opts['build'][-3:]==['compiler/rustc','library','src/tools/rustdoc'] and 'optimize = true' in (origin/'bootstrap.toml').read_text() and 'lto = "off"' in (origin/'bootstrap.toml').read_text(),'different source stage1 recipe')
    return ident
def main():
    if len(sys.argv)==5 and sys.argv[1]=='lock':
        sys.stdout.buffer.write(m.canon(lock(*(m.read(Path(x)) for x in sys.argv[2:])))+b'\n');return
    w,tmp=m.host();assert sys.argv[1:]==['admit'];_,prev=m.check_sources(w);old=m.load('previous_release_intake',prev/'intake.py')
    rid=os.environ['BUILD_RUN_ID'];head=os.environ['BUILD_HEAD'];pin=os.environ['SDK_LOCK_SHA256'];assert re.fullmatch('[1-9][0-9]*',rid) and re.fullmatch('[0-9a-f]{40}',head) and re.fullmatch('[0-9a-f]{64}',pin)
    out=w/'trait-results';proof=out/'intake';proof.mkdir();scratch=tmp/'handwritten-install';scratch.mkdir()
    for name,tail in [('run',''),('jobs','/jobs?per_page=100'),('artifacts','/artifacts?per_page=100')]:m.save(proof/(name+'.json'),old.gh_json('api','--method','GET',f'repos/{REPO}/actions/runs/{rid}'+tail))
    rec=lock(*(m.read(proof/(n+'.json'))for n in ['run','jobs','artifacts']));m.save(proof/'sdk-lock.json',rec)
    assert rec['head']==head and rec['rid']==int(rid) and m.filesha(proof/'sdk-lock.json')==pin
    builder=w/'builder';h=builder/'scripts/handwritten-stage1';spec=m.read(m.HERE/'builder-files.json');parents=[line[7:].decode() for line in m.sha_git(builder,'cat-file','commit','HEAD').split(b'\n\n',1)[0].splitlines() if line.startswith(b'parent ')];assert parents==[spec['parent']] and head==spec['reviewed_head'] and m.sha_git(builder,'rev-parse','HEAD').decode().strip()==head and all(m.filesha(builder/f)==v['sha256']for f,v in spec['files'].items())
    sys.path.insert(0,str(h));stage=m.load('admitted_stage1',h/'stage.py');carrier=stage.file_map()
    ctx={'GITHUB_REPOSITORY':REPO,'GITHUB_SHA':head,'GITHUB_REF':'refs/heads/'+BR,'GITHUB_WORKFLOW_REF':REPO+'/.github/workflows/ci.yml@refs/heads/'+BR,'GITHUB_RUN_ID':rid,'GITHUB_RUN_ATTEMPT':'1'}
    old.released(scratch,proof);archive,=(scratch/'signed').glob('*.tar.gz');fixed=signed(scratch/'fixed',archive)
    pool=tmp/'ctfe22-root-sdks';pool.mkdir();meta=proof/'role-material';meta.mkdir();result={}
    for role in ROLES:
        srv=rec['roles'][role];z=scratch/(role+'.zip');old.gh_bytes(f"repos/{REPO}/actions/artifacts/{srv['id']}/zip",z,srv['bytes'],srv['sha256'])
        origin=scratch/role;unpack(z,origin,role);ident=check_archive(role,origin,stage,ctx,carrier);sdk=pool/role;inv=extract(origin,sdk)
        dest=meta/role;dest.mkdir()
        for f in origin.iterdir():
            if f.name!='sdk.tar.zst':shutil.copyfile(f,dest/('built-sdk-inventory.json' if f.name=='sdk-inventory.json' else f.name))
        for rel,src in fixed.items():
            f=sdk/rel;f.parent.mkdir(parents=True,exist_ok=True);assert not f.is_symlink();shutil.copy2(src,f)
            inv[rel]={'sha256':m.filesha(f),'bytes':f.stat().st_size,'mode':0o755}
        m.save(dest/'sdk-inventory.json',inv)
        rlib='lib/'+ident['driver'];runtime={n:inv[n]['sha256']for n in ['bin/cargo','bin/rustc','bin/rustdoc',rlib,*('lib/'+q for q in ident['resolved_llvm'])]}
        assert runtime[rlib]==ident['driver_sha256'] and runtime['bin/rustc']==ident['rustc_sha256'] and runtime['bin/cargo']==m.P['signed_cargo_sha256']
        clean={'PATH':'/usr/bin:/bin','HOME':str(scratch),'LC_ALL':'C.UTF-8'}
        actual=subprocess.check_output([sdk/'bin/rustc','-vV'],env=clean,text=True);assert actual==ident['rustc_vV']
        link=subprocess.check_output(['ldd',sdk/'bin/rustc'],text=True,env=clean);assert 'not found' not in link
        mapped={n:Path(p)for n,p in re.findall(r'(?m)^\s*(\S+) => (\S+)',link)}
        assert all(mapped[k].samefile(sdk/'lib'/k)for k in [ident['driver'],*ident['resolved_llvm']])
        assert Path(subprocess.check_output([sdk/'bin/rustc','--print','sysroot'],env=clean,text=True).strip()).resolve()==sdk
        assert 'commit-hash: '+m.P['signed_cargo_commit']+'\n' in subprocess.check_output([sdk/'bin/cargo','-Vv'],env=clean,text=True)
        result[role]={'source':m.P['roles'][role],'runtime':runtime,'stage1_archive':m.filesha(origin/'sdk.tar.zst'),'server':srv}
    m.save(out/'intake.json',{'installed':result,'sdk_lock_sha256':pin,'signed_cargo_sha256':m.P['signed_cargo_sha256'],'build_run':int(rid),'build_head':head})
if __name__=='__main__':main()
