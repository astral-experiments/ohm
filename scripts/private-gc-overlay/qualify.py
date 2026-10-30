"""Build physically authenticated branches and run the original twelve overlay regressions."""
from pathlib import Path
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'gc-mount-evidence'))
import build_candidate as b

def save(p, value):
    with p.open('x') as f:
        json.dump(value,f,indent=2,sort_keys=True);f.write('\n')

def run(out,label,args,root,env):
    v=subprocess.run(list(map(str,args)),cwd=root,env=env,capture_output=True,timeout=1800)
    for name,data in [('stdout',v.stdout),('stderr',v.stderr)]:
        (out/(label+'.'+name+'.gz')).write_bytes(gzip.compress(data,mtime=0))
    save(out/(label+'.json'),{'args':list(map(str,args)),'exit':v.returncode,'stdout':hashlib.sha256(v.stdout).hexdigest(),'stderr':hashlib.sha256(v.stderr).hexdigest()})
    return v

def execute(role,root):
    b.HERE=HERE/'sources'/role
    b.main(root,HERE.parent/'ohm-apple-zmij/cargo293/source.pack')

def suites(role,root):
    src=root/'source';cert=root/'build-cert';spec=json.loads((HERE/'sources'/role/'candidate-source/spec.json').read_bytes());assert b.materialize.git(src,'rev-parse','HEAD').decode().strip()==spec['head']
    assert b.materialize.hash_files(src,spec['head'])['mode_path_sha256_inventory']==spec['inventory']
    assert subprocess.check_output(['findmnt','-T',root,'-n','-o','FSTYPE']).decode().strip()=='overlay'
    original=json.loads((HERE/'failed-original.json').read_bytes());names=set(original['names']);assert len(names)==12
    env=dict(os.environ); target=Path(env['RUNNER_TEMP'])/'cargo-tests'
    for key in ('RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','CARGO_BUILD_BUILD_DIR','CARGO_TARGET_DIR','TMPDIR','CARGO_HOME','RUSTUP_TOOLCHAIN'):
        env.pop(key,None)
    tmp=Path(tempfile.mkdtemp(dir=env['RUNNER_TEMP'],prefix='private-gc-suite-tmp-'))
    env.update(CARGO_TARGET_DIR=str(target),TMPDIR=str(tmp),CARGO_HOME=str(root/'stable-registry'),CARGO_PROFILE_DEV_DEBUG='1',CARGO_PROFILE_TEST_DEBUG='1',CARGO_INCREMENTAL='0',RUSTUP_TOOLCHAIN='1.99.0',LANG='C.UTF-8')
    version=run(cert,'official-version',['rustc','+1.99.0','-vV'],src,env);assert version.returncode==0 and b'commit-hash: b940084d' in version.stdout,version.stdout
    result=run(cert,'official-build',['cargo','+1.99.0','test','--locked','-p','cargo','--lib','--test','testsuite','--no-run','-j12','--message-format=json'],src,env)
    assert result.returncode==0,result.stderr.decode()[-5000:]
    events=[json.loads(v) for v in result.stdout.splitlines() if v.startswith(b'{')]
    assert events[-1]=={'reason':'build-finished','success':True}
    def binary(kind,name):
        found,=[Path(e['executable']) for e in events if e['reason']=='compiler-artifact' and e['target']['kind']==[kind] and e['target']['name']==name and e['executable']]
        assert found.is_relative_to(target);return found
    suite=binary('test','testsuite');unit=binary('lib','cargo')
    cli=target/'debug/cargo';assert cli.is_file() and os.access(cli,os.X_OK)
    jobs={}
    for label,exe,wanted in [('profile-unit',unit,{'workspace::build_cache_gc::worktrees::idle::tests::stock_build_can_finish_opening_a_profile_after_discovery'}),('old-twelve',suite,names)]:
        listed=run(cert,label+'-list',[exe,'--list'],src,env)
        assert listed.returncode==0 and wanted<={r[:-6] for r in listed.stdout.decode().splitlines() if r.endswith(': test')}
        p=run(cert,label,[exe,'--color','never','--test-threads=4','--exact',*sorted(wanted)],src,env)
        rows={n:s for n,s in re.findall(r'(?m)^test (\S+) \.\.\. (ok|FAILED|ignored)$',p.stdout.decode())}
        assert set(rows)==wanted,label
        jobs[label]={'binary':b.digest(exe),'exit':p.returncode,'rows':rows}
    data={'source':spec,'official_rust':version.stdout.decode(),'official_cargo':b.digest(cli),'compiled_fixture_root':str(target),
          'actual_filesystem':subprocess.check_output(['findmnt','-T',target,'-n','-o','TARGET,SOURCE,FSTYPE']).decode().strip(),'jobs':jobs,'previous':original}
    save(cert/'suite-verdict.json',data)
    print(role,{k:list(v['rows'].values()).count('ok') for k,v in jobs.items()},flush=True)
    assert all(v['exit']==0 and all(q=='ok' for q in v['rows'].values()) for v in jobs.values()),jobs

if __name__=='__main__':{'build':execute,'tests':suites}[sys.argv[1]](sys.argv[2],Path(sys.argv[3]).resolve())
