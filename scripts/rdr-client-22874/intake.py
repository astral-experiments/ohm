"""One exact authorized private SDK plus the eight released -22 tools used by the completed package run."""
from pathlib import Path
from zipfile import ZipFile
import hashlib, json, os, re, shutil, subprocess, sys
HERE=Path(__file__).resolve().parent;PRIOR=HERE.parent/'uv-inherent-22874';sys.path[:0]=[str(PRIOR),str(HERE.parent/'handwritten-panel')]
import core as c,history as h,enroll
m=c.m;P=m.read(HERE/'pins.json');ROLE=P['role'];REPO='astral-experiments/ohm';BR='charlie/codex-rdr-22874-uv-client'
def scope():
    assert m.P['branch'] in ('charlie/codex-20988-handwritten-stage1-check',BR);m.P['branch']=BR
    work,tmp=m.host();origin=work/'coordinator';e=os.environ
    assert e['GITHUB_REPOSITORY_ID']=='1319437234' and (e['BUILD_RUN_ID'],e['BUILD_HEAD'],e['SDK_LOCK_SHA256'])==(str(P['run']),P['head'],P['sdk_lock_sha256'])
    assert m.sha_git(origin,'rev-parse','HEAD').decode().strip()==e['REVIEWED_HEAD']
    parents=[v[7:].decode()for v in m.sha_git(origin,'cat-file','commit','HEAD').split(b'\n\n',1)[0].splitlines()if v.startswith(b'parent ')]
    assert parents==[P['carrier_parent']] and m.sha_git(work/'builder','rev-parse','HEAD').decode().strip()==P['head']
    assert (c.P['A'],c.P['B'],c.P['plan_units'],len(c.P['workspace_check_libraries']))==('fc7f936e906ba98274926c3a79fdda4e5b07bcc0','d952be66482a298658f39f314ba8c337154ed0e7',543,38)
    assert c.CHECK==['/tmp/uv-workflow-search/sdk/bin/cargo','check','--locked','--offline','-j8','-p','uv-client']
    assert 'RUSTC_WRAPPER' not in m.ENV and 'RUSTC_WORKSPACE_WRAPPER' not in m.ENV and 'OHM_RDR_OBSERVER_DIR' not in m.ENV
    return work,tmp
def service(run,jobs,artifacts):
    assert run['repository']['full_name']==run['head_repository']['full_name']==REPO and run['repository']['private'] is True
    assert (run['id'],run['head_sha'],run['head_branch'],run['run_attempt'],run['event'],run['path'],run['status'],run['conclusion'])==(P['run'],P['head'],P['producer_branch'],1,'workflow_dispatch','.github/workflows/ci.yml','completed','success')
    j,=jobs['jobs'];a,=artifacts['artifacts'];assert jobs['total_count']==artifacts['total_count']==1
    assert (j['id'],j['name'],j['head_sha'],j['run_id'],j['run_attempt'],j['status'],j['conclusion'])==(P['job'],'Public metadata observer SDK ('+ROLE+')',P['head'],P['run'],1,'completed','success')
    assert not a['expired'] and (a['id'],a['name'],a['size_in_bytes'],a['digest'])==(P['artifact']['id'],P['artifact_name'],P['artifact']['bytes'],'sha256:'+P['artifact']['sha256'])
    assert (a['workflow_run']['id'],a['workflow_run']['head_sha'],a['workflow_run']['head_branch'])==(P['run'],P['head'],P['producer_branch'])
def members(z):
    items=z.infolist(); assert len(items)==len(P['capsule']) and {q.filename for q in items}==set(P['capsule'])
    for q in items:
        assert enroll.safe_name(q.filename) and not q.is_dir() and ((q.external_attr>>16)&0o170000) in (0,0o100000) and not q.flag_bits&1 and q.file_size==P['capsule'][q.filename][0]
    return items
def inventory(sdk):
    expected=P['sdk_inventory'];present={str(f.relative_to(sdk)) for f in sdk.rglob('*')if f.is_file()}
    assert present==set(expected)
    for rel,x in expected.items():
        f=sdk/rel;assert not f.is_symlink() and f.resolve().is_relative_to(sdk.resolve()) and f.stat().st_size==x['bytes'] and f.stat().st_mode&0o777==x['mode'] and m.filesha(f)==x['sha256']
    return m.digest(m.canon(expected))
def complete_helpers(sdk,fixed,native):
    signed=m.read(m.HERE/'helpers.json')
    prefix='lib/rustlib/x86_64-unknown-linux-gnu/bin/'
    present={prefix+n for n in ('gcc-ld/ld.lld','gcc-ld/ld64.lld','gcc-ld/lld-link','gcc-ld/wasm-ld','rust-lld','rust-objcopy')}
    assert set(fixed)==set(signed) and set(native)&set(fixed)==present and set(fixed)-present=={'bin/cargo',prefix+'wild-ld/ld.bfd'}
    for rel,src in fixed.items():
        f=sdk/rel;expected=signed[rel];f.parent.mkdir(parents=True,exist_ok=True)
        assert (src.stat().st_size,m.filesha(src))==(expected['bytes'],expected['sha256']) and not src.is_symlink()
        if rel in present:
            item=native[rel]
            assert f.is_file() and not f.is_symlink() and f.resolve().is_relative_to(sdk.resolve())
            assert (f.stat().st_size,f.stat().st_mode&0o777,m.filesha(f))==(item['bytes'],item['mode'],item['sha256'])
        else:
            assert not f.exists() and not f.is_symlink()
        shutil.copy2(src,f)
        assert f.stat().st_size==expected['bytes'] and m.filesha(f)==expected['sha256']
def admit():
    w,tmp=scope();out=w/'trait-results';proof=out/'intake';proof.mkdir();scratch=tmp/'client-rdr-intake';scratch.mkdir();h.guard_space(w,tmp)
    _,previous=m.check_sources(w);old=m.load('previous_release_intake',previous/'intake.py');parts=[]
    for name,tail in [('run',''),('jobs','/jobs?per_page=100'),('artifacts','/artifacts?per_page=100')]:
        data=old.gh_json('api','--method','GET',f"repos/{REPO}/actions/runs/{P['run']}"+tail);m.save(proof/(name+'.json'),data);parts.append(data)
    service(*parts);art=P['artifact'];zpath=scratch/'observer.zip';old.gh_bytes(f"repos/{REPO}/actions/artifacts/{art['id']}/zip",zpath,art['bytes'],art['sha256'])
    capsule=scratch/'capsule';capsule.mkdir()
    with ZipFile(zpath)as z:
        for it in members(z):
            f=capsule/it.filename
            with z.open(it)as a,f.open('xb')as b:shutil.copyfileobj(a,b,1<<20)
            assert m.filesha(f)==P['capsule'][it.filename][1]
    role=m.read(capsule/'role.json');assert (role['source']['commit'],role['source']['tree'],role['source']['epoch'])==(P['rustc'],P['tree'],43311)
    smoke=m.read(capsule/'observer-smoke.json');assert smoke['visits']==['native','observer','native'] and smoke['trace_sha256']==m.filesha(capsule/'observer-fixture.rdr')
    old.released(scratch,proof);official,=(scratch/'signed').glob('*.tar.gz');fixed=enroll.signed(scratch/'fixed',official)
    sdk=tmp/'rdr-22874-admitted-sdk';native=enroll.extract(capsule,sdk)
    complete_helpers(sdk,fixed,native)
    inv=inventory(sdk);e={'PATH':'/usr/bin:/bin','HOME':str(scratch),'LC_ALL':'C.UTF-8'}
    def run(*args):return subprocess.check_output(args,env=e,text=True)
    ident=m.read(capsule/'identity.json')
    assert run(sdk/'bin/rustc','-vV')==ident['rustc_vV'] and Path(run(sdk/'bin/rustc','--print','sysroot').strip()).samefile(sdk)
    assert 'commit-hash: ed0ae15d22da9a0af9afb3d0fdeb4ceb8a71b770\n'in run(sdk/'bin/cargo','-Vv')
    ldd=run('ldd',sdk/'bin/rustc');mapped=dict(re.findall(r'(?m)^\s*(\S+) => (\S+)',ldd))
    assert 'not found'not in ldd and all(Path(mapped[n]).samefile(sdk/'lib'/n)for n in[ident['driver'],*ident['resolved_llvm']])
    src=scratch/'probe.rs';src.write_text('fn main(){assert_eq!(2+2,4);}\n');run(sdk/'bin/rustc',src,'-o',scratch/'probe');run(scratch/'probe')
    for n in ('source.json','role.json','identity.json','observer-smoke.json','sdk-inventory.json'):shutil.copyfile(capsule/n,proof/n)
    m.save(proof/'admitted.json',{'sdk':str(sdk),'source':role['source'],'capsule_hashes':P['capsule'],'sdk_inventory':inv,'ldd':ldd,'native_link_run':True,'release_archive':m.filesha(official)})
if __name__=='__main__':admit()
