"""Use the compiled Cargo library harness on native runner overlay, tmpfs and ext4."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));import build_candidate as bc
def put(path,body):
    with gzip.open(path,'xb') as f:f.write(body)
def save(path,obj):
    with path.open('x') as f:json.dump(obj,f,sort_keys=True,indent=2);f.write('\n')
PANICS={'util::counter::tests::counter_zero_slot','util::dependency_queue::test::rejects_cycle','util::git::tests::duplicate_registration_is_rejected','util::io::tests::over_the_limit'}
PRIVATE_OVERLAY='workspace::build_cache_gc::worktrees::idle::tests::stock_build_can_finish_opening_a_profile_after_discovery'
def execute(bin,source,env,out,name,flags,expect):
    p=subprocess.run([bin,*flags],cwd=source,env=env,timeout=390,capture_output=True)
    put(out/(name+'.stdout.gz'),p.stdout);put(out/(name+'.stderr.gz'),p.stderr)
    seen=re.findall(rb'^test (.+?) \.\.\. (ok|FAILED|ignored.*)$',p.stdout,re.M)
    actual={n.decode():v.decode() for n,v in seen};assert len(seen)==len(actual)
    logical={k.removesuffix(' - should panic') if k.endswith(' - should panic') and k.removesuffix(' - should panic') in PANICS else k:v for k,v in actual.items()}
    assert len(logical)==len(actual)
    summary=re.findall(rb'test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored;',p.stdout)
    rec={'command':[str(bin),*flags],'exit':p.returncode,'TMPDIR':env.get('TMPDIR'),'f_filesystem':subprocess.check_output(['stat','-f','-c','%T',env['TMPDIR']],text=True).strip(),
         'binary_sha':bc.digest(bin),'listed_expected':len(expect),'actual':actual,'logical_names':logical,'raw_names_equal':set(actual)==expect,'terminal_summary':[[v.decode() for v in s] for s in summary]}
    save(out/(name+'.json'),rec)
    return p.returncode==0 and set(logical)==expect and len(summary)==1 and int(summary[0][2])==0

def build(root):
    out=root/'build-cert';src=root/'source';build=json.loads((out/'build.json').read_bytes());env=build['env']|{'CARGO_NET_OFFLINE':'true','RUSTUP_TOOLCHAIN':'ohm'}
    cmd=['cargo','+ohm','-Zohm-defaults=no','test','--lib','--no-run','--release','--offline','--locked','-p','cargo','--features','all-static,ohm-defaults','-j12','--message-format=json']
    p=bc.run(cmd,src,env,out/'unitcompile')
    rows=[json.loads(l) for l in p.stdout.splitlines()]
    assert rows[-1]=={'reason':'build-finished','success':True}
    leaf,=[r for r in rows if r['reason']=='compiler-artifact' and r['target']['name']=='cargo' and 'lib' in r['target']['kind'] and r['profile']['test'] and r.get('executable')]
    native=Path(leaf['executable']);assert native.is_file() and not leaf['fresh'] and any(native.resolve().is_relative_to(root/p) for p in ('build-target','build-shared'))
    deliver=root/'unit-deliver';deliver.mkdir();binary=deliver/'library-tests';shutil.copyfile(native,binary);binary.chmod(0o755)
    listed=subprocess.check_output([binary,'--list'],cwd=src,env=env)
    put(out/'unit-list.gz',listed);names={v.removesuffix(': test') for v in listed.decode().splitlines() if v.endswith(': test')}
    focus={n for n in names if n.startswith('workspace::build_cache_gc')}
    assert any(n.endswith('::shared_cleanup_preserves_a_nested_mount_in_active_and_retired_trees') for n in focus)
    assert any(n.endswith('::mount_path::tests::renamed_parent_and_final_symlink') for n in focus)
    proof={'sha':bc.digest(native),'source':str(src),'candidate':build['candidate'],'qa':build['qa'],'names':sorted(names),'gc':sorted(focus),'cmd':cmd}
    assert proof['sha']==bc.digest(binary)
    for path in (deliver/'unit.json',out/'unit.json'):save(path,proof)
    success={}
    for label,parent in [('namespace-overlay',root),('tmpfs',Path('/dev/shm'))]:
        with tempfile.TemporaryDirectory(prefix='ohm-gc-units-',dir=parent) as tmp:
            success[label]=execute(binary,src,env|{'TMPDIR':tmp},out,label,['workspace::build_cache_gc','--test-threads=1','--color','never'],focus)
    ov=json.loads((out/'namespace-overlay.json').read_bytes());failed={k for k,v in ov['logical_names'].items() if v=='FAILED'}
    success['actual_overlay_failures']=sorted(failed)
    success['shared_and_other_focus_tests_green']=set(ov['logical_names'])==focus and not (failed-{PRIVATE_OVERLAY})
    success['old_private_overlay_failure_reproduced']=PRIVATE_OVERLAY in failed
    save(out/'unit-native-results.json',success)
    assert success['tmpfs'] and success['shared_and_other_focus_tests_green'],success
    print('Native focused GC suites',success,flush=True)
def ext4(root,artifact,pack):
    out=root/'packet/units';out.mkdir(parents=True,exist_ok=False)
    specdir=HERE/'candidate-source';spec=json.loads((specdir/'spec.json').read_bytes())
    u=json.loads((artifact/'unit.json').read_bytes());assert u['candidate']==spec['head'] and u['qa']==os.environ['GITHUB_SHA']
    b=artifact/'library-tests';assert bc.digest(b)==u['sha'];b.chmod(0o755)
    # libtest's compile-time source path must exist in the reader job too.
    src=Path(u['source']);assert src==root.parent/'gc-compiler-build/source' and not src.exists()
    src.parent.mkdir(exist_ok=True);holder=root/'unit-deltas';holder.mkdir();bas=bc.materialize.HERE
    for name in ('parent.commit','parent.patch.gz'):shutil.copyfile(bas/name,holder/name)
    for part in spec['commits']:
        for end in ('.commit','.patch.gz'):
            name=part['key']+end;shutil.copyfile(specdir/name,holder/name)
    bc.materialize.HERE=holder;tree=bc.materialize.tree(src,pack,spec);assert tree['mode_path_sha256_inventory']==spec['inventory'] and tree['lock']==spec['lock_sha256']
    home=root/'units-home';home.mkdir();tmp=root/'units-tmp';tmp.mkdir();shims=root/'units-bin';shims.mkdir();ru=root/'units-rustup/toolchains';ru.mkdir(parents=True)
    (ru/'ohm').symlink_to(root/'sdk-21',target_is_directory=True)
    for n in ('cargo','rustc'):(shims/n).symlink_to(shutil.which('rustup'))
    env={'LANG':'C.UTF-8','PATH':str(shims)+':/usr/local/bin:/usr/bin:/bin','TMPDIR':str(tmp),'HOME':str(home),'CARGO_HOME':str(root/'units-cargo-home'),
         'RUSTUP_HOME':str(ru.parent),'RUSTUP_TOOLCHAIN':'ohm','RUSTUP_AUTO_INSTALL':'0','CARGO_NET_OFFLINE':'true'}
    result=execute(b,src,env,out,'full-ext4',['--test-threads=1','--color','never'],set(u['names']))
    save(out/'ext4-result.json',{'full':result,'cargo_sha':bc.digest(b),'qa':u['qa'],'source':tree})
    assert result,'full ext4 library unit tests or exact returned names did not pass'
if __name__=='__main__':
    if sys.argv[1]=='build':build(Path(sys.argv[2]))
    else:ext4(Path(sys.argv[2]),Path(sys.argv[3]),Path(sys.argv[4]))
