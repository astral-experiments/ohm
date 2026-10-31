"""Single hosted strict Cargo acquisition. The independent verifier reads the raw stream."""
import argparse
import gzip
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
QA = '9d1dd09be4d2346142957cc298093d8a75c755c3'
FIXED = '035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4'
SIGNED = '4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e'
RUSTC = 'f7663fb7dec7e5c7ea613a85ff1d6e4c00bf97b8c50534f17e5c95cd599712b9'
DRIVER = 'dae4f8dc64b2b2ac9dc04dfe2cfad633d6af1a87da2dfc532e757ffe758680e3'
WILD = '0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5'
RON = 'fd490c5b18261893f14449cbd28cb9c0b637aebf161cd77900bfdedaff21ec32'
DERIVE = 'e7a5d71263a5a7d47b41f6b3f06ba276f10cc18b0931f1799f710578e2309348'
SERDE = 'serde_derive-1.0.229.crate'
WARN=b'\n#[deprecated(note = "OHM_QA_PRESERVED_WARNING")]\nconst OHM_QA_OLD_CONST: u8 = 17;\n#[warn(deprecated)]\nconst _: u8 = OHM_QA_OLD_CONST;\n'
BAD=b'\nconst _: u8 = "OHM_RON_CHECK_BAD_TYPE";\n'
ROLES=('build_rustc','generator','unicode_rustc','ron')
ORDERS=('TS','ST','ST','TS','ST','TS','TS','ST')

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


def move_states(m, label):
    archive=m.R/'saved'/label; archive.mkdir(parents=True,exist_ok=False)
    for name in ('target','shared','ron-session'):
        old=m.S/name
        if old.exists():old.rename(archive/name)
        assert not old.exists()


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


def fingerprint(m,p):
    s=p.stat()
    return {'path':str(p),'identity':[s.st_dev,s.st_ino],'bytes':s.st_size,'sha256':m.sha(p)}


def observe(m,name,mode,selector,wild,command,env=None,cwd=None):
    dest=m.O/name;dest.mkdir(parents=True,exist_ok=False)
    trace=dest/'trace';trace.mkdir()
    invocation=[m.R/'tree-counter',trace,mode,selector,wild,*command]
    p=subprocess.run(invocation,cwd=cwd,env=env,capture_output=True,timeout=1200)
    m.gz(dest/'stdout.gz',p.stdout);m.gz(dest/'stderr.gz',p.stderr)
    m.save(dest/'visit.json',{'observer':mode,'command':list(map(str,command)),'returncode':p.returncode})
    assert (trace/'counts.tsv').is_file(), (name,p.stderr[-1400:])
    return dest,p


def calibration(m):
    from verify import calibration_result
    assert m.sha(m.counter_fixture)=='dacd1dd7fef85cacb44a236e0c4191d95db036a623b2a01ae3a5d76d2f3d0b0e'
    for src,out,extra in [(HERE/'tree-counter.c','tree-counter',[]),(HERE/'cal-fanout.c','cal-fanout',[]),
                          (m.HERE/'calibration_driver.c','cal-driver',[]),(m.counter_fixture,'cal-loop',['-pthread'])]:
        subprocess.run(['cc','-O2','-Wall','-Wextra','-Werror',*extra,src,'-o',m.R/out],check=True)
    d=m.R/'calibrators';d.mkdir()
    for role in ROLES:shutil.copy2(m.R/'cal-driver',d/role)
    assert len({(d/r).stat().st_ino for r in ROLES})==4
    n=10_000_000
    (m.O/'calibration').mkdir()
    for mode in ('cal','sham'):
        for i,q in enumerate((0,n,0,n)):
            _,p=observe(m,f'calibration/{mode}-{i}',mode,d,'-',[m.R/'cal-fanout',d,m.R/'cal-loop',str(q)])
            assert p.returncode==0
    result=calibration_result(m.O)
    m.save(m.O/'calibration-verdict.json',result)
    assert result['admitted'],result


def command(m,name,mode,env):
    dest,p=observe(m,name,mode,m.R/'sdk-21/bin/rustc',m.R/'sdk-21/lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd',m.cmd,env,m.src)
    expected=101 if name in ('warm-invalid','independent-empty-invalid') else 0
    assert p.returncode==expected,(name,p.returncode,p.stderr[-1400:])
    stream=[json.loads(k) for k in p.stdout.splitlines()]
    assert stream[-1]=={'reason':'build-finished','success':not expected}
    output,=[Path(v['out_dir']) for v in stream if v['reason']=='build-script-executed' and v['package_id'].split('#')[0].endswith('/crates/ruff_unicode_names2')]
    assert output.resolve().is_relative_to(m.S)
    files={}
    for n in ('generated.rs','generated_phf.rs','generated_alias.rs'):
        f=output/n;files[n]=fingerprint(m,f)|{'mtime_ns':f.stat().st_mtime_ns}
    ar,=[x for x in stream if x['reason']=='compiler-artifact' and x['target']['name']=='unicode_names2' and x['target']['kind']==['lib']]
    meta,=[Path(x) for x in ar['filenames'] if x.endswith('.rmeta')]
    m.save(dest/'products.json',{'generated':files,'metadata':fingerprint(m,meta),
           'historical_source':m.sha(m.src/m.changed),'test_source':m.sha(m.src/'crates/ty_project/src/lib.rs'),
           'lock':m.sha(m.src/'Cargo.lock')})
    print(name,mode,p.returncode,'complete',flush=True)


def main(args):
    m=load_original(args);assert m.sha(args.cargo)==FIXED
    env=m.acquire();locked=registry(m,env)
    for key in ('RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','CI','RUSTFLAGS','CARGO_LOG','CARGO_INCREMENTAL','GITHUB_TOKEN','GH_TOKEN'):assert key not in env
    sdk=m.R/'sdk-21';cargo=sdk/'bin/cargo';rust=sdk/'bin/rustc';driver,=(sdk/'lib').glob('librustc_driver*.so')
    wild=sdk/'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd'
    assert [m.sha(p) for p in (cargo,rust,driver,wild)]==[SIGNED,RUSTC,DRIVER,WILD]
    cargo.rename(m.R/'retained-signed-cargo');shutil.copy2(args.cargo,cargo);cargo.chmod(0o755)
    version=m.get(['cargo','+ohm','-Vv'],env=env).decode()
    assert m.sha(cargo)==FIXED and '761ea115605c34f11a1cd29afd68812c1e1359dd' in version
    lib=m.src/'crates/ty_project/src/lib.rs';baseline=lib.read_bytes()
    sources=['crates/ruff_unicode_names2/build.rs','crates/ruff_unicode_names2/src/lib.rs',
             'crates/ruff_unicode_names2/data/UnicodeData.txt','crates/ruff_unicode_names2/data/NameAliases.txt',
             'crates/ruff_unicode_names2_generator/src/lib.rs']
    digests={f:m.sha(m.src/f) for f in sources}
    assert all(m.h(m.w.git(m.src,'show',m.c.RUFF+':'+f))==v for f,v in digests.items())
    m.save(m.O/'strict-subject.json',{'tools':{k:fingerprint(m,p) for k,p in [('cargo',cargo),('rustc',rust),('driver',driver),('wild',wild)]},
           'version':version,'registry':locked,'unicode_source':digests,'runner_script_hashes':{f.name:m.sha(f) for f in HERE.iterdir() if f.is_file()},
           'source':m.c.RUFF,'lock':m.c.LOCK,'hist':m.hist,'argv':m.cmd})
    calibration(m)
    move_states(m,'acquisition-only')
    lib.write_bytes(baseline+WARN)
    command(m,'cold-original','roster',env)
    m.run(['git','-C',m.src,'apply','--reverse','-'],input=gzip.decompress((m.HERE/'historical.patch.gz').read_bytes()))
    assert (m.src/m.changed).read_bytes()==m.w.git(m.src,'show',m.hist+'^:'+m.changed)
    assert set(m.w.git(m.src,'diff','--name-only').decode().splitlines())=={m.changed,'crates/ty_project/src/lib.rs'}
    command(m,'historical-edit','roster',env)
    for i,order in enumerate(ORDERS,1):
        for mode in order:
            command(m,f'pair-{i:02d}-{mode}','roster' if mode=='T' else 'sham',env)
    lib.write_bytes(baseline+WARN+BAD)
    command(m,'warm-invalid','roster',env)
    lib.write_bytes(baseline+WARN)
    command(m,'warm-repair','roster',env)
    move_states(m,'original-history');m.w.room(m.R,15)
    lib.write_bytes(baseline+WARN+BAD)
    command(m,'independent-empty-invalid','roster',env)
    lib.write_bytes(baseline+WARN)
    command(m,'independent-repair','roster',env)
    move_states(m,'independent-error');m.w.room(m.R,15)
    command(m,'independent-empty-edited','roster',env)
    command(m,'independent-unchanged','roster',env)
    m.save(m.O/'acquired.json',{'orders':ORDERS,'named_sources':digests,'ordinary_commands':24,'original_and_two_empty':True})


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for s in ('protocol','signed-source','counter','cargo'):ap.add_argument('--'+s,type=Path,required=True)
    main(ap.parse_args())
