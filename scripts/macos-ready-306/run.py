"""Capture the real, unmodified Cargo integration testcase and each generated fixture on macOS."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'cargo-diagnostic-fix'))
import materialize
sys.path.insert(0,str(HERE));import diagnose
NAME='ohm_ready_tests::uses_current_runtime_inputs_and_ignores_disabled_binaries'
PARENT='2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c'
CANDIDATE='c7f394c8c9aaef1272c621ff11d77dcf569ed94b'
TESTSHA='03d2fa196a80c0af1c67ece2fb2cf952e15c60caae0419e115fd5a2459fd2aa5'
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def gz(path,buf):
    with gzip.open(path,'xb') as f:f.write(buf)
def save(path,d):
    with path.open('x') as f:json.dump(d,f,sort_keys=True,indent=2);f.write('\n')
def roster(w):
    # ps only when the real binary is in flight; never modify its generated project.
    rows={}
    for l in subprocess.check_output(['/bin/ps','-axo','pid=,ppid=,state=,command='],text=True,errors='replace').splitlines():
        parts=l.strip().split(None,3)
        if len(parts)==4 and parts[0].isdigit() and parts[1].isdigit():rows[int(parts[0])]=(int(parts[1]),*parts[2:])
    allp={w};front={w}
    while front:
        front={i for i,r in rows.items() if r[0] in front and i not in allp};allp.update(front)
    return {i:r for i,r in rows.items() if i in allp}
def controls(fixture):
    p=fixture/'foo/control'
    return {f.name:[f.stat().st_mtime_ns,f.read_text()] for f in p.glob('*') if f.is_file()}
def main():
    assert sys.platform=='darwin' and os.uname().machine=='arm64'
    role=sys.argv[1];assert role in ('parent','candidate')
    root=Path(os.environ['RUNNER_TEMP'])/'ready-306';root.mkdir();base=root/'source';out=root/'record';out.mkdir();bundle=root/'deltas';bundle.mkdir()
    features=HERE.parent/'gc-mount-evidence/candidate-source'
    spec=json.loads((features/'spec.json').read_bytes());assert spec['parent']==PARENT and spec['head']==CANDIDATE
    for n in ('parent.commit','parent.patch.gz'):shutil.copyfile(materialize.HERE/n,bundle/n)
    for ch in spec['commits']:
        for end in ('.commit','.patch.gz'):
            n=ch['key']+end;shutil.copyfile(features/n,bundle/n)
    materialize.HERE=bundle;tree=materialize.tree(base,HERE.parent/'ohm-apple-zmij/cargo293/source.pack',spec if role=='candidate' else None)
    assert tree['commit']==(CANDIDATE if role=='candidate' else PARENT) and sha(base/'tests/testsuite/ohm_ready_tests.rs')==TESTSHA
    if role=='candidate':assert tree['mode_path_sha256_inventory']==spec['inventory']
    cargo=['cargo','+1.99.0'];want=['test','-p','cargo','--test','testsuite']
    tdir=Path(os.environ['CARGO_TARGET_DIR']);assert tdir==root.parent/'cargo-tests'
    product=base/'tests/testsuite/ohm_ready_tests.rs'
    save(out/'source.json',{'tree':tree,'fixture':sha(product),'qa':os.environ['GITHUB_SHA'],'run':os.environ['GITHUB_RUN_ID'],'role':role,'uname':list(os.uname()),'rustc':subprocess.check_output(['rustc','+1.99.0','-vV'],text=True),'sw_vers':subprocess.check_output(['/usr/bin/sw_vers'],text=True),'cpu':subprocess.check_output(['/usr/sbin/sysctl','-n','hw.activecpu'],text=True).strip()})
    build=subprocess.run([*cargo,*want,'--no-run','--message-format=json'],cwd=base,capture_output=True,timeout=1050)
    gz(out/'build.stdout.gz',build.stdout);gz(out/'build.stderr.gz',build.stderr)
    assert build.returncode==0,build.stderr[-1800:];messages=[json.loads(x) for x in build.stdout.splitlines()];assert messages[-1]=={'reason':'build-finished','success':True}
    def artifact(name,kind):
        a,=[m for m in messages if m['reason']=='compiler-artifact' and m['target']['name']==name and m['target']['kind']==[kind] and m.get('executable')];assert not a['fresh'];return Path(a['executable'])
    suite=artifact('testsuite','test');subject=artifact('cargo','bin')
    assert suite.is_relative_to(tdir) and subject==tdir/'debug/cargo'
    assert [x for x in subprocess.check_output([suite,'--list'],cwd=base,text=True).splitlines() if x==NAME+': test']==[NAME+': test']
    save(out/'products.json',{'suite':str(suite),'suite_sha256':sha(suite),'cargo':str(subject),'cargo_sha256':sha(subject),'version':subprocess.check_output([subject,'-Vv'],cwd=base,text=True),'fixture':sha(product)})
    fixture=tdir/'tmp/cit/testsuite/ohm_ready_tests'/NAME.split('::')[-1];summary=[]
    previous_subject=sha(subject)
    failures=0
    # The early process sampler can perturb the scheduling window. Leave all builds
    # uninstrumented until the actual edited z wrapper has already waited for two seconds.
    for number in range(1,61):
        folder=out/f'visit-{number:02}';folder.mkdir();start=time.monotonic()
        cmd=[*cargo,*want,'--',NAME,'--exact','--nocapture']
        env=os.environ.copy();env.pop('QA_READY_DELAY_MS',None);env.pop('QA_READY_LOG',None)
        observed=None;slow_since=None;active_stamp=None;released=False
        watched_tag=fixture/'foo/control/slow-active';outcome_tag=fixture/'foo/control/a-timing'
        dest1=folder/'stdout';dest2=folder/'stderr';trans=[];last=None
        with dest1.open('xb') as o1,dest2.open('xb') as o2:
            proc=subprocess.Popen(cmd,cwd=base,stdout=o1,stderr=o2,env=env)
            while proc.poll() is None:
                assert time.monotonic()-start<120
                try:
                    stamp=(watched_tag.stat().st_mtime_ns,watched_tag.read_text())
                except FileNotFoundError:stamp=None
                if stamp and stamp!=active_stamp:slow_since=time.monotonic();active_stamp=stamp
                # Avoid samples of the prior visit's completed fixture (a-timing exists)
                # and all short-lived ordinary cases, including the fallback preparation.
                if stamp and not outcome_tag.exists() and slow_since is not None and time.monotonic()-slow_since>2.15:
                    if observed is None:
                        now=roster(proc.pid);observed=diagnose.stacks(folder,now,fixture);save(folder/'stall.json',observed)
                    now=roster(proc.pid);exists=controls(fixture);sig=([*sorted(now)],exists)
                    if sig!=last:trans.append({'since':time.monotonic()-start,'processes':now,'control':exists});last=sig
                    # Preserve the first actual timeout. On exactly the next stall, release
                    # only the test wrapper after 5s; compare real semantic output afterward.
                    if not released and failures==1 and time.monotonic()-slow_since>5.0:
                        try:
                            with outcome_tag.open('x') as m:m.write('diagnostic release')
                        except FileExistsError:pass
                        else:
                            released=True;save(folder/'release.json',{'state':controls(fixture),'elapsed':time.monotonic()-start})
                time.sleep(.11)
        stdout=dest1.read_bytes();stderr=dest2.read_bytes();dest1.unlink();dest2.unlink();gz(folder/'stdout.gz',stdout);gz(folder/'stderr.gz',stderr)
        item={'exit':proc.returncode,'argv':cmd,'root':str(fixture),'control':controls(fixture),'duration':time.monotonic()-start,'number':number}
        assert b'running 1 test' in stdout and NAME.encode() in stdout
        item['diagnostic']=released;item['delay_ms']=0;item['had_stall']=observed is not None
        save(folder/'final-snapshot.json',diagnose.fixture_snapshot(fixture))
        item['timeout_message']=b'ready test never started' in stdout+stderr
        item['raw_pass']=b'test result: ok. 1 passed; 0 failed;' in stdout and proc.returncode==0
        if item['raw_pass']:
            ctl=item['control'];assert ctl['runs'][1]=='a\n' and ctl['a-timing'][1]=='during' and ctl['current-binary'][1]=='yes'
        else:
            # Preserve all nonmatching failures; only the exact investigating exception is classified.
            item['same_original_failure']=item['timeout_message'] and proc.returncode==101 and b'could not compile `z`' in stdout+stderr
        exe=fixture/'ready-wrapper/target/debug/ready-wrapper';assert exe.is_file()
        item['wrapper_sha']=sha(exe)
        item['files']={str(p.relative_to(fixture)):[p.stat().st_mtime_ns,p.stat().st_size] for p in (fixture/'foo/target/debug').rglob('*') if p.is_file() and (p.name.startswith(('a-','z-','runtime-')) or p.name in ('output','value','a'))}
        save(folder/'result.json',item);gz(folder/'observer.json.gz',json.dumps(trans,sort_keys=True).encode());summary.append([number,proc.returncode,item['raw_pass'],item['timeout_message']]);print(role,summary[-1],flush=True)
        if item['timeout_message'] or released:failures+=1
        if failures>=3:break
    save(out/'terminal.json',{'role':role,'visits':summary,'product_unchanged':sha(subject)==previous_subject})
if __name__=='__main__':main()
