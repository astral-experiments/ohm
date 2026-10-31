"""Prospective disposable Linux runner. Public inputs are fixed in PROTOCOL.md."""
import argparse
import collections
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tomllib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from native_control import run_control

QA = '9d1dd09be4d2346142957cc298093d8a75c755c3'
FIXED = 'f1a88bf5fb2bf431eeea068455d9d4e98dcfbfee3dc381ee47cc7c96df3e128f'
SIGNED = '4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e'
RON = 'fd490c5b18261893f14449cbd28cb9c0b637aebf161cd77900bfdedaff21ec32'
DERIVE = 'e7a5d71263a5a7d47b41f6b3f06ba276f10cc18b0931f1799f710578e2309348'
SERDE = 'serde_derive-1.0.229.crate'
PHASES = ('train','edit','repeat','second','invalid','repair','repaired-repeat','profile','empty-edited')


def load_original(args):
    protocol = args.protocol.resolve()
    assert subprocess.check_output(['git','-C',protocol,'rev-parse','HEAD']).decode().strip()==QA
    module = protocol / 'scripts/ron-check-share/measure.py'
    old = sys.argv
    try:
        sys.argv=[str(module),str(args.signed_source.resolve()),str(args.counter.resolve())]
        spec=importlib.util.spec_from_file_location('original_ron_qualification',module)
        m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    finally:
        sys.argv=old
    return m


def census(path):
    if not path.exists(): return {'logical':0,'allocated':0,'files':{}}
    files={}; seen=set(); size=0; allocated=0
    for p in sorted(path.rglob('*')):
        assert not p.is_symlink()
        if not p.is_file(): continue
        st=p.stat(); ident=(st.st_dev,st.st_ino)
        files[str(p.relative_to(path))]=[st.st_size,st.st_blocks*512,*ident]
        if ident not in seen:
            seen.add(ident); size+=st.st_size; allocated+=st.st_blocks*512
    return {'logical':size,'allocated':allocated,'files':files}


def allocation(paths):
    seen=set(); files=0; logical=0; allocated=0
    for root in paths:
        if not root.exists():continue
        for p in root.rglob('*'):
            if p.is_symlink() or not p.is_file():continue
            s=p.stat();key=(s.st_dev,s.st_ino)
            if key in seen:continue
            seen.add(key);files+=1;logical+=s.st_size;allocated+=s.st_blocks*512
    return {'physical_regular_files':files,'logical':logical,'allocated':allocated}


def move_states(m, label):
    archive=m.R/'saved'/label; archive.mkdir(parents=True,exist_ok=False)
    for name in ('target','shared','ron-session'):
        old=m.S/name
        if old.exists():old.rename(archive/name)
        assert not old.exists()


def source(m, which):
    f=m.src/m.changed
    assert m.sha(m.src/'Cargo.lock')==m.c.LOCK
    f.write_bytes(m.w.git(m.src,'show',which+':'+m.changed))


def registry(m,env):
    locked={r['name']+'-'+r['version']+'.crate':r['checksum'] for r in tomllib.loads((m.src/'Cargo.lock').read_text())['package'] if 'checksum' in r}
    files={p.name:p for p in (Path(env['CARGO_HOME'])/'registry/cache').glob('*/*.crate')}
    assert len(locked)==498 and set(locked)==set(files)
    assert {n:m.sha(p) for n,p in files.items()}==locked
    assert locked['ron-0.12.0.crate']==RON and locked[SERDE]==DERIVE
    with tarfile.open(files['ron-0.12.0.crate']) as contents:
        held=json.load(contents.extractfile('ron-0.12.0/.cargo_vcs_info.json'))
        assert held['git']['sha1']=='c6a8cff1eff986cc1ad9b026e838335187d411f0'
    return locked


def one(m, mode, phase, env):
    label=mode+'/'+phase
    dest=m.O/label
    profile=m.O/(mode+'-profiles') if phase=='profile' else None
    if profile:profile.mkdir()
    session=m.S/'ron-session'
    (m.R/'policy').write_text(f'{mode} {session} {profile or "none"}\n')
    p,cc,events=m.observe(label,m.R/'sdk-21/bin/rustc','ron',m.cmd,env,m.src)
    # Preserve all literal argv in observe/trace; only adapt the *old parser's*
    # no-incremental precondition after verifying every experimental flag exactly.
    adapted=[]; selected=[]
    for pid,ident,match,image,argv in events:
        if match:
            assert argv[argv.index('--crate-name')+1]=='ron'
            special = [a for a in argv if a.startswith(('-Cincremental=', '-Zself-profile'))]
            expect=([f'-Cincremental={session}'] if mode=='session' else [])
            if profile: expect.extend([f'-Zself-profile={profile}','-Zself-profile-events=generic-activity,function-args,incr-cache-load'])
            assert special==expect
            selected.append(argv)
            argv=[a for a in argv if a not in special]
        adapted.append([pid,ident,match,image,argv])
    report=m.facts(p,cc,adapted,env,dest,label)
    assert selected and len(selected)==1 and m.hw(cc['whole']) and m.hw(cc['selected'])
    assert report['native_ron_marker'] and any(v[2]>0 for v in report['native_ron_marker'])
    assert p.returncode==(101 if phase=='invalid' else 0)
    msgs=[json.loads(l) for l in p.stdout.splitlines()]
    errors=[l['message'] for l in msgs if l.get('message',{}).get('level')=='error']
    if phase=='invalid':
        typed=[a for a in errors if (a.get('code') or {}).get('code')=='E0308']
        assert len(typed)==1 and any(s['is_primary'] and s['file_name'].endswith('ty_project/src/lib.rs') and any('RON_STUDY_INVALID' in t['text'] for t in s['text']) for s in typed[0]['spans'])
    else:assert not errors
    if phase in ('repeat','second','profile'):
        assert [row[1] for row in report['actual_rustcs']]==['ron'] and not report['native_links']
    assert report['unit_count']==(302 if phase=='invalid' else 303)
    art,=[a for a in msgs if a['reason']=='compiler-artifact' and a['target']['name']=='ron' and a['target']['kind']==['lib']]
    meta,=[Path(x) for x in art['filenames'] if x.endswith('.rmeta')]
    assert meta.is_file() and meta.stat().st_size and meta.resolve().is_relative_to(m.S)
    activity=census(session);assert (activity['allocated']>0)==(mode=='session')
    m.save(dest/'session.json',activity)
    if mode=='session':
        graphs=[Path(n).parent for n in activity['files'] if Path(n).name=='dep-graph.bin']
        tables=[Path(n).parent for n in activity['files'] if Path(n).name=='query-cache.bin']
        assert len(graphs)==1 and graphs==tables
    blob=meta.read_bytes();digest=m.h(blob);cas=m.O/'rmeta-blobs';cas.mkdir(exist_ok=True);receipt=cas/(digest+'.gz')
    if not receipt.exists():m.gz(receipt,blob)
    assert gzip.decompress(receipt.read_bytes())==blob
    closure={}
    argv=selected[0]
    for i,a in enumerate(argv[:-1]):
        if a=='--extern':
            name,filename=argv[i+1].split('=',1);f=Path(filename)
            assert f.is_file() and name not in closure;closure[name]=[str(f),f.stat().st_size,m.sha(f)]
    assert [n for n,v in closure.items() if v[0].endswith('.so')]==['serde_derive']
    m.save(dest/'observed.json',{'literal_ron_argv':selected[0],'rmeta':[str(meta),digest,len(blob)],
           'externs':closure,'regular_file_storage':allocation([m.S/n for n in ('target','shared','ron-session')]),
           'compiler_messages':[i['message'] for i in msgs if i['reason']=='compiler-message'],
           'allocated_session':activity['allocated'],'complete':True})
    return report,meta


def reader(m,env,meta,dest):
    src=m.R/'independent-reader.rs';out=m.R/'independent-reader.rmeta'
    literal=m.read(dest/'observed.json')['literal_ron_argv']
    # Ohm's shared-store layout gives dependencies separate directories. Use
    # Ron's actual closure on this visit, never an earlier generation's files.
    dirs=[literal[i+1] for i,v in enumerate(literal[:-1]) if v=='-L' and literal[i+1].startswith('dependency=')]
    assert dirs and len(set(dirs))==len(dirs) and all(Path(d.split('=',1)[1]).is_dir() for d in dirs)
    search=[a for d in dirs for a in ('-L',d)]
    records=[]
    for valid in (True, False):
        src.write_text('pub fn check() -> '+('String' if valid else 'u8')+' { ron::ser::to_string(&[17u32, 29]).unwrap() }\n')
        args=['rustc','+ohm','--edition=2024','--crate-type=lib','--crate-name=typed_ron_api',str(src),
              '--emit=metadata','--error-format=json','--extern','ron='+str(meta),'-L','dependency='+str(meta.parent),*search,'-o',str(out)]
        p=subprocess.run(args,cwd=m.src,env=env,capture_output=True)
        diags=[json.loads(v) for v in p.stderr.splitlines()]
        assert p.returncode==(0 if valid else 1)
        if valid:assert not diags and out.stat().st_size>0
        else:assert [a['code']['code'] for a in diags if a.get('code')]==['E0308']
        records.append({'argv':args,'returncode':p.returncode,'diagnostics':diags,'result':m.sha(out) if valid else None})
    m.save(dest/'reader.json',records)
    return records


def main(args):
    m=load_original(args); assert m.sha(args.cargo)==FIXED
    env=m.acquire();locked=registry(m,env)
    cargo=m.R/'sdk-21/bin/cargo'; assert m.sha(cargo)==SIGNED
    cargo.rename(m.R/'retained-signed-cargo');shutil.copy2(args.cargo,cargo);cargo.chmod(0o755);assert m.sha(cargo)==FIXED
    assert 'b76dc8006155d48a8cd7d6c5543acb9c18e2ce4b' in m.get(['cargo','+ohm','-Vv'],env=env).decode()
    m.save(m.O/'comparison-subject.json',{'cargo':FIXED,'actual_cargo':m.w.fx(cargo),'signed_other_members':m.read(m.O/'subjects.json')['tools'],
           'registry':locked,'source_files':{p.name:m.sha(p) for p in HERE.iterdir() if p.is_file()}})
    assert m.calibration()
    wrapper=m.R/'ron-wrapper';subprocess.run(['cc','-O2','-Wall','-Wextra','-Werror',HERE/'ron-wrapper.c','-o',wrapper],check=True)
    env=env|{'RUSTC_WRAPPER':str(wrapper),'RON_STUDY_POLICY':str(m.R/'policy')}
    # The boundary is a separate genuine native compile using the installed SDK.
    run_control(m.R/'native-boundary',m.O/'native-boundary',env)
    lib=m.src/'crates/ty_project/src/lib.rs'; base=lib.read_bytes()
    # Cargo's acquisition-only fetch and --unit-graph may create directories.
    # Preserve these untouched, never import their fingerprints as a warm arm.
    move_states(m,'signed-acquisition-only')
    for mode in ('sham','session'):
        m.w.room(m.R,15);source(m,m.c.RUFF)
        assert not any((m.S/n).exists() for n in ('target','shared','ron-session'))
        for phase in PHASES:
            if phase=='edit':source(m,m.hist+'^')
            if phase=='invalid':lib.write_bytes(base+b'\nconst _: u8 = "RON_STUDY_INVALID";\n')
            if phase=='repair':lib.write_bytes(base)
            if phase=='empty-edited':move_states(m,mode+'-warm')
            report,meta=one(m,mode,phase,env)
            if phase in ('repeat','empty-edited'):
                reader(m,env,meta,m.O/mode/phase)
        move_states(m,mode+'-empty')
    m.save(m.O/'acquired.json',{'order':['sham','session'],'phases':PHASES,'test':'one session mechanism only'})


if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    for key in ('protocol','signed-source','counter','cargo'):a.add_argument('--'+key,type=Path,required=True)
    main(a.parse_args())
