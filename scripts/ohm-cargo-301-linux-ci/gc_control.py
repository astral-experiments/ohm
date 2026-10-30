"""Compare the shipped GC tests on a single runner and a single genuine checkout."""

import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tempfile

SOURCE = runpy.run_path(str(Path(__file__).with_name('source.py')))


def run(args, env=None, check=True):
    result = subprocess.run(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check and result.returncode:
        raise RuntimeError(result.stdout.decode(errors='replace')[-4000:])
    return result


def main():
    temp = Path(os.environ['RUNNER_TEMP'])
    output = temp / 'gc-controls'
    output.mkdir()
    roots = {'default': Path(tempfile.gettempdir()), 'runner': temp, 'shared-memory': Path('/dev/shm')}
    reports = {}
    for label, root in roots.items():
        with tempfile.TemporaryDirectory(dir=root) as physical:
            p = Path(physical)
            (p / 'directory').mkdir()
            (p / 'file').write_bytes(b'input')
            (p / 'link').symlink_to('file')
            rows = {}
            for entry in os.scandir(p):
                st = os.lstat(entry.path)
                rows[entry.name] = {'readdir_inode': entry.inode(), 'lstat_inode': st.st_ino,
                                    'device': st.st_dev, 'size': st.st_size}
            reports[label] = {'path': str(root), 'capacity': shutil.disk_usage(p)._asdict(),
                              'rows': rows, 'mount': run(['findmnt','-T',str(p),'-no','TARGET,SOURCE,FSTYPE']).stdout.decode().strip()}
    (output / 'filesystems.json').write_text(json.dumps(reports, indent=2, sort_keys=True)+'\n')
    print('Filesystems:', json.dumps(reports, sort_keys=True), flush=True)
    verdicts = {}
    source = ('src/workspace/build_cache_gc/mod.rs', 'src/workspace/build_cache_gc_roots.rs',
              'src/workspace/build_cache_gc/worktrees/at.rs', 'src/workspace/build_cache_gc/worktrees/idle/mod.rs')
    for role, rev in [('child', SOURCE['HEAD']), ('parent', SOURCE['PARENT'])]:
        run(['git','checkout','--quiet','--detach',rev])
        assert run(['git','rev-parse','HEAD']).stdout.decode().strip() == rev
        assert run(['git','status','--porcelain=v1']).stdout == b''
        env = dict(os.environ, CARGO_TARGET_DIR=str(temp/('build-gc-'+role)))
        build = run(['cargo','+'+env['RUST_VERSION'],'test','-p','cargo','--lib','--no-run','--message-format=json'], env)
        (output / (role+'-build.log')).write_bytes(build.stdout)
        events = [json.loads(line) for line in build.stdout.splitlines() if line.startswith(b'{')]
        assert {'reason':'build-finished','success':True} in events
        executable, = [Path(e['executable']) for e in events if e['reason']=='compiler-artifact' and e.get('executable') and e['target']['name']=='cargo' and e['target']['kind']==['lib']]
        assert executable.is_relative_to(Path(env['CARGO_TARGET_DIR']))
        forms = {}
        for label, root in roots.items():
            settings = env if label=='default' else dict(env,TMPDIR=str(root))
            result = run([str(executable),'workspace::build_cache_gc','--test-threads=1'], settings, check=False)
            (output/(role+'-'+label+'.log')).write_bytes(result.stdout)
            failed = sorted(n.decode() for n in re.findall(rb'(?m)^test (\S+) \.\.\. FAILED$', result.stdout))
            passed = sorted(n.decode() for n in re.findall(rb'(?m)^test (\S+) \.\.\. ok$', result.stdout))
            assert len(failed)+len(passed) >= 30 and (result.returncode==0)==(not failed)
            forms[label] = {'status':result.returncode,'failed':failed,'passed':passed}
            print(role, label, len(passed), len(failed), flush=True)
        verdicts[role] = {'commit':rev,'source':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in source},
                          'binary':hashlib.sha256(executable.read_bytes()).hexdigest(),'verdicts':forms}
    (output/'results.json').write_text(json.dumps(verdicts, indent=2, sort_keys=True)+'\n')
    assert verdicts['child']['source']==verdicts['parent']['source']
    assert verdicts['child']['verdicts']==verdicts['parent']['verdicts'], 'the direct parent has different native verdicts'
    print('Physical parent/child outcomes match on every tested filesystem.', flush=True)


if __name__=='__main__':
    main()
