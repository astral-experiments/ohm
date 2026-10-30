"""Execute one unchanged integration test binary against the two enrolled Cargo executables."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import qualification as q
m=q.m

def main():
    out=m.R/'test-packet';out.mkdir()
    spec=json.loads((HERE/'spec.json').read_bytes());assert m.read(m.O/'fix-terminal.json')['product']==spec
    C=m.read(m.O/'buildkit/C/built.json'); P=m.read(m.O/'buildkit/P/built.json')
    original=m.read(m.O/'subjects.json')['environment']
    build=q.build_env(original);source=Path(C['source_directory'])
    args=['cargo','+ohm','-Zohm-defaults=no','test','--test','testsuite','--release','-p','cargo','--locked','--offline',
          '--features','ohm-defaults,all-static','--no-run','-j12','--message-format=json']
    p=q.builder(source,args,build,out/'compile')
    messages=[json.loads(line) for line in p.stdout.splitlines()]
    assert messages[-1]=={'reason':'build-finished','success':True}
    unit,=[o for o in messages if o['reason']=='compiler-artifact' and o['target']['kind']==['test'] and o['target']['name']=='testsuite']
    exe=Path(unit['executable'])
    assert exe.resolve().is_relative_to(m.R/'buildkit')
    tmp=m.R/'int-tests';env=m.w.environment(m.R,'21',tmp)
    env['CARGO_HOME']=original['CARGO_HOME']
    # Launch the exact native test harness directly. Its fixture projects get
    # new roots in Cargo's test framework for each --exact run.
    env['RUSTUP_TOOLCHAIN']='ohm'
    env.pop('CARGO_TARGET_DIR',None);env.pop('CARGO_BUILD_BUILD_DIR',None)
    known=m.get([exe,'--list','--format','terse'],cwd=source,env=env)
    q.out(out/'list.gz',known)
    for name in spec['tests']:assert (name+': test').encode() in known.splitlines()
    m.save(out/'subjects.json',{'candidate':C['cargo'],'parent':P['cargo'],'suite':q.item_stat(exe),'tests':spec['tests'],
          'selected_source':str(source),'suite_typed_output':unit,'env':env})
    def invoke(role,name,expect,required=None):
        path=out/role/name.split('::')[-1];path.mkdir(parents=True)
        trace=path/'exec.log'
        cmd=[exe,name,'--exact','--nocapture','--test-threads=1']
        result=subprocess.run(['strace','-f','-qq','-ttt','-s','32768','-e','trace=execve,execveat','-o',trace,'--',*cmd],
                              cwd=source,env=env,capture_output=True,timeout=370)
        q.out(path/'stdout.gz',result.stdout);q.out(path/'stderr.gz',result.stderr)
        raw=trace.read_bytes();q.out(path/'exec.log.gz',raw);trace.unlink()
        if result.returncode!=expect:print(role,name,result.returncode,(result.stdout+result.stderr).decode(errors='replace')[-5600:],flush=True)
        assert result.returncode==expect,(role,name,result.returncode)
        report=result.stdout+result.stderr
        if expect:
            assert b'1 failed' in report and b'E0308' in report and name.encode() in report
        else:
            assert b'1 passed; 0 failed' in report and name.encode() in report
        # Concretely locate the binary the suite embedded at compile time. A
        # strace successful exec or matching resumed exec is required; all
        # recorded real target invocations must resolve to that single path.
        complete=set()
        for line in raw.splitlines():
            match=re.match(rb'^(\d+)\s+[0-9.]+\s+<\.\.\. execve resumed>.*= 0$',line)
            if match:complete.add(int(match[1]))
        native=[]
        for line in raw.splitlines():
            match=re.match(rb'^(\d+)\s+[0-9.]+\s+execve\("([^"\\]+)",\s*\[(.*?)\],',line)
            if not match:continue
            candidate=Path(os.fsdecode(match[2]))
            if candidate.name!='cargo' or not candidate.is_relative_to(m.R/'buildkit'):continue
            assert candidate.is_file() and (line.endswith(b'= 0') or b'<unfinished ...>' in line and int(match[1]) in complete)
            native.append([int(match[1]),str(candidate),match[3].decode(errors='replace')])
        assert native and len({r[1] for r in native})==1,(role,name,len(native))
        at=Path(native[0][1]);sha=m.sha(at)
        if required:assert str(at)==required[0] and sha==required[1]
        m.save(path/'result.json',{'role':role,'name':name,'exit':result.returncode,'cargo':q.item_stat(at),'native_argv':native,
            'stdout_sha256':m.h(result.stdout),'stderr_sha256':m.h(result.stderr),'trace_sha256':m.h(raw)})
        return at
    discovery=invoke('discovery',spec['tests'][0],0)
    assert discovery.is_relative_to(m.R/'buildkit') and discovery.is_file() and not discovery.is_symlink()
    backup=discovery.with_name(discovery.name+'.before-diagnostic-qualification')
    assert not backup.exists()
    discovery.rename(backup)
    records=[]
    try:
        for name,subject in [('parent',P),('fixed',C)]:
            fresh=discovery.with_name(discovery.name+'.qa-test-install')
            assert not fresh.exists()
            shutil.copyfile(subject['cargo']['path'],fresh);fresh.chmod(0o755);os.replace(fresh,discovery)
            version=m.get([discovery,'-Vv'],env=env).decode()
            assert 'commit-hash: '+subject['source']['commit'] in version and m.sha(discovery)==subject['cargo']['sha256']
            for i,fn in enumerate(spec['tests']):
                want=101 if name=='parent' and i==0 else 0
                invoke(name,fn,want,[str(discovery),subject['cargo']['sha256']])
                records.append([name,fn,want])
    finally:os.replace(backup,discovery)
    m.save(out/'terminal.json',{'test_results':records,'matched_suite':q.item_stat(exe),'restored':q.item_stat(discovery)})
    print('All eight matched-source test outcomes met their expected clean/red verdicts',flush=True)
if __name__=='__main__':main()
