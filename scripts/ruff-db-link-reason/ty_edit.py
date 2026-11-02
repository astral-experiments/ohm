"""Require a genuine ty_server edit to relink, change behavior, and match a clean build."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from install import HOST, RECORDS, ROOT, SDK, WILD, save, sha
from workspace import CENSUS, SITE, census, raw_args
sys.path.insert(0,str(SITE/'scripts/ruff-workspace-remat'))
import e2e

def main(role):
    assert role in ('23','253') and census.git(SITE,'rev-parse','HEAD')==CENSUS
    source=Path(os.environ['GITHUB_WORKSPACE'])/'ruff-e2e'
    assert census.git(source,'rev-parse',e2e.NEW+'^')==e2e.OLD
    assert set(census.git(source,'diff','--name-only',e2e.OLD,e2e.NEW).splitlines())==set(e2e.PATHS)
    assert sha(SDK/'lib/rustlib'/HOST/'bin/wild-ld/ld.bfd')==WILD
    assert not (SDK/'lib/rustlib'/HOST/'bin/wild-ld/libutil.so').exists()
    work=ROOT/'ty-edit';work.mkdir()
    state=work/'state';out=RECORDS/'ty-edit';out.mkdir()
    env=json.loads((RECORDS/'environment.json').read_text())
    for key,part in [('HOME','home'),('CARGO_HOME','cargo'),('TMPDIR','tmp')]:
        env[key]=str(work/part);(work/part).mkdir()
    env.update(LD_LIBRARY_PATH=str(SDK/'lib'),CARGO_TARGET_DIR=str(state/'target'),CARGO_BUILD_BUILD_DIR=str(state/'build'))
    census.git(source,'checkout','-q','--detach',e2e.OLD)
    assert sha(source/'Cargo.lock')==e2e.LOCK and not census.git(source,'status','--porcelain')
    with (out/'fetch.log').open('xb') as log:
        subprocess.run(['cargo','+ohm','fetch','--locked'],cwd=source,env=env,stdout=log,stderr=log,check=True,timeout=900)
    locked=tomllib.loads((source/'Cargo.lock').read_text())
    expected={q['name']+'-'+q['version']+'.crate':q['checksum'] for q in locked['package'] if 'source' in q}
    got={q.name:sha(q) for q in (work/'cargo/registry/cache').glob('*/*.crate')}
    assert len(expected)==505 and got==expected
    env['CARGO_NET_OFFLINE']='true'
    history={};catalogs={}
    for phase in ('old','new','unchanged','invalid','repaired','historical-implementation','restored-new','clean-new'):
        folder=out/phase;folder.mkdir()
        if phase=='new':census.git(source,'checkout','-q','--detach',e2e.NEW)
        if phase=='invalid':
            with (source/e2e.SESSION).open('ab') as f:f.write(e2e.INVALID)
        if phase=='historical-implementation':
            (source/e2e.SESSION).write_bytes(subprocess.check_output(['git','-C',source,'show',e2e.OLD+':'+e2e.SESSION]))
        if phase in ('repaired','restored-new'):census.git(source,'restore','--',e2e.SESSION)
        if phase=='clean-new':state.rename(work/'previous-state')
        assert sha(source/'Cargo.lock')==e2e.LOCK
        if phase not in ('historical-implementation','invalid'):
            assert not census.git(source,'status','--porcelain')
        cmd=e2e.CARGO
        if phase=='restored-new':
            cmd=['strace','-ff','-qq','-v','-e','trace=%process','-e','signal=none','-s','4096','-o',str(folder/'exec'),'--',*cmd]
        visit=subprocess.run(cmd,cwd=source,env=env,capture_output=True,timeout=1200)
        (folder/'cargo.stdout.gz').write_bytes(gzip.compress(visit.stdout,compresslevel=2))
        (folder/'cargo.stderr.gz').write_bytes(gzip.compress(visit.stderr,compresslevel=2))
        messages=[json.loads(s) for s in visit.stdout.splitlines()]
        assert messages[-1]==dict(reason='build-finished',success=phase!='invalid')
        if phase=='invalid':
            assert visit.returncode==101 and any(m['reason']=='compiler-message' and (m['message'].get('code') or {}).get('code')=='E0308' for m in messages)
            history[phase]=dict(code=visit.returncode,error='E0308');continue
        assert not visit.returncode,visit.stderr[-2000:]
        arts=[m for m in messages if m['reason']=='compiler-artifact']
        target,=[m for m in arts if m['target']['name']=='e2e' and m['target']['src_path'].startswith(str(source/'crates/ty_server'))]
        exe=Path(target['executable'])
        assert exe.is_file() and exe.resolve().is_relative_to(state)
        listing=subprocess.check_output([exe,'--list','--format','terse'],cwd=source,env=env)
        (folder/'tests.list').write_bytes(listing)
        names=e2e.test_names(listing.decode())
        assert (e2e.ADDED in names)==(phase!='old')
        case=e2e.SIBLING if phase=='old' else e2e.ADDED
        witness=subprocess.run([exe,'--exact',case,'--test-threads','1','--nocapture','--format','pretty','--color','never'],cwd=source,env=env,capture_output=True,timeout=90)
        (folder/'native.stdout').write_bytes(witness.stdout);(folder/'native.stderr').write_bytes(witness.stderr)
        negative=phase=='historical-implementation'
        assert witness.returncode==(101 if negative else 0)
        left=e2e.executed(witness.stdout.decode(),witness.stderr.decode(),case,negative)
        catalogs[phase]=names
        result=dict(code=0,sha256=sha(exe),bytes=exe.stat().st_size,executable=str(exe),tests=len(names),
                    test=case,witness=left,dirty=[m['target']['name'] for m in arts if not m['fresh']],units=len(arts))
        if phase=='restored-new':
            found=[]
            for linker in census.genealogy(folder)['linkers']:
                assert os.path.samefile(linker['path'],SDK/'lib/rustlib'/HOST/'bin/wild-ld/ld.bfd')
                if (linker['owning_rustc'] or {}).get('owner')!='e2e':continue
                lines=(folder/('exec.'+str(linker['pid']))).read_text(errors='replace').splitlines()
                calls=[p for s in lines if (p:=raw_args(s)) and os.path.exists(p[0]) and os.path.samefile(p[0],linker['path'])]
                (_,args),=calls;dest=Path(args[args.index('-o')+1]);assert dest.samefile(exe)
                found.append([linker['pid'],linker['owning_rustc']['pid'],str(dest)])
            assert len(found)==1;result['wild']=found
        history[phase]=result
        save('ty-edit/visits.json',history)
    assert set(catalogs['new'])-set(catalogs['old'])=={e2e.ADDED} and set(catalogs['old']).issubset(catalogs['new'])
    assert all(names==catalogs['new'] for phase,names in catalogs.items() if phase!='old')
    keys=('new','unchanged','repaired','restored-new','clean-new')
    assert len({history[k]['sha256'] for k in keys})==1
    assert len({history[k]['sha256'] for k in ('old','new','historical-implementation')})==3
    assert not census.git(source,'status','--porcelain')
    save('ty-edit/accepted.json',dict(role=role,pair=[e2e.OLD,e2e.NEW],old=history['old']['sha256'],
         correct=history['new']['sha256'],stale_control=history['historical-implementation']['sha256'],added=e2e.ADDED,
         warning=e2e.WARNING,actual_historical_value=history['historical-implementation']['witness'],head=os.environ['GITHUB_SHA']))
if __name__=='__main__':main(sys.argv[1])
